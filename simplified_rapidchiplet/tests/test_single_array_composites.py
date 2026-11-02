"""Every advertised C1..C9 has a legal transaction and final-invalid rollback."""
from dataclasses import replace
import unittest

from simple_rapidchiplet.hybrid.mapping import LayerGroup, initial_mapping
from simple_rapidchiplet.hybrid.rl_actions import apply_transaction, resized_mapping
from simple_rapidchiplet.hybrid.rl_schema import ActionEdit, DesignState, make_action_plan
from simple_rapidchiplet.hybrid.single_array_hardware import PROFILE, enumerate_single_array_architectures
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class CompositeContractTests(unittest.TestCase):
    def test_C1_through_C9_commit_only_complete_legal_PE_transactions(self):
        w = make_toy_workload(batch=1, channels=5, spatial=7)
        candidates = enumerate_single_array_architectures((1, 2))
        one, two = candidates[0], candidates[1]
        mapping = initial_mapping(w, one.package.mapping_core_ids, one.package.memory_ids)
        state = DesignState(one.id, mapping, w.fingerprint, PROFILE, version=2)
        def plan(base, family, edits):
            return make_action_plan(base, family, [ActionEdit(action, parameters) for action, parameters in edits])
        allocations = {
            'conv0': {'cores': list(mapping.mapping_map['conv0'].chiplets) + ['compute:0/pe:5'], 'partition': [1, 1, 1, 6]},
            'conv1': {'cores': list(mapping.mapping_map['conv1'].chiplets)[1:], 'partition': [1, 1, 1, 4]},
        }
        c1 = plan(state, 'C1', [('A4', {'allocations': allocations}), ('A2', {'layer_id': 'conv0', 'partition': [1, 1, 1, 6]})])
        expanded_mapping = resized_mapping(w, state, two)
        c2 = plan(state, 'C2', [('A9', {'architecture_candidate_id': two.id, 'mapping': expanded_mapping.to_dict()})])
        expanded = apply_transaction(w, state, c2, candidates)
        c3 = plan(expanded, 'C3', [('A9', {'architecture_candidate_id': one.id, 'mapping': mapping.to_dict()})])
        c4 = plan(state, 'C4', [('A2', {'layer_id': 'conv0', 'partition': [1, 1, 1, 5]}),
                              ('A2', {'layer_id': 'conv1', 'partition': [1, 1, 5, 1]})])
        c5 = plan(state, 'C5', [('A5', {'layer_id': 'conv0', 'cores': list(reversed(mapping.mapping_map['conv0'].chiplets))}),
                              ('A8', {'tensor_id': 'weight:conv0', 'configuration_id': 'memory:1'})])
        ids = [layer.id for layer in w.layers]
        fused_allocations = {lid: {'cores': ['compute:0/pe:0'], 'partition': [1, 1, 1, 1]} for lid in ids}
        c6 = plan(state, 'C6', [('A10', {'groups': [{'id': 'joint', 'layer_ids': ids, 'mode': 'temporal'}]}),
                              ('A4', {'allocations': fused_allocations}),
                              ('A1', {'operation': 'merge', 'layer_ids': ids, 'tile_hw': [4, 4]})])
        fused = apply_transaction(w, state, c6, candidates)
        c7 = plan(fused, 'C7', [('A3', {'layer_ids': ids, 'tile_hw': [2, 2]}),
                              ('A7', {'layer_ids': ids, 'cache_h': False, 'cache_v': False})])
        c8 = plan(fused, 'C8', [('A3', {'layer_ids': ids, 'tile_hw': [7, 7]}),
                              ('A7', {'layer_ids': ids, 'cache_h': True, 'cache_v': True})])
        c9 = plan(state, 'C9', [('A10', {'groups': [{'id': 'first', 'layer_ids': ['conv0'], 'mode': 'temporal'},
                                                  {'id': 'later', 'layer_ids': ['conv1', 'add'], 'mode': 'temporal'}]}),
                              ('A4', {'allocations': {lid: fused_allocations[lid] for lid in ('conv1', 'add')}})])
        for base, transaction in ((state, c1), (state, c2), (expanded, c3), (state, c4), (state, c5),
                                  (state, c6), (fused, c7), (fused, c8), (state, c9)):
            with self.subTest(family=transaction.family_id):
                original = base.fingerprint
                trial = apply_transaction(w, base, transaction, candidates)
                self.assertNotEqual(trial.fingerprint, original)
                bad = replace(transaction, ordered_edits=(*transaction.ordered_edits,
                    ActionEdit('A2', {'layer_id': 'conv0', 'partition': [1, 999, 1, 1]})))
                with self.assertRaises(ValueError):
                    apply_transaction(w, base, bad, candidates)
                self.assertEqual(base.fingerprint, original)

    def test_labels_cannot_claim_joint_C6_or_unsupported_C10(self):
        w = make_toy_workload(batch=1)
        candidate = enumerate_single_array_architectures((1,))[0]
        mapping = initial_mapping(w, candidate.package.mapping_core_ids, candidate.package.memory_ids)
        state = DesignState(candidate.id, mapping, w.fingerprint, PROFILE, version=2)
        for family in ('C6', 'C10'):
            transaction = make_action_plan(state, family, [ActionEdit('A5', {
                'layer_id': 'conv0', 'cores': list(reversed(mapping.mapping_map['conv0'].chiplets))})])
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                apply_transaction(w, state, transaction, (candidate,))

    def test_group_label_only_changes_are_not_fake_new_designs_in_schema2(self):
        w = make_toy_workload(batch=1)
        candidate = enumerate_single_array_architectures((1,))[0]
        mapping = initial_mapping(w, candidate.package.mapping_core_ids, candidate.package.memory_ids)
        state = DesignState(candidate.id, mapping, w.fingerprint, PROFILE, version=2)
        renamed = replace(mapping, groups=tuple(replace(group, id='renamed_' + group.id) for group in mapping.groups))
        self.assertEqual(state.fingerprint, replace(state, mapping=renamed).fingerprint)
        historical = replace(state, version=1)
        self.assertNotEqual(historical.fingerprint, replace(historical, mapping=renamed).fingerprint)


if __name__ == '__main__':
    unittest.main()
