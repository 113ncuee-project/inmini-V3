"""Versioned seed DP and multicast lifetime regression for the shared L2."""
from dataclasses import replace
import unittest

from simple_rapidchiplet.hybrid.communication import build_communication
from simple_rapidchiplet.hybrid.mapping import Partition, initial_mapping
from simple_rapidchiplet.hybrid.single_array_communication import split_read_cohorts
from simple_rapidchiplet.hybrid.single_array_compiler import compile_single_array
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator
from simple_rapidchiplet.hybrid.single_array_hardware import SingleArrayHardware
from simple_rapidchiplet.hybrid.single_array_seed import generate_single_array_seeds
from simple_rapidchiplet.hybrid.workload import LayerSpec, TensorSpec, make_toy_workload


class SeedAndCohortTests(unittest.TestCase):
    def test_seed_adapter_preserves_original_and_DP_only_proposes(self):
        w, h = make_toy_workload(batch=1, channels=5, spatial=7), SingleArrayHardware(1, 1)
        seeds = generate_single_array_seeds(w, h, max_candidates=4)
        original = initial_mapping(w, h.compute_slots, ('memory:0', 'memory:1'), max_group_layers=1)
        self.assertEqual(seeds[0].plan, original)
        self.assertGreater(len(seeds), 1)
        self.assertTrue(any(s.provenance['source'] == 'bounded_segmentation_DP_beam' for s in seeds))
        for seed in seeds:
            self.assertFalse(seed.provenance['original_tangram_executed'])
            self.assertEqual(seed.provenance['physical_validity'], 'global oracle pending')
            self.assertFalse(seed.proxy['formal_PPA'])
            result = SingleArrayEvaluator(w, h)(seed.plan)
            self.assertEqual(result.metrics['executed_macs'], w.total_macs)
            self.assertTrue(result.metrics['feasible'])

    def test_future_recipient_bank_does_not_create_atomic_multicast_cycle(self):
        w, h = make_toy_workload(batch=1, channels=5, spatial=7), SingleArrayHardware(1, 1)
        shape = w.tensor_map['conv1'].shape
        relu = LayerSpec('relu', 'ReLU', ('conv1',), 'relu', vector_ops_per_element=1)
        add = replace(w.layers[-1], inputs=('image', 'relu'))
        w = replace(w, layers=(*w.layers[:2], relu, add),
                    tensors=(*w.tensors, TensorSpec('relu', shape, producer='relu')))
        w.validate()
        plan = initial_mapping(w, h.compute_slots, ('memory:0', 'memory:1'), max_group_layers=1)
        plan = replace(plan, layer_mappings=tuple(replace(item,
            chiplets=('compute:0/pe:0' if item.layer_id == 'conv0' else 'compute:0/pe:1',), partition=Partition())
            for item in plan.layer_mappings))
        compiled = compile_single_array(w, plan, h)
        raw = build_communication(w, compiled)
        self.assertTrue(any(len({compiled.unit_map[name].group_id for name in t.consumer_units}) > 1 for t in raw.transfers))
        grouped = split_read_cohorts(compiled, raw)
        self.assertGreaterEqual(grouped.dram_read_bytes, raw.dram_read_bytes)
        identifiers = {transfer.id for transfer in grouped.transfers}
        for unit, dependencies in grouped.unit_dependencies:
            self.assertTrue(all(dep in identifiers or dep in compiled.unit_map for dep in dependencies))
        result = SingleArrayEvaluator(w, h)(plan)
        self.assertTrue(result.schedule.validate())
        self.assertTrue(result.metrics['feasible'])
        self.assertEqual(result.metrics['executed_macs'], w.total_macs)
        for transfer in result.communication.transfers:
            if transfer.kind != 'dram_weight':
                self.assertLessEqual(len({compiled.unit_map[name].group_id for name in transfer.consumer_units}), 1)


if __name__ == '__main__':
    unittest.main()
