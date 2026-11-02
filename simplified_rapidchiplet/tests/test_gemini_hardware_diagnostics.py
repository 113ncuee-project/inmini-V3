"""Physical invariants and measured schedule diagnostics for the new template."""
from dataclasses import replace
import math
import unittest

from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures, resource_totals
from simple_rapidchiplet.hybrid.hardware import gemini_hardware, build_package, validate_gemini_chiplet, validate_package
from simple_rapidchiplet.hybrid.rapid_backend import evaluate_package
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator, _transfer_service
from simple_rapidchiplet.hybrid.communication import Transfer
from simple_rapidchiplet.hybrid.mapping import initial_mapping, TensorRegion
from simple_rapidchiplet.hybrid.workload import make_toy_workload
from simple_rapidchiplet.hybrid.scheduler import Job, schedule_jobs
from simple_rapidchiplet.hybrid.diagnostics import _schedule_slack


class GeminiHardwareTests(unittest.TestCase):
    def test_independent_core_arrays_and_costs(self):
        spec=gemini_hardware(4)
        self.assertEqual((spec.core_rows,spec.core_cols,spec.cores_per_die),(2,2,4))
        self.assertEqual(spec.pes_per_core,16)
        self.assertEqual(spec.pe_count,64)
        self.assertEqual(spec.macs_per_cycle//4,1024)
        self.assertEqual(spec.per_core_mac_rate,1024e9)
        self.assertEqual(spec.unified_buffer_bytes,4*spec.core_global_buffer_bytes)
        self.assertEqual(spec.sram_costs['UB']['capacity_bytes'],2*1024**2)
        self.assertEqual(spec.sram_costs['WL2']['area_mm2'],0)
        self.assertEqual(spec.total_buffer_bytes_per_die,64*14*1024+8*1024**2)
        self.assertIn('vector_units',spec.compute_area_breakdown)
        self.assertNotIn('ddr_phy_controller',spec.compute_area_breakdown)
        self.assertGreater(spec.compute_area_breakdown['grs_phys'],0)
        self.assertGreater(spec.compute_area_breakdown['core_control'],0)

    def test_count_and_shape_templates_pay_IO_without_free_DRAM(self):
        one=gemini_hardware(1)
        horizontal=gemini_hardware(4,mesh_shape=(1,4))
        square=gemini_hardware(4,mesh_shape=(2,2))
        self.assertEqual(one.compute_area_mm2,horizontal.compute_area_mm2)
        self.assertEqual(resource_totals(one)['dram_bandwidth_Bps'],resource_totals(horizontal)['dram_bandwidth_Bps'])
        self.assertEqual(resource_totals(square)['dram_bandwidth_Bps'],2*resource_totals(horizontal)['dram_bandwidth_Bps'])
        p=build_package(square)
        self.assertEqual((len(p.compute_ids),len(p.io_ids),len(p.memory_ids)),(4,4,4))
        self.assertEqual(len(p.mapping_core_ids),16)
        self.assertTrue(all(e.lane_count==2 and e.bandwidth_Bps==32e9 for e in p.links if e.kind.startswith('gemini')))
        self.assertTrue(all('ddr_phy_controller' in p.nodes[x].area_components for x in p.io_ids))

    def test_templates_are_explicit_and_reject_hardware_mutation(self):
        candidates=enumerate_gemini_architectures(compute_counts=(1,2,4))
        self.assertEqual({x.id for x in candidates},{'gemini_c1_1x1','gemini_c2_1x2','gemini_c2_2x1','gemini_c4_1x4','gemini_c4_2x2','gemini_c4_4x1'})
        with self.assertRaises(ValueError): gemini_hardware(3)
        with self.assertRaises(ValueError): gemini_hardware(4,mesh_shape=(2,3))
        with self.assertRaisesRegex(ValueError,'fixed hardware'):
            validate_gemini_chiplet(replace(gemini_hardware(),lanes=16))
        p=build_package(gemini_hardware())
        bad=replace(p,links=(replace(p.links[0],lane_count=1),*p.links[1:]))
        with self.assertRaisesRegex(ValueError,'lane capacity'):
            validate_package(bad,gemini_hardware())

    def test_explicit_core_lanes_route_same_die_and_cross_die(self):
        spec=gemini_hardware(2,mesh_shape=(1,2))
        p=build_package(spec); context=evaluate_package(spec,p)
        self.assertEqual(context.route('compute:0/core:0','compute:0/core:3'),
                         ('compute:0/core:0','compute:0/core:1','compute:0/core:3'))
        top=('compute:0/core:1','compute:1/core:0')
        bottom=('compute:0/core:3','compute:1/core:2')
        self.assertEqual(context.link_bandwidth_Bps[top],16e9)
        self.assertEqual(context.link_bandwidth_Bps[bottom],16e9)
        self.assertEqual(context.link_bandwidth_Bps[('compute:0/core:0','compute:0/core:1')],32e9)
        self.assertNotEqual(top,bottom)
        transfer=Transfer('multicast','memory:0',('compute:0/core:0','compute:1/core:0'),
            1000,(),(),'dram_input','x',TensorRegion(((0,1),(0,1),(0,1),(0,1000))),0)
        _,resources,stats=_transfer_service(transfer,spec,context)
        dram=[x for x in stats['link_load_bytes'] if x['source']=='memory:0']
        self.assertEqual(sum(x['bytes'] for x in dram),1000)
        self.assertEqual(stats['local_delivered_bytes'],2000)
        self.assertIn('compute:0/core:0:dma',resources)
        self.assertTrue(math.isclose(stats['energy_j'],sum(stats[k] for k in ('nop_energy_j','dram_energy_j','noc_energy_j','sram_energy_j','crossbar_energy_j'))))


class GeminiOracleDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload=make_toy_workload(batch=2)
        cls.evaluator=HybridEvaluator(cls.workload,gemini_hardware(2),trace=True)
        cls.plan=initial_mapping(cls.workload,cls.evaluator.package.mapping_core_ids,cls.evaluator.package.memory_ids,max_group_layers=3)
        cls.result=cls.evaluator(cls.plan)

    def test_real_execution_conserves_energy_work_and_power(self):
        r=self.result
        self.assertTrue(r.metrics['feasible'])
        self.assertEqual(r.metrics['total_macs'],self.workload.total_macs)
        self.assertAlmostEqual(sum(r.metrics['energy_components'].values()),r.metrics['energy_j'])
        self.assertIn('vector_j',r.metrics['energy_components'])
        self.assertAlmostEqual(r.metrics['energy_j']/r.metrics['latency_s'],r.metrics['power_w'])
        self.assertEqual((r.metrics['compute_chiplets'],r.metrics['io_chiplets'],r.metrics['memory_dies']),(2,2,2))
        self.assertTrue(r.schedule.validate())

    def test_per_core_glb_overflow_is_infeasible(self):
        small=replace(gemini_hardware(2),core_global_buffer_bytes=128,unified_buffer_bytes=512)
        result=HybridEvaluator(self.workload,small,trace=False)(self.plan)
        self.assertFalse(result.metrics['feasible'])
        self.assertTrue(any('GLB needs' in x for x in result.metrics['violations']))

    def test_DMA_and_PE_stages_share_physical_GLB_service(self):
        result=self.result
        transfers=result.communication.transfer_map
        touched_by_core={core:[] for core in self.evaluator.package.mapping_core_ids}
        for event in result.schedule.events:
            if event.job.kind in ('core_read','core_write'):
                core=event.job.metadata['core']
                touched_by_core[core].append(event)
                self.assertIn(f'{core}:glb_port',event.job.resources)
            elif event.job.id in transfers:
                transfer=transfers[event.job.id]
                for core in set((transfer.src,*transfer.dsts)) & touched_by_core.keys():
                    touched_by_core[core].append(event)
                    self.assertIn(f'{core}:glb_port',event.job.resources)
        checked=0
        for spans in touched_by_core.values():
            spans.sort(key=lambda event:(event.start_s,event.finish_s))
            checked+=len(spans)
            for a,b in zip(spans,spans[1:]):
                self.assertLessEqual(a.finish_s,b.start_s+1e-15,
                    f'physical GLB port overlap: {a.job.id} and {b.job.id}')
        self.assertGreater(checked,len(result.compiled.units)*2)

    def test_diagnostics_use_actual_windows_and_unknown_split_waits(self):
        r=self.result; d=r.diagnostics
        self.assertEqual(len(d['layers']),len(self.workload.layers))
        self.assertEqual(len(d['flows']),len(r.communication.transfers))
        self.assertEqual(len(d['memory']),len(self.evaluator.package.mapping_core_ids))
        for row in d['layers']:
            self.assertIsNone(row['dram_wait_s'])
            self.assertIsNone(row['noc_wait_s'])
            self.assertIsNone(row['d2d_wait_s'])
            self.assertGreaterEqual(row['resource_wait_s'],0)
        for row in d['network']:
            self.assertEqual(sum(w['transmitted_bytes'] for w in row['time_windows']),row['transmitted_bytes'])
            self.assertLessEqual(row['reservation_fraction'],1+1e-12)
            for window in row['time_windows']:
                e=r.schedule.event_map[window['flow_id']]
                self.assertEqual((window['start_s'],window['finish_s']),(e.start_s,e.finish_s))

    def test_slack_includes_serialized_resource_order(self):
        schedule=schedule_jobs((Job('a',(),('core',),2,priority=(0,)),
            Job('b',(),('core',),3,priority=(1,)),Job('c',(),('other',),1,priority=(2,))))
        slack=_schedule_slack(schedule)
        self.assertEqual(slack['a'],0)
        self.assertEqual(slack['b'],0)
        self.assertEqual(slack['c'],4)


if __name__=='__main__': unittest.main()
