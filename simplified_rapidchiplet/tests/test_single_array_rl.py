"""Schema-v2 reachability, temporal transactions, joint DF and learned features."""
from dataclasses import replace
import tempfile
import gzip
import json
import unittest
from pathlib import Path

import numpy as np

from simple_rapidchiplet.hybrid.mapping import LayerGroup, initial_mapping
from simple_rapidchiplet.hybrid.rl_actions import apply_transaction, generate_candidates, validate_state
from simple_rapidchiplet.hybrid.rl_schema import ActionEdit, DesignState, make_action_plan
from simple_rapidchiplet.hybrid.rl_search import (
    ACTION_SIZE_V2, STATE_SIZE_V2, JointObjective, JointSearchConfig, candidate_features,
    run_joint_search, state_features,
)
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator
from simple_rapidchiplet.hybrid.single_array_hardware import PROFILE, enumerate_single_array_architectures
from simple_rapidchiplet.hybrid.single_array_proposals import SingleArrayJointProposals
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class SingleArrayRLTests(unittest.TestCase):
    def setUp(self):
        self.workload = make_toy_workload(batch=1, channels=5, spatial=7)
        self.candidates = enumerate_single_array_architectures()
        self.candidate = self.candidates[0]
        self.mapping = initial_mapping(self.workload, self.candidate.package.mapping_core_ids,
                                       self.candidate.package.memory_ids, max_group_layers=3)
        self.state = DesignState(self.candidate.id, self.mapping, self.workload.fingerprint,
                                  hardware_template_version=PROFILE, version=2)

    def test_A9_all_rectangles_reachable_in_one_step(self):
        for start in (self.candidates[0], self.candidates[-1]):
            mapping = initial_mapping(self.workload, start.package.mapping_core_ids, start.package.memory_ids)
            state = replace(self.state, architecture_candidate_id=start.id, mapping=mapping)
            plans, _ = generate_candidates(self.workload, state, {}, self.candidates,
                                           shortlist=64, max_per_family=12)
            targets = set()
            for plan in plans:
                for edit in plan.ordered_edits:
                    if edit.action_id == 'A9':
                        trial = apply_transaction(self.workload, state, plan, self.candidates)
                        targets.add(trial.architecture_candidate_id)
                        self.assertTrue(all('/pe:' in slot for item in trial.mapping.layer_mappings for slot in item.chiplets))
            self.assertEqual(targets, {c.id for c in self.candidates if c.id != start.id})

    def test_C9_temporal_group_reuses_PE_sets_and_rolls_back_on_invalid_final_state(self):
        ids = tuple(layer.id for layer in self.workload.layers)
        allocations = {lid: {'cores': ['compute:0/pe:0'], 'partition': [1, 1, 1, 1]} for lid in ids}
        plan = make_action_plan(self.state, 'C9', [ActionEdit('A10', {'groups': [
            {'id': 'temporal', 'layer_ids': list(ids), 'mode': 'temporal'}]}), ActionEdit('A4', {'allocations': allocations})])
        trial = apply_transaction(self.workload, self.state, plan, self.candidates)
        self.assertEqual(trial.mapping.groups[0].mode, 'temporal')
        self.assertTrue(all(item.chiplets == ('compute:0/pe:0',) for item in trial.mapping.layer_mappings))
        self.assertNotEqual(trial.fingerprint, self.state.fingerprint)
        original = self.state.fingerprint
        bad = replace(plan, ordered_edits=(*plan.ordered_edits, ActionEdit('A2', {'layer_id': ids[0], 'partition': [1, 2, 1, 1]})))
        with self.assertRaises(ValueError):
            apply_transaction(self.workload, self.state, bad, self.candidates)
        self.assertEqual(self.state.fingerprint, original)

    def test_joint_C6_changes_mapping_and_off_on_pair_remains_in_shared_pool(self):
        # Closed residual window must include the Add, preserving both inputs.
        hook = SingleArrayJointProposals(self.workload, self.candidates, shortlist=48, transition_cap=36)
        candidates, stats = generate_candidates(self.workload, self.state, {}, self.candidates)
        candidates, stats = hook(self.state, {}, candidates, stats)
        joint = [p for p in candidates if p.family_id == 'C6' and any(e.action_id == 'A4' for e in p.ordered_edits)]
        self.assertTrue(joint)
        self.assertTrue(any(p.family_id.startswith('A') for p in candidates))
        self.assertTrue(any(any(e.action_id == 'A9' for e in p.ordered_edits) for p in candidates))
        for plan in joint:
            trial = apply_transaction(self.workload, self.state, plan, self.candidates)
            self.assertTrue(trial.mapping.fusion_stacks)
            self.assertEqual(self.workload.layer_map['add'].inputs, ('image', 'conv1'))
            self.assertTrue(any(trial.mapping.mapping_map[lid] != self.mapping.mapping_map[lid] for lid in plan.target_ids))
        self.assertEqual(stats['joint_window']['full_evaluations'], 0)
        self.assertEqual(stats['joint_window']['physical_validity'], 'global oracle pending')

    def test_new_feature_schema_includes_real_resource_pressure(self):
        metrics = SingleArrayEvaluator(self.workload, self.candidate.hardware)(self.mapping).metrics
        features = state_features(self.state, metrics, metrics, JointObjective(), self.candidate, 256, 0.)
        self.assertEqual(features.shape, (STATE_SIZE_V2,))
        self.assertGreater(features[-1], 0.)  # real shared L2 occupancy
        plans, _ = generate_candidates(self.workload, self.state, metrics, self.candidates)
        vectors = candidate_features(self.state, plans, features, {c.id: c for c in self.candidates}, self.workload)
        self.assertEqual(vectors.shape, (len(plans), ACTION_SIZE_V2))
        self.assertTrue(np.all(np.isfinite(vectors)))
        two_die = [i for i, plan in enumerate(plans) if any(edit.action_id == 'A9' and
                   edit.parameters['architecture_candidate_id'].startswith('single_array_c2_') for edit in plan.ordered_edits)]
        self.assertEqual(len(two_die), 2)
        self.assertFalse(np.array_equal(vectors[two_die[0]], vectors[two_die[1]]),
                         'different row/column and IO populations need distinct physical embeddings')

    def test_production_RL_checkpoint_replay_preserves_trace_and_identity(self):
        cs = self.candidates[:3]
        factory = lambda candidate: SingleArrayEvaluator(self.workload, candidate.hardware)
        temporary_root = Path(__file__).resolve().parents[2] / 'tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            checkpoint = str(Path(directory) / 'checkpoint.json')
            result = run_joint_search(self.workload, self.state, cs, factory,
                config=JointSearchConfig(budget=4, max_steps=4, horizon=4, shortlist=24, checkpoint_every=1),
                checkpoint_path=checkpoint, evaluator_identity='single_array_test_v1')
            replay = run_joint_search(self.workload, self.state, cs, factory,
                config=JointSearchConfig(budget=4, max_steps=4, horizon=4, shortlist=24, checkpoint_every=1),
                checkpoint_path=checkpoint, evaluator_identity='single_array_test_v1', resume=True)
            self.assertEqual(result.best_state.fingerprint, replay.best_state.fingerprint)
            self.assertEqual(result.evaluations, replay.evaluations)
            self.assertEqual(result.trace, replay.trace)
            self.assertGreater(result.policy_updates, 0)
            for row in result.trace:
                evidence = row['candidate_shortlist']
                self.assertTrue(Path(evidence['path']).is_file())
                self.assertEqual(len(json.loads(gzip.decompress(Path(evidence['path']).read_bytes()))['plans']), row['candidate_count'])
                if row.get('behavior_probability') is not None:
                    self.assertGreater(row['behavior_probability'], 0)

    def test_per_evaluation_timeout_is_unknown_not_a_physical_reject_or_cache_hit(self):
        candidate = self.candidate
        real = SingleArrayEvaluator(self.workload, candidate.hardware)
        initial_metrics = real(self.mapping).metrics
        calls = [0]
        def evaluate(mapping):
            calls[0] += 1
            if calls[0] == 1:
                raise TimeoutError('controlled slow-query timeout')
            return real(mapping)
        root = Path(__file__).resolve().parents[2] / 'tmp'
        with tempfile.TemporaryDirectory(dir=root) as directory:
            result = run_joint_search(self.workload, self.state, (candidate,), lambda _: evaluate,
                config=JointSearchConfig(budget=2, max_steps=4, shortlist=12, proposal='atomic', checkpoint_every=1),
                bootstrap_evaluations=((self.state, initial_metrics),), checkpoint_path=str(Path(directory) / 'checkpoint.json'),
                evaluator_identity='timeout_regression')
            self.assertEqual(result.trace[0]['physical_validity'], 'unknown')
            self.assertIsNone(result.trace[0]['reward'])
            self.assertGreater(result.policy_updates, 0)
            data = result.to_dict()
            self.assertEqual(data['oracle_timeouts'], 1)
            self.assertEqual(data['cache_hits'], data['requests'] - data['evaluations'] - 1)
            saved = json.loads((Path(directory) / 'checkpoint.json').read_text(encoding='utf-8'))
            unknown_hash = result.trace[0]['attempted_state_hash']
            self.assertIn(unknown_hash, saved['timed_out_state_hashes'])
            self.assertFalse(any(m.get('design_state_hash') == unknown_hash for m in saved['cache'].values()))

    def test_old_and_new_hardware_identity_cannot_mix(self):
        with self.assertRaisesRegex(ValueError, 'matching design schema'):
            validate_state(self.workload, replace(self.state, version=1), self.candidates)
        with self.assertRaisesRegex(ValueError, 'hardware identity'):
            validate_state(self.workload, replace(self.state, hardware_template_version='gemini_2x2_core_v1'), self.candidates)


if __name__ == '__main__':
    unittest.main()
