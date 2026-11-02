"""Small exact oracles for transactions, physical reward and learned search."""
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

import numpy as np

from simple_rapidchiplet.hybrid.architecture import enumerate_architectures, enumerate_gemini_architectures
from simple_rapidchiplet.hybrid.mapping import compile_mapping, initial_mapping, Partition
from simple_rapidchiplet.hybrid.rl_actions import (apply_transaction, diagnose, generate_candidates,
                                                 resized_mapping, validate_plan)
from simple_rapidchiplet.hybrid.rl_schema import (ActionEdit, ActionPlan, ATOMIC_ACTIONS,
                                                DesignState, make_action_plan)
from simple_rapidchiplet.hybrid.rl_search import (ExactEvaluationCache, JointDesignEnvironment,
                                                JointObjective, JointSearchConfig,
                                                compute_reward, run_joint_search)
from simple_rapidchiplet.hybrid.search import LinearActorCritic
from simple_rapidchiplet.hybrid.workload import make_toy_workload, LayerSpec, TensorSpec, Workload


class JointRLTests(unittest.TestCase):
    def setUp(self):
        self.workload = make_toy_workload(residual=False, batch=4)
        self.candidates = enumerate_architectures(compute_counts=(1, 2, 4))
        self.candidate = self.candidates[1]
        self.plan = initial_mapping(self.workload, self.candidate.package.mapping_core_ids,
                                    self.candidate.package.memory_ids, microbatch_size=2, max_group_layers=2)
        self.state = DesignState(self.candidate.id, self.plan, self.workload.fingerprint,
                                 workload_definition={"batch_size": 4})

    @staticmethod
    def factory(candidate):
        def oracle(plan):
            # Exact, hand-checkable parallel stages, with a priced K traffic
            # term. This test oracle is never the production cost model.
            busy = {"conv0": 12 / len(plan.mapping_map["conv0"].chiplets),
                    "conv1": 2 / len(plan.mapping_map["conv1"].chiplets)}
            latency = max(busy.values()) if len(plan.groups) == 1 else sum(busy.values())
            energy = 1 + sum(item.partition.k for item in plan.layer_mappings) * .01
            return {"latency_s": latency, "energy_j": energy,
                    "area_mm2": candidate.hardware.compute_count * 10., "power_w": energy / latency,
                    "feasible": True,
                    "diagnostics": {"layers": [{"layer_id": "conv0", "bottleneck": "compute", "criticality": 1., "slack_s": 0.},
                                               {"layer_id": "conv1", "bottleneck": "unknown", "criticality": 0., "slack_s": latency - busy["conv1"]}]}}
        return oracle

    def test_a11_normalizes_to_only_one_policy_transition(self):
        parameters = {"architecture_candidate_id": self.candidates[0].id,
                      "mapping": resized_mapping(self.workload, self.state, self.candidates[0]).to_dict()}
        old = make_action_plan(self.state, "A11", [("A11", parameters)])
        new = make_action_plan(self.state, "A9", [("A9", parameters)])
        self.assertEqual(old.family_id, "A9")
        self.assertEqual(old.ordered_edits[0].action_id, "A9")
        self.assertEqual(old.id, new.id)
        self.assertEqual(len(ATOMIC_ACTIONS), 10)
        self.assertEqual(ActionPlan.from_dict(old.to_dict()), old)

    def test_failed_macro_rolls_back_every_decision_and_stale_plan_is_rejected(self):
        part = self.plan.mapping_map["conv0"].partition.as_tuple()
        action = make_action_plan(self.state, "C4", [("A2", {"layer_id": "conv0", "partition": part}),
                                  ("A9", {"architecture_candidate_id": "missing", "mapping": self.plan.to_dict()})])
        before = self.state.to_dict()
        with self.assertRaisesRegex(ValueError, "unknown legal architecture"):
            apply_transaction(self.workload, self.state, action, self.candidates)
        self.assertEqual(self.state.to_dict(), before)
        stale = replace(action, base_state_hash="stale")
        self.assertFalse(validate_plan(self.workload, self.state, stale, self.candidates)["valid"])

    def test_a9_expansion_and_consolidation_keep_exact_outputs_without_dangling_cores(self):
        for target in (self.candidates[0], self.candidates[2], self.candidate):
            mapping = resized_mapping(self.workload, self.state, target)
            action = make_action_plan(self.state, "A9", [("A9", {"architecture_candidate_id": target.id, "mapping": mapping.to_dict()})])
            trial = apply_transaction(self.workload, self.state, action, self.candidates)
            compiled = compile_mapping(self.workload, trial.mapping)
            self.assertEqual(sum(unit.macs for unit in compiled.units), self.workload.total_macs)
            allowed = set(target.package.mapping_core_ids)
            self.assertTrue(all(set(item.chiplets) <= allowed for item in trial.mapping.layer_mappings))
            self.assertEqual(tuple(trial.mapping.memory_ids), tuple(target.package.memory_ids))
            for layer in self.workload.layers:
                elements = sum(unit.output_region.elements for unit in compiled.units if unit.layer_id == layer.id)
                self.assertEqual(elements, self.workload.tensor_map[layer.output].elements)

    def test_exact_cache_includes_hardware_placement_tile_and_routing_identity(self):
        cache = ExactEvaluationCache(self.candidates, self.factory, "test-oracle-v1")
        initial_key = cache.key(self.state)
        self.assertEqual(initial_key, cache.key(self.state.with_report({"different": "report"}, 99)))
        first = self.plan.mapping_map["conv0"]
        moved = self.state.__class__(self.state.architecture_candidate_id,
                                    self.plan.replace_layer(replace(first, chiplets=tuple(reversed(first.chiplets)))),
                                    self.state.model_hash)
        self.assertNotEqual(initial_key, cache.key(moved))
        cache.get(self.state, 10)
        _, hit, _ = cache.get(self.state.with_report({"a": 1}), 10)
        self.assertTrue(hit)
        self.assertEqual(cache.evaluations, 1)
        changed_hardware = replace(self.candidate, hardware=replace(self.candidate.hardware, dram_bandwidth_Bps=self.candidate.hardware.dram_bandwidth_Bps * .5))
        changed = ExactEvaluationCache([changed_hardware], self.factory, "test-oracle-v1")
        self.assertNotEqual(initial_key, changed.key(self.state))

    def test_noop_has_zero_reward_no_new_evaluation_and_same_identity(self):
        env = JointDesignEnvironment(self.workload, self.state, self.candidates, self.factory)
        item = self.plan.mapping_map["conv0"]
        action = make_action_plan(self.state, "A2", [("A2", {"layer_id": "conv0", "partition": item.partition.as_tuple()})])
        result = env.step(action)
        self.assertTrue(result.valid)
        self.assertEqual(result.reward, 0)
        self.assertTrue(result.cache_hit)
        self.assertEqual(result.new_state.fingerprint, self.state.fingerprint)
        self.assertEqual(env.oracle.evaluations, 1)

    def test_valid_worse_transition_commits_while_archive_stays_separate(self):
        objective = JointObjective(latency_weight=0, area_weight=1, power_weight=0)
        env = JointDesignEnvironment(self.workload, self.state, self.candidates, self.factory, objective=objective)
        larger = self.candidates[2]
        action = make_action_plan(self.state, "C2", [("A9", {"architecture_candidate_id": larger.id,
                                  "mapping": resized_mapping(self.workload, self.state, larger).to_dict()})])
        result = env.step(action)
        self.assertTrue(result.valid)
        self.assertLess(result.reward, 0)
        self.assertEqual(env.current_state.architecture_candidate_id, larger.id)
        self.assertEqual(env.best_state.architecture_candidate_id, self.state.architecture_candidate_id)

    def test_reward_telescopes_and_strict_archive_never_recommends_constraint_violation(self):
        objective = JointObjective(max_area_mm2=5)
        a = self.factory(self.candidates[0])(self.plan)
        b = dict(a, latency_s=a["latency_s"] * .9)
        c = dict(b, power_w=b["power_w"] * .8)
        reward = compute_reward(a, b, a, objective) + compute_reward(b, c, a, objective)
        self.assertAlmostEqual(reward, objective.penalized_cost(a, a) - objective.penalized_cost(c, a))
        result = run_joint_search(self.workload, self.state, self.candidates, self.factory, objective=objective,
                                  config=JointSearchConfig(budget=7, max_steps=8, fusion_enabled=False))
        self.assertIsNone(result.best_state)
        self.assertIsNotNone(result.closest_state)
        self.assertFalse(result.to_dict()["strict_feasible"])
        self.assertTrue(all(not item["strict_feasible"] for item in result.architecture_archive.values()))

    def test_generic_fallback_unknown_diagnosis_and_explicit_macro_plans(self):
        plans, stats = generate_candidates(self.workload, self.state, {}, self.candidates,
                                            rng=random.Random(5), shortlist=64, random_quota=8)
        self.assertEqual(diagnose(self.state, {})["evidence"], "unknown")
        self.assertTrue(any(plan.family_id.startswith("A") for plan in plans))
        self.assertTrue(any(plan.family_id in {"C2", "C3", "C4", "C6"} for plan in plans))
        self.assertTrue(all(plan.base_state_hash == self.state.fingerprint for plan in plans))
        hashes = [apply_transaction(self.workload, self.state, plan, self.candidates).fingerprint for plan in plans]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(stats["full_evaluations"], 0)

    def test_fusion_off_masks_all_df_actions(self):
        plans, _ = generate_candidates(self.workload, self.state, {}, self.candidates,
                                        fusion_enabled=False, shortlist=64)
        self.assertFalse(any(edit.action_id in {"A1", "A3", "A7"} for plan in plans for edit in plan.ordered_edits))

    def test_composites_record_explicit_coordinated_edits_and_exact_state_dedup(self):
        report = self.factory(self.candidate)(self.plan)
        report["diagnostics"]["network"] = [{"source": "a", "destination": "b", "time_windows": [{"queue_wait_s": .1, "flow_id": "hot0"}]}]
        report["diagnostics"]["flows"] = [{"flow_id": "hot0", "tensor_id": "weights:conv0", "producer_units": [],
                                             "consumer_units": ["conv0:mb0:s0:t0"]}]
        plans, _ = generate_candidates(self.workload, self.state, report, self.candidates,
                                       rng=random.Random(11), shortlist=512, random_quota=24, max_per_family=48)
        families = {plan.family_id for plan in plans}
        self.assertTrue({"C1", "C2", "C3", "C4", "C5", "C6", "C9"} <= families)
        for plan in plans:
            if plan.family_id.startswith("C"):
                self.assertGreaterEqual(len(plan.ordered_edits), 2)
            if plan.family_id in {"C2", "C3"}:
                self.assertTrue({"A9", "A2", "A5", "A8"} <= {edit.action_id for edit in plan.ordered_edits})
        identities = [apply_transaction(self.workload, self.state, plan, self.candidates).fingerprint for plan in plans]
        self.assertEqual(len(identities), len(set(identities)))
        fuse = make_action_plan(self.state, "A1", [("A1", {"operation": "merge", "layer_ids": ["conv0", "conv1"], "tile_hw": [2, 2]})])
        fused = apply_transaction(self.workload, self.state, fuse, self.candidates)
        df_plans, _ = generate_candidates(self.workload, fused, report, self.candidates,
                                          shortlist=128, random_quota=12, max_per_family=32)
        self.assertTrue({"C7", "C8"} <= {plan.family_id for plan in df_plans})
        for plan in df_plans:
            if plan.family_id in {"C7", "C8"}:
                self.assertEqual({"A3", "A7"}, {edit.action_id for edit in plan.ordered_edits})

    def test_nonexecutable_physical_result_rolls_back_without_fictitious_reward(self):
        def factory(candidate):
            if candidate.id == self.candidates[2].id:
                return lambda plan: {"feasible": False, "reason": "buffer overflow"}
            return self.factory(candidate)
        env = JointDesignEnvironment(self.workload, self.state, self.candidates, factory)
        larger = self.candidates[2]
        action = make_action_plan(self.state, "A9", [("A9", {"architecture_candidate_id": larger.id,
                                  "mapping": resized_mapping(self.workload, self.state, larger).to_dict()})])
        before = env.current_state.fingerprint
        result = env.step(action)
        self.assertFalse(result.valid)
        self.assertEqual(result.reward, 0)
        self.assertEqual(env.current_state.fingerprint, before)
        self.assertEqual(result.rejection_reason, "buffer overflow")
        self.assertNotIn(larger.id, env.architecture_archive)
        trial = apply_transaction(self.workload, self.state, action, self.candidates)
        self.assertIn(trial.fingerprint, env.oracle.invalid_design_hashes)
        plans, _ = generate_candidates(self.workload, self.state, {}, self.candidates,
                                        shortlist=64, excluded_state_hashes=env.oracle.invalid_design_hashes)
        self.assertTrue(all(apply_transaction(self.workload, self.state, plan, self.candidates).fingerprint != trial.fingerprint
                            for plan in plans))

    def test_same_compute_count_shape_change_stays_a9(self):
        shapes = enumerate_gemini_architectures(compute_counts=(4,), include_shapes=True)
        candidate = next(item for item in shapes if item.hardware.cluster_rows == item.hardware.cluster_cols)
        mapping = initial_mapping(self.workload, candidate.package.mapping_core_ids, candidate.package.memory_ids,
                                   microbatch_size=2, max_group_layers=2)
        state = DesignState(candidate.id, mapping, self.workload.fingerprint)
        plans, _ = generate_candidates(self.workload, state, {}, shapes, shortlist=128)
        shape_changes = [plan for plan in plans if any(edit.action_id == "A9" for edit in plan.ordered_edits)]
        self.assertTrue(shape_changes)
        self.assertTrue(all(plan.family_id == "A9" for plan in shape_changes))
        self.assertFalse(any(plan.family_id in {"C2", "C3"} for plan in plans))

    def test_generic_quota_cannot_silently_remove_all_legal_macros(self):
        plans, _ = generate_candidates(self.workload, self.state, {}, self.candidates,
                                        shortlist=2, random_quota=500, rng=random.Random(7))
        self.assertEqual(len(plans), 2)
        self.assertTrue(any(plan.family_id.startswith("A") for plan in plans))
        self.assertTrue(any(plan.family_id.startswith("C") for plan in plans))
        with self.assertRaisesRegex(ValueError, "at least 2"):
            JointSearchConfig(proposal="composite", shortlist=1)
        with self.assertRaisesRegex(ValueError, "at least 2"):
            generate_candidates(self.workload, self.state, {}, self.candidates, shortlist=1)
        atomic, _ = generate_candidates(self.workload, self.state, {}, self.candidates,
                                         proposal="atomic", shortlist=1)
        self.assertEqual(len(atomic), 1)

    def test_c5_only_couples_storage_of_actual_queued_flow_owners(self):
        report = {"diagnostics": {"network": [{"time_windows": [{"flow_id": "queued", "queue_wait_s": .25}]}],
                                  "flows": [{"flow_id": "queued", "tensor_id": "weights:conv0", "consumer_units": ["conv0:mb0:s0:t0"]},
                                            {"flow_id": "unrelated", "tensor_id": "weights:conv1", "consumer_units": ["conv1:mb0:s0:t0"]}]}}
        plans, statistics = generate_candidates(self.workload, self.state, report, self.candidates,
                                                 shortlist=512, random_quota=24, max_per_family=48)
        c5 = [plan for plan in plans if plan.family_id == "C5"]
        self.assertTrue(c5)
        self.assertEqual(statistics["diagnosis"]["hotspot_layer_ids"], ["conv0"])
        for plan in c5:
            self.assertIn("conv0", plan.target_ids)
            self.assertTrue(all(edit.parameters["tensor_id"] == "weight:conv0"
                                for edit in plan.ordered_edits if edit.action_id == "A8"))
        self.assertTrue(any(plan.family_id == "A8" and plan.ordered_edits[0].parameters["tensor_id"] == "weight:conv1" for plan in plans))
        report["diagnostics"]["flows"] = []
        unknown, _ = generate_candidates(self.workload, self.state, report, self.candidates, shortlist=128)
        self.assertFalse(any(plan.family_id == "C5" for plan in unknown))

    def test_no_overlap_stack_does_not_receive_duplicate_cache_modes(self):
        shape = (1, 4, 4, 4)
        workload = Workload("pointwise", (TensorSpec("x", shape), TensorSpec("a", shape, producer="p0"),
                                          TensorSpec("y", shape, producer="p1")),
                            (LayerSpec("p0", "Identity", ("x",), "a", vector_ops_per_element=1),
                             LayerSpec("p1", "Identity", ("a",), "y", vector_ops_per_element=1)), ("x",), ("y",))
        mapping = initial_mapping(workload, self.candidate.package.mapping_core_ids,
                                   self.candidate.package.memory_ids, max_group_layers=2)
        state = DesignState(self.candidate.id, mapping, workload.fingerprint)
        fuse = make_action_plan(state, "A1", [("A1", {"layer_ids": ["p0", "p1"], "tile_hw": [2, 2]})])
        fused = apply_transaction(workload, state, fuse, self.candidates)
        plans, _ = generate_candidates(workload, fused, {}, self.candidates, shortlist=128)
        self.assertFalse(any(plan.family_id in {"C7", "C8"} for plan in plans))
        self.assertFalse(any(edit.action_id == "A7" and (edit.parameters["cache_h"] or edit.parameters["cache_v"])
                             for plan in plans for edit in plan.ordered_edits))
        invalid = make_action_plan(fused, "A7", [("A7", {"layer_ids": ["p0", "p1"], "cache_h": True, "cache_v": True})])
        self.assertFalse(validate_plan(workload, fused, invalid, self.candidates)["valid"])

    def test_policy_reinforcement_changes_actual_behavior_probability(self):
        policy = LinearActorCritic(actor_features=2, state_size=1, entropy=0, discount=1)
        features = np.eye(2)
        before = policy.probabilities(features)
        policy.update(features, 0, before, np.ones(1), np.ones(1), 1., True)
        self.assertGreater(policy.probabilities(features)[0], before[0])

    def test_seed_reproducibility_and_resume_match_uninterrupted_training(self):
        full = JointSearchConfig(seed=31, budget=40, max_steps=12, horizon=5, fusion_enabled=False,
                                  max_per_family=3, shortlist=16, random_quota=4)
        expected = run_joint_search(self.workload, self.state, self.candidates, self.factory, config=full,
                                    evaluator_identity="toy-known-v1")
        test_tmp = Path(__file__).resolve().parents[2] / "tmp"
        test_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_tmp) as temporary:
            checkpoint = Path(temporary) / "joint.json"
            run_joint_search(self.workload, self.state, self.candidates, self.factory,
                              config=replace(full, max_steps=4), checkpoint_path=checkpoint,
                              evaluator_identity="toy-known-v1")
            actual = run_joint_search(self.workload, self.state, self.candidates, self.factory,
                                      config=full, checkpoint_path=checkpoint, resume=True,
                                      evaluator_identity="toy-known-v1")
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(saved["policy"]["discount"], 1.0)
        self.assertEqual(actual.evaluations, expected.evaluations)
        self.assertEqual(actual.requests, expected.requests)
        self.assertEqual(actual.policy_updates, expected.policy_updates)
        self.assertEqual(actual.current_state.fingerprint, expected.current_state.fingerprint)
        self.assertEqual(actual.best_state.fingerprint, expected.best_state.fingerprint)
        for left, right in zip(actual.trace, expected.trace):
            for field in ("action_plan", "reward", "behavior_probability", "before_state_hash", "after_state_hash"):
                self.assertEqual(left[field], right[field])

    def test_all_methods_charge_every_physical_query_and_keep_cumulative_budget(self):
        for method in ("rl", "random", "greedy"):
            calls = []
            def factory(candidate):
                oracle = self.factory(candidate)
                def evaluate(mapping):
                    calls.append((candidate.id, mapping))
                    return oracle(mapping)
                return evaluate
            result = run_joint_search(self.workload, self.state, self.candidates, factory,
                                      config=JointSearchConfig(method=method, budget=5, max_steps=40,
                                                               fusion_enabled=False, shortlist=12, max_per_family=3))
            self.assertLessEqual(len(calls), 5)
            self.assertEqual(result.evaluations, len(calls))
            self.assertGreaterEqual(result.requests, result.evaluations)
            self.assertTrue(all(row["evaluations"] <= 5 for row in result.trace))

    def test_rl_resume_after_full_query_budget_matches_one_larger_run(self):
        full = JointSearchConfig(seed=83, budget=12, max_steps=40, horizon=7,
                                  fusion_enabled=False, shortlist=16, max_per_family=4, random_quota=4)
        expected = run_joint_search(self.workload, self.state, self.candidates, self.factory,
                                    config=full, evaluator_identity="budget-oracle-v1")
        test_tmp = Path(__file__).resolve().parents[2] / "tmp"
        test_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_tmp) as temporary:
            checkpoint = Path(temporary) / "joint.json"
            first = run_joint_search(self.workload, self.state, self.candidates, self.factory,
                                     config=replace(full, budget=4), checkpoint_path=checkpoint,
                                     evaluator_identity="budget-oracle-v1")
            self.assertEqual(first.evaluations, 4)
            actual = run_joint_search(self.workload, self.state, self.candidates, self.factory,
                                      config=full, checkpoint_path=checkpoint, resume=True,
                                      evaluator_identity="budget-oracle-v1")
        self.assertEqual(actual.evaluations, expected.evaluations)
        self.assertEqual(actual.requests, expected.requests)
        self.assertEqual(actual.policy_updates, expected.policy_updates)
        self.assertEqual(actual.current_state.fingerprint, expected.current_state.fingerprint)
        self.assertEqual(len(actual.trace), len(expected.trace))
        for left, right in zip(actual.trace, expected.trace):
            for field in ("action_plan", "reward", "behavior_probability", "before_state_hash", "after_state_hash", "budget_truncated"):
                self.assertEqual(left[field], right[field])


if __name__ == "__main__":
    unittest.main()
