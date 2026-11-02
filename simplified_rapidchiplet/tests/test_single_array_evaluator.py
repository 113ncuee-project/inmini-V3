"""v0.2 production compiler/oracle: exact work, finite ports and paid DF."""
from dataclasses import replace
import math
import time
import unittest

from simple_rapidchiplet.hybrid.communication import Transfer
from simple_rapidchiplet.hybrid.mapping import FusionStack, LayerGroup, Partition, TensorRegion, initial_mapping
from simple_rapidchiplet.hybrid.single_array_compiler import compile_single_array, tile_requirements
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator
from simple_rapidchiplet.hybrid.single_array_hardware import ExperimentalAssumptions, SingleArrayHardware
from simple_rapidchiplet.hybrid.workload import LayerSpec, TensorSpec, make_toy_workload


class SingleArrayOracleTests(unittest.TestCase):
    def setUp(self):
        self.workload = make_toy_workload(batch=1, channels=5, spatial=7)
        self.hardware = SingleArrayHardware(1, 1)
        self.plan = initial_mapping(self.workload, self.hardware.compute_slots,
                                    ('memory:0', 'memory:1'), max_group_layers=3)

    def test_full_cost_conservation_and_explicit_requant(self):
        oracle = SingleArrayEvaluator(self.workload, self.hardware)
        r = oracle(self.plan)
        self.assertTrue(r.metrics['feasible'], r.metrics['violations'])
        self.assertEqual(r.metrics['executed_macs'], 12250)
        self.assertEqual(r.metrics['executed_macs'], self.workload.total_macs)
        self.assertAlmostEqual(r.metrics['energy_components']['mac_j'], 12250 * .024e-12)
        self.assertAlmostEqual(sum(r.metrics['energy_components'].values()), r.metrics['energy_j'])
        self.assertAlmostEqual(r.metrics['energy_j'] / r.metrics['latency_s'], r.metrics['power_w'])
        self.assertEqual(r.metrics['physical_cores'], 0)
        self.assertEqual(r.metrics['pes'], 16)
        self.assertEqual(r.metrics['area_mm2'], self.hardware.area_estimate['total_silicon_mm2'])
        requant = [e for e in r.schedule.events if e.job.kind == 'vector_execute' and e.job.metadata['requantized']]
        self.assertEqual(len(requant), sum(bool(u.macs) for u in r.compiled.units))
        self.assertTrue(any(t.kind == 'quantization_parameters' for t in r.communication.transfers))
        self.assertTrue(r.schedule.validate())
        self.assertIs(oracle(self.plan), r)
        self.assertEqual((oracle.evaluations, oracle.cache_hits), (1, 1))

    def test_all_L2_users_share_one_aggregate_RW_port(self):
        r = SingleArrayEvaluator(self.workload, self.hardware)(self.plan)
        count = 0
        for event in r.schedule.events:
            if event.job.kind in ('pe_read', 'psum_write', 'vector_execute'):
                self.assertIn('compute:0:l2_rw', event.job.resources)
                count += 1
            self.assertFalse(any('/core:' in resource or ':ub_' in resource for resource in event.job.resources))
        self.assertGreater(count, 0)
        spans = sorted((e.start_s, e.finish_s) for e in r.schedule.events if 'compute:0:l2_rw' in e.job.resources)
        self.assertTrue(all(a[1] <= b[0] + 1e-15 for a, b in zip(spans, spans[1:])))

    def test_VPU_is_one_per_die_and_non_MAC_ops_do_not_use_PE_compute(self):
        r = SingleArrayEvaluator(self.workload, self.hardware)(self.plan)
        add_units = {u.id for u in r.compiled.units if u.layer_id == 'add'}
        for event in r.schedule.events:
            if (event.job.metadata or {}).get('unit_id') in add_units:
                self.assertFalse(any(resource.endswith(':mac') for resource in event.job.resources))
        vpus = {resource for event in r.schedule.events for resource in event.job.resources if resource.endswith(':vpu')}
        self.assertEqual(vpus, {'compute:0:vpu'})
        for unit in r.compiled.units:
            if unit.layer_id == 'add':
                self.assertEqual(r.buffer_statistics['peak_by_pool'][unit.chiplet + ':AL1'], 0)

    def test_transit_router_never_accesses_relay_L2(self):
        hardware = SingleArrayHardware(1, 4)
        oracle = SingleArrayEvaluator(self.workload, hardware)
        flow = Transfer('probe', 'memory:0', ('compute:3/pe:0',), 8192, (), (), 'dram_input',
                        'image', TensorRegion(((0, 1), (0, 1), (0, 1), (0, 8192))), 0)
        duration, resources, loads, energy = oracle.transfer_service(flow)
        self.assertIn('io:0:controller', resources)
        self.assertIn('compute:3:dma', resources)
        for die in range(3):
            self.assertIn(f'compute:{die}:nop_switch', resources)
            self.assertNotIn(f'compute:{die}:l2_rw', resources)
            self.assertNotIn(f'compute:{die}:dma', resources)
        self.assertGreaterEqual(duration, 8192 / hardware.dram_bandwidth_Bps)
        self.assertEqual(sum(amount for _, _, amount, kind in loads if kind == 'dram'), 8192)
        self.assertGreater(energy['nop_j'], 0)

    def test_INT24_alignment_changes_real_traffic_and_energy(self):
        packed = SingleArrayEvaluator(self.workload, self.hardware)(self.plan)
        aligned_hardware = replace(self.hardware, assumptions=replace(self.hardware.assumptions, psum_storage_bytes=4))
        aligned = SingleArrayEvaluator(self.workload, aligned_hardware)(self.plan)
        self.assertEqual(packed.metrics['executed_macs'], aligned.metrics['executed_macs'])
        self.assertGreater(aligned.metrics['noc_hop_bytes'], packed.metrics['noc_hop_bytes'])
        self.assertGreater(aligned.metrics['energy_j'], packed.metrics['energy_j'])
        self.assertNotEqual(packed.metrics['evaluator_identity'], aligned.metrics['evaluator_identity'])

    def test_full_channel_tiles_fit_each_pool_including_interior_halo(self):
        w = make_toy_workload(batch=1, channels=64, spatial=13)
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=3)
        compiled = compile_single_array(w, p, self.hardware)
        self.assertEqual(sum(u.macs for u in compiled.units), w.total_macs)
        self.assertGreater(len(compiled.units), len(w.layers) * 5)
        for unit in compiled.units:
            req = tile_requirements(w, w.layer_map[unit.layer_id], unit.output_region)
            self.assertLessEqual(req['weight_bytes'], 64 * 1024)
            self.assertLessEqual(req['activation_bytes'], 16 * 1024)
            if unit.macs:
                self.assertLessEqual(req['psum_bytes'], 8 * 1024)

    def test_non_DF_local_forward_does_not_invent_DRAM_roundtrip(self):
        w = make_toy_workload(residual=False, batch=1, channels=3, spatial=5)
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=2)
        off = SingleArrayEvaluator(w, self.hardware)(p)
        on = SingleArrayEvaluator(w, self.hardware)(replace(p, fusion_stacks=(FusionStack(('conv0', 'conv1'), (3, 3), 'recompute'),)))
        self.assertFalse(any(t.kind.startswith('inter_group_') for t in off.communication.transfers))
        self.assertTrue(any(t.kind == 'activation' for t in off.communication.transfers))
        self.assertEqual(off.metrics['executed_macs'], w.total_macs)
        # Independent sink K shards may recompute upstream channels even for
        # 1x1 conv; all such extra work must be explicitly reported and paid.
        self.assertGreaterEqual(on.metrics['executed_macs'], w.total_macs)
        self.assertEqual(on.metrics['executed_macs'] - w.total_macs, on.metrics['recompute_macs'])
        self.assertGreater(off.metrics['noc_hop_bytes'], 0)
        self.assertGreater(on.metrics['noc_hop_bytes'], 0)

    def test_DF_halo_recompute_is_charged_and_full_cache_is_capacity_checked(self):
        w = make_toy_workload(residual=False, batch=1, channels=3, spatial=7)
        layer = replace(w.layers[1], kernel=(3, 3), padding=(1, 1), weight_shape=(3, 3, 3, 3),
                        macs_per_sample=7 * 7 * 3 * 3 * 9)
        w = replace(w, layers=(w.layers[0], layer))
        w.validate()
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=2)
        recomp = SingleArrayEvaluator(w, self.hardware)(replace(p, fusion_stacks=(FusionStack(('conv0', 'conv1'), (2, 2), 'recompute'),)))
        cached = SingleArrayEvaluator(w, self.hardware)(replace(p, fusion_stacks=(FusionStack(('conv0', 'conv1'), (2, 2), 'full_cache'),)))
        self.assertGreater(recomp.metrics['recompute_macs'], 0)
        self.assertGreater(recomp.metrics['executed_macs'], cached.metrics['executed_macs'])
        self.assertAlmostEqual(recomp.metrics['energy_components']['mac_j'], recomp.metrics['executed_macs'] * .024e-12)
        self.assertTrue(all('UB' not in name for name in cached.buffer_statistics['peak_by_pool']))

    def test_real_diagnostics_and_deadline_cannot_archive_partial_PPA(self):
        r = SingleArrayEvaluator(self.workload, self.hardware)(self.plan)
        self.assertEqual(r.diagnostics['evidence_quality'], 'partial')
        self.assertGreater(len(r.diagnostics['critical_path']), 0)
        self.assertTrue(all(row['queue_wait_s'] >= 0 and row['utilization'] <= 1 + 1e-10 for row in r.diagnostics['network']))
        for row in r.diagnostics['memory']:
            self.assertEqual(row['peak_live_bytes'], r.buffer_statistics['peak_by_pool'][row['pool_id']])
        oracle = SingleArrayEvaluator(self.workload, self.hardware, deadline=time.monotonic() - 1)
        with self.assertRaises(TimeoutError):
            oracle(self.plan)
        self.assertEqual(oracle.evaluations, 0)
        self.assertEqual(oracle.cache, {})

    def test_DRAM_materialization_releases_source_OL2_before_later_DRAM_read(self):
        w = make_toy_workload(residual=False, batch=1, channels=1, spatial=3)
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=1)
        p = replace(p, layer_mappings=tuple(replace(item, chiplets=('compute:0/pe:0',), partition=Partition())
                                            for item in p.layer_mappings))
        r = SingleArrayEvaluator(w, self.hardware)(p)
        # A complete 9-element INT24 tile and its INT8 output coexist during
        # requant: 27+9=36 B. A materialized old tensor cannot remain charged
        # while the next group reads a different copy from DRAM (45 B bug).
        self.assertEqual(r.buffer_statistics['peak_by_pool']['compute:0:OL2'], 36)

    def test_depthwise_channels_pack_output_lanes_with_paid_tail_and_traffic(self):
        w = make_toy_workload(residual=False, batch=1, channels=32, spatial=3)
        first = replace(w.layers[0], groups=32, weight_shape=(32, 1, 3, 3), macs_per_sample=32 * 3 * 3 * 9)
        w = replace(w, layers=(first, w.layers[1]))
        w.validate()
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=1)
        p = replace(p, layer_mappings=tuple(replace(item, chiplets=('compute:0/pe:0',), partition=Partition())
                                            for item in p.layer_mappings))
        oracle = SingleArrayEvaluator(w, self.hardware)
        unit = next(u for u in compile_single_array(w, p, self.hardware).units if u.layer_id == 'conv0')
        kernel = oracle._kernel(unit, first)
        self.assertEqual(kernel['mac_cycles'], 3 * 3 * 2 * 9)
        self.assertEqual(kernel['activation_read_bytes'], unit.macs)
        self.assertEqual(kernel['lane_utilization'], 1 / 16)

    def test_same_PE_residual_retains_OL2_even_without_an_explicit_transfer(self):
        w = make_toy_workload(residual=False, batch=1, channels=1, spatial=3)
        shape = (1, 1, 3, 3)
        relu = LayerSpec('relu', 'ReLU', ('conv1',), 'relu', vector_ops_per_element=1)
        add = LayerSpec('add', 'Add', ('conv0', 'relu'), 'add', vector_ops_per_element=1)
        w = replace(w, layers=(*w.layers, relu, add), tensors=(*w.tensors,
                    TensorSpec('relu', shape, producer='relu'), TensorSpec('add', shape, producer='add')), output_ids=('add',))
        w.validate()
        p = initial_mapping(w, self.hardware.compute_slots, self.plan.memory_ids, max_group_layers=4, pipeline=False)
        p = replace(p, layer_mappings=tuple(replace(item, chiplets=('compute:0/pe:0',), partition=Partition()) for item in p.layer_mappings))
        r = SingleArrayEvaluator(w, self.hardware)(p)
        # Original residual 9B + next tile's INT24 psums 27B + INT8 output 9B.
        # A missing same-PE transfer cannot make the original residual free.
        self.assertEqual(r.buffer_statistics['peak_by_pool']['compute:0:OL2'], 45)


if __name__ == '__main__':
    unittest.main()
