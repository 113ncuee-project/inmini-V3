"""Tangram-style seed keeps the scheduling DAG and pays for all oracle queries."""
from dataclasses import replace
import json
import math
import unittest

from simple_rapidchiplet.hybrid.hardware import HardwareSpec, build_package
from simple_rapidchiplet.hybrid.mapping import compile_mapping, validate_plan
from simple_rapidchiplet.hybrid.tangram_seed import (
    build_tangram_seed, dag_snapshot, generate_tangram_seeds,
)
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class TangramSeedTests(unittest.TestCase):
    def setUp(self):
        self.workload = make_toy_workload(batch=4, channels=5, spatial=7)
        self.hardware = HardwareSpec(cluster_rows=1, cluster_cols=1, compute_per_cluster=1)
        self.package = build_package(self.hardware)
        self.args = (self.workload, self.package.mapping_core_ids, self.package.memory_ids, self.hardware)

    def test_seed_keeps_two_add_inputs_and_exact_tail_coverage(self):
        fingerprint = self.workload.fingerprint
        for candidate in generate_tangram_seeds(*self.args, max_candidates=4):
            self.assertTrue(validate_plan(self.workload, candidate.plan, self.package.mapping_core_ids))
            compiled = compile_mapping(self.workload, candidate.plan)
            self.assertEqual(sum(unit.macs for unit in compiled.units), self.workload.total_macs)
            for microbatch in range(compiled.microbatch_count):
                for layer in self.workload.layers:
                    units = [unit for unit in compiled.units if unit.layer_id == layer.id and unit.microbatch == microbatch]
                    elements = math.prod(self.workload.tensor_map[layer.output].shape[1:]) * candidate.plan.microbatch_size
                    self.assertEqual(sum(unit.output_region.elements for unit in units), elements)
                    for index, unit in enumerate(units):
                        for other in units[index + 1:]:
                            self.assertIsNone(unit.output_region.intersection(other.output_region))
            for unit in compiled.units:
                if unit.layer_id == "add":
                    self.assertEqual({req.tensor_id for req in unit.inputs}, {"image", "conv1"})
                    self.assertTrue(unit.dependencies)
                    self.assertTrue(all(compiled.unit_map[name].layer_id == "conv1" for name in unit.dependencies))
        self.assertEqual(self.workload.fingerprint, fingerprint)

    def test_snapshot_preserves_residual_shape_and_dag_hash(self):
        snapshot = dag_snapshot(self.workload)
        add = next(node for node in snapshot["nodes"] if node["id"] == "add")
        self.assertEqual(add["inputs"], ["image", "conv1"])
        self.assertEqual(add["output_shape"], [4, 5, 7, 7])
        edges = [edge for edge in snapshot["edges"] if edge["consumer"] == "add"]
        self.assertEqual([edge["producer"] for edge in edges], [None, "conv1"])
        self.assertEqual([edge["input_index"] for edge in edges], [0, 1])
        self.assertEqual(snapshot["model_hash"], self.workload.fingerprint)
        json.dumps(snapshot, allow_nan=False)

    def test_full_oracle_overrides_proxy_and_counts_all_failures(self):
        calls = []
        def evaluate(plan):
            calls.append(plan)
            if len(calls) == 1:
                raise ValueError("exact memory capacity failure")
            if len(calls) == 2:
                return {"feasible": False, "latency_s": 0.01, "energy_j": 0.01}
            return {"feasible": True, "latency_s": 10 / len(calls), "energy_j": 2.0}
        result = build_tangram_seed(*self.args, evaluator=evaluate, max_candidates=5)
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(result.evaluator_queries, len(calls))
        self.assertEqual(result.selected_index, len(calls) - 1)
        self.assertEqual(result.plan, calls[-1])
        self.assertIn("memory capacity", result.evaluation_records[0]["rejection_reason"])
        self.assertFalse(result.evaluation_records[1]["valid"])
        self.assertGreaterEqual(result.evaluation_elapsed_s, sum(row["elapsed_s"] for row in result.evaluation_records))

    def test_budget_and_all_invalid_never_invent_evaluated_ppa(self):
        calls = []
        def evaluate(plan):
            calls.append(plan)
            return {"feasible": False, "latency_s": 1, "energy_j": 1}
        result = build_tangram_seed(*self.args, evaluator=evaluate, max_evaluations=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.evaluator_queries, 2)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.metrics)
        self.assertEqual(result.status, "no_evaluated_executable_seed")
        empty = build_tangram_seed(*self.args, evaluator=evaluate, max_evaluations=0)
        self.assertEqual(empty.evaluator_queries, 0)
        self.assertIsNone(empty.plan)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_custom_fixed_ppa_score_is_used_and_limits_can_be_violated_at_seed(self):
        calls = []
        def evaluate(plan):
            calls.append(plan)
            return {"feasible": True, "latency_s": 1.0, "energy_j": float(len(calls)),
                    "area_mm2": 100.0, "power_w": float(100 - len(calls))}
        result = build_tangram_seed(*self.args, evaluator=evaluate, max_candidates=4,
                                    score_fn=lambda metrics: metrics["power_w"] + max(0, metrics["area_mm2"] / 10 - 1))
        self.assertEqual(result.plan, calls[-1])
        self.assertEqual(result.provenance["ranking_objective"], "caller score_fn")

    def test_proposal_only_is_explicit_and_deterministic(self):
        first = build_tangram_seed(*self.args, microbatch_sizes=(1, 2, 3, 4))
        second = build_tangram_seed(*self.args, microbatch_sizes=(1, 2, 3, 4))
        self.assertEqual(first.status, "proposal_only")
        self.assertIsNone(first.metrics)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.candidates, second.candidates)
        self.assertEqual(first.evaluator_queries, 0)
        self.assertFalse(first.provenance["original_tangram_executed"])
        self.assertFalse(first.provenance["original_gemini_executed"])
        self.assertFalse(first.provenance["globally_exact"])
        self.assertTrue(any("BSD" in note for note in first.provenance["approximation_limits"]))
        json.dumps(first.to_dict(), allow_nan=False)

    def test_invalid_dag_and_invalid_bounds_are_rejected(self):
        wrong = replace(self.workload.tensors[-1], shape=(4, 4, 7, 7))
        workload = replace(self.workload, tensors=(*self.workload.tensors[:-1], wrong))
        with self.assertRaisesRegex(ValueError, "Add"):
            build_tangram_seed(workload, *self.args[1:])
        for value in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                build_tangram_seed(*self.args, max_evaluations=value)


if __name__ == "__main__":
    unittest.main()
