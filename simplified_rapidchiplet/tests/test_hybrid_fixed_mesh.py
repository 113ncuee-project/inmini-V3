"""Physical and production-interface regressions for homogeneous mesh chiplets."""
from collections import Counter
from dataclasses import asdict, replace
import csv
import json
from pathlib import Path
import tempfile
import unittest

import hybrid_dse
import hybrid_gui
from simple_rapidchiplet.hybrid.architecture import enumerate_architectures, resource_totals
from simple_rapidchiplet.hybrid.communication import Transfer
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator, _transfer_service
from simple_rapidchiplet.hybrid.hardware import (
    HardwareSpec, fixed_mesh_hardware, validate_fixed_chiplet, build_package, validate_package,
)
from simple_rapidchiplet.hybrid.mapping import TensorRegion
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.rapid_backend import build_native_inputs, evaluate_package
from simple_rapidchiplet.hybrid.report import save_evaluation
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class FixedMeshTests(unittest.TestCase):
    def test_more_chiplets_scale_resources_without_changing_each_die(self):
        baseline = fixed_mesh_hardware(1)
        fixed = asdict(baseline)
        for count in (1,2,4,8,16):
            spec = fixed_mesh_hardware(count)
            observed = asdict(spec)
            for name in fixed.keys()-{'cluster_rows','cluster_cols'}:
                self.assertEqual(observed[name],fixed[name],name)
            totals = resource_totals(spec)
            self.assertEqual(totals['pes'],16*count)
            self.assertEqual(totals['unified_bytes'],8*1024**2*count)
            self.assertEqual(totals['dram_bandwidth_Bps'],37.5e9/8*count)
            self.assertEqual(totals['io_dies'],0)
            self.assertAlmostEqual(spec.macs_per_second,4096*500e6)
            self.assertAlmostEqual(spec.peak_tops,4.096*count)
            package = build_package(spec)
            self.assertEqual(len(package.nodes),2*count)
            self.assertTrue(all(package.nodes[n].area_components==baseline.compute_area_breakdown for n in package.compute_ids))
            self.assertTrue(all(package.nodes[n].ports==5 for n in package.compute_ids))
            self.assertEqual(sum(e.kind=='compute_mesh' for e in package.links),spec.cluster_rows*(spec.cluster_cols-1)+spec.cluster_cols*(spec.cluster_rows-1))

    def test_mesh_xy_compute_relay_and_boundary_ports_are_physical(self):
        spec = fixed_mesh_hardware(16)
        package = build_package(spec)
        native,_ = build_native_inputs(spec,package)
        context = evaluate_package(spec,package)
        self.assertEqual(context.route('memory:0','compute:15/core:3'),
                         ('memory:0','compute:0','compute:1','compute:2','compute:3','compute:7','compute:11','compute:15'))
        self.assertEqual(context.route('memory:15','memory:0'),
                         ('memory:15','compute:15','compute:14','compute:13','compute:12','compute:8','compute:4','compute:0','memory:0'))
        self.assertTrue(native['packaging']['has_interposer'])
        self.assertEqual(native['chiplets']['compute:0'],native['chiplets']['compute:5'])
        self.assertTrue(native['chiplets']['compute:0']['relay'])
        self.assertFalse(native['chiplets']['memory:0']['relay'])
        self.assertEqual(context.area_breakdown['io_silicon_mm2'],0)
        for route in context.routes.values():
            self.assertEqual(len(route),len(set(route)))
            self.assertTrue(all(n.startswith('compute:') for n in route[1:-1]))
            for edge in zip(route,route[1:]):
                self.assertIn(edge,context.link_bandwidth_Bps)
        for edge in package.links:
            self.assertAlmostEqual(context.link_bandwidth_Bps[(edge.a,edge.b)],edge.bandwidth_Bps)

    def test_relay_pays_network_service_but_does_not_allocate_tensor_sram(self):
        spec = fixed_mesh_hardware(16)
        context = evaluate_package(spec)
        transfer = Transfer('test','compute:0/core:0',('compute:15/core:0',),
                            1000,(),(),'activation','x',TensorRegion(((0,1),(0,1000),(0,1),(0,1))),0)
        _,resources,stats = _transfer_service(transfer,spec,context)
        self.assertIn('compute:1:crossbar',resources)
        self.assertNotIn('compute:1:dma',resources)
        self.assertEqual(stats['nop_hop_bytes'],6000)
        self.assertEqual(stats['sram_access_ledger']['UB']['read_bits'],8000)
        self.assertEqual(stats['sram_access_ledger']['UB']['write_bits'],8000)
        self.assertGreater(stats['crossbar_energy_j'],0)

    def test_multicast_common_mesh_prefix_counted_once(self):
        spec = fixed_mesh_hardware(4)
        context = evaluate_package(spec)
        transfer = Transfer('test','memory:0',('compute:1/core:0','compute:3/core:0'),
                            1000,(),(),'dram_input','x',TensorRegion(((0,1),(0,1000),(0,1),(0,1))),0)
        _,resources,stats = _transfer_service(transfer,spec,context)
        self.assertEqual(stats['nop_hop_bytes'],3000)
        self.assertEqual(stats['dram_bytes'],1000)
        self.assertEqual(stats['local_delivered_bytes'],2000)
        self.assertEqual(len(resources),len(set(resources)))
        self.assertEqual([(e['source'],e['destination']) for e in stats['link_load_bytes']],
                         [('compute:0','compute:1'),('compute:1','compute:3'),('memory:0','compute:0')])

    def test_invalid_mesh_cannot_hide_bad_links_or_missing_neighbors(self):
        spec = fixed_mesh_hardware(4)
        package = build_package(spec)
        links = list(package.links)
        mesh_index = next(i for i,e in enumerate(links) if e.kind=='compute_mesh')
        links[mesh_index] = replace(links[mesh_index],a_port=0)
        with self.assertRaisesRegex(ValueError,'compass'):
            validate_package(replace(package,links=tuple(links)),spec)
        links = tuple(e for e in package.links if not (e.a=='compute:0' and e.b=='compute:1'))
        with self.assertRaisesRegex(ValueError,'every neighboring'):
            validate_package(replace(package,links=links),spec)

    def test_fixed_profile_rejects_overrides_and_preserves_history(self):
        reference = fixed_mesh_hardware()
        for changed in (replace(reference,pe_count=32),replace(reference,unified_buffer_bytes=2*1024**2),
                        replace(reference,prefetch_slots=1),replace(reference,dram_bandwidth_Bps=10e9)):
            with self.assertRaisesRegex(ValueError,'fixed hardware'):
                validate_fixed_chiplet(changed)
        with self.assertRaises(ValueError):
            enumerate_architectures(noc_topologies=('multi_ring',))
        with self.assertRaises(ValueError):
            fixed_mesh_hardware(6)
        old = asdict(HardwareSpec())
        del old['package_topology']
        self.assertEqual(HardwareSpec.from_dict(old).package_topology,'indm_cluster')
        self.assertEqual(HardwareSpec.from_dict(asdict(reference)),reference)
        defaults = hybrid_dse.parser().parse_args([])
        self.assertEqual((defaults.mode,defaults.noc,defaults.prefetch_slots),('architecture','mesh',2))
        config = hybrid_gui.validate_config({'models':['toy']})
        self.assertEqual(config['dies'],[1,2,4,8,16])
        self.assertEqual(config['prefetch_slots'],1)
        self.assertEqual(config['planner'],'tangram')
        for data in ({'dies':[4]},{'noc':['multi_ring']},{'ub_mib':2},{'prefetch_slots':2}):
            with self.assertRaises(ValueError):
                hybrid_gui.validate_config(data)

    def test_exports_preserve_routes_timing_and_byte_accounting(self):
        workload = make_toy_workload(batch=1)
        spec = fixed_mesh_hardware(4)
        evaluator = HybridEvaluator(workload,spec)
        plan = balanced_mapping(workload,evaluator.package.mapping_core_ids,evaluator.package.memory_ids,hardware=spec)
        result = evaluator.evaluate(plan,retain_trace=True)
        self.assertTrue(result.metrics['feasible'])
        self.assertEqual(result.metrics['executed_macs'],workload.total_macs)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            save_evaluation(folder,result,evaluator,plan)
            deployment = json.loads((folder/'deployment.json').read_text())
            self.assertEqual((deployment['compute_chiplets'],deployment['io_chiplets'],deployment['total_dies']),(4,0,8))
            routes = json.loads((folder/'traffic_routes.json').read_text())['transfers']
            self.assertEqual(len(routes),len(result.communication.transfers))
            expected = Counter()
            for transfer in routes:
                self.assertLessEqual(transfer['start_s'],transfer['finish_s'])
                for route in transfer['routes']:
                    self.assertEqual(tuple(route['path']),evaluator.context.route(transfer['src'],route['destination']))
                for link in transfer['statistics']['link_load_bytes']:
                    expected[(link['source'],link['destination'])] += link['bytes']
            actual = Counter()
            with (folder/'link_traffic.csv').open() as stream:
                for row in csv.DictReader(stream):
                    actual[(row['source'],row['destination'])] += int(row['bytes'])
            self.assertEqual(actual,expected)
            layout = json.loads((folder/'layout.json').read_text())
            self.assertEqual(sum(row['bytes'] for row in layout['link_traffic']),sum(expected.values()))


if __name__ == '__main__':
    unittest.main()
