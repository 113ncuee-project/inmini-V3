from dataclasses import replace
from pathlib import Path
import random
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simple_rapidchiplet.hybrid.replay_q import ReplayQ
from simple_rapidchiplet.hybrid.mapping_proposals_v4 import StructuredMappings
from simple_rapidchiplet.hybrid.mapping import initial_mapping
from simple_rapidchiplet.hybrid.workload import make_toy_workload
from simple_rapidchiplet.hybrid.rl_schema import DesignState
from simple_rapidchiplet.hybrid.single_array_hardware import enumerate_single_array_architectures_v3
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator
from replay_mapping_dse import cost

class ReplayMappingTests(unittest.TestCase):
    def fixture(self):
        w=make_toy_workload(batch=1,channels=5,spatial=7)
        c=next(c for c in enumerate_single_array_architectures_v3() if c.id=='single_array_c2_2x1')
        m=initial_mapping(w,c.hardware.compute_slots,c.package.memory_ids,max_group_layers=1)
        s=DesignState(c.id,m,w.fingerprint,c.hardware.profile_id,version=3)
        return w,c,s

    def test_replay_learns_utility_order_and_is_not_uniform(self):
        rng=np.random.default_rng(11);x=rng.normal(size=(32,8)).astype(np.float32)
        y=4*x[:,0]-3*x[:,1]+2*x[:,2]
        policy=ReplayQ(8,seed=7)
        before=np.mean((policy.predict(x)-y)**2)
        for a,b in zip(x,y):policy.observe(a,b,updates=12)
        after=np.mean((policy.predict(x)-y)**2)
        self.assertLess(after,before*.12)
        p,_=policy.probabilities(x,.1)
        self.assertGreater(p.max(),3/len(p));self.assertAlmostEqual(float(p.sum()),1.,places=6)
        self.assertEqual(policy.updates,384)

    def test_saved_policy_replays_identical_predictions(self):
        root=Path(__file__).resolve().parents[2]/'tmp';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            p=ReplayQ(5);x=np.eye(5,dtype=np.float32)
            for row in x:p.observe(row,float(row[0])*10,updates=3)
            p.save(Path(tmp)/'policy.pt');q=ReplayQ(5);q.load(Path(tmp)/'policy.pt')
            np.testing.assert_array_equal(p.predict(x),q.predict(x))
            self.assertEqual(p.updates,q.updates)

    def test_global_bank_keeps_hardware_fusion_and_integer_ownership(self):
        from simple_rapidchiplet.hybrid.mapping import validate_plan
        w,c,s=self.fixture();bank=StructuredMappings(w,c,s)
        trials=bank.global_pool();self.assertGreater(len(trials),50)
        self.assertEqual(len({t.fingerprint for t in trials}),len(trials))
        for trial in trials:
            self.assertEqual(trial.state.architecture_candidate_id,s.architecture_candidate_id)
            self.assertFalse(trial.state.mapping.fusion_stacks)
            validate_plan(w,trial.state.mapping,c.hardware.compute_slots)
        self.assertTrue(any(any(m.weight_policy=='persistent' for m in t.state.mapping.layer_mappings) for t in trials))

    def test_native_and_reference_preserve_actual_PPA_and_capacity(self):
        w,c,s=self.fixture();bank=StructuredMappings(w,c,s)
        candidates=[bank.build((q,d,'spread','interleave',p)) for q,d,p in
            ((2,'K','cold'),(4,'P','persistent'),(8,'balanced','auto'))]
        for trial in candidates:
            old=SingleArrayEvaluator(w,c.hardware,calendar_backend='coalesced')(trial.state.mapping)
            new=SingleArrayEvaluator(w,c.hardware,calendar_backend='auto')(trial.state.mapping)
            for key in ('latency_s','energy_j','power_w','area_mm2','executed_macs','dram_read_bytes','dram_write_bytes','noc_hop_bytes','nop_hop_bytes'):
                self.assertEqual(old.metrics[key],new.metrics[key])
            self.assertEqual(new.metrics['executed_macs'],w.total_macs)
            self.assertAlmostEqual(new.metrics['power_w']*new.metrics['latency_s'],new.metrics['energy_j'],places=14)
            if new.metrics['feasible']:
                for row in new.metrics['diagnostics']['memory']:self.assertLessEqual(row['peak_live_bytes'],row['capacity_bytes'])

    def test_service_cache_returns_independent_energy_and_kernel_dicts(self):
        w,c,s=self.fixture();oracle=SingleArrayEvaluator(w,c.hardware);first=oracle(s.mapping)
        transfer=first.communication.transfers[0];a=oracle.transfer_service(transfer);a[3]['poison']=1
        self.assertNotIn('poison',oracle.transfer_service(transfer)[3])
        unit=next(u for u in first.compiled.units if u.macs)
        kernel=oracle._kernel(unit,w.layer_map[unit.layer_id]);kernel['mac_cycles']=-999
        self.assertGreater(oracle._kernel(unit,w.layer_map[unit.layer_id])['mac_cycles'],0)

    def test_geometry_reuse_preserves_full_PPA_after_flow_and_retention_changes(self):
        w,c,s=self.fixture();warm=SingleArrayEvaluator(w,c.hardware)
        warm(s.mapping)
        for flow,policy in (('weight_reuse','cold'),('output_stationary','persistent'),('activation_reuse','cold')):
            mapping=replace(s.mapping,layer_mappings=tuple(replace(m,dataflow=flow,weight_policy=policy) for m in s.mapping.layer_mappings))
            a=warm(mapping);b=SingleArrayEvaluator(w,c.hardware)(mapping)
            self.assertTrue(a.metrics['exact_geometry_cache_hit'])
            for key in ('latency_s','energy_j','power_w','feasible','dram_read_bytes','noc_hop_bytes','nop_hop_bytes'):
                self.assertEqual(a.metrics[key],b.metrics[key])
            self.assertEqual(a.buffer_statistics,b.buffer_statistics)

    def test_objective_and_invalid_reports_are_not_fictitious_rewards(self):
        m=dict(feasible=True,latency_s=2.,energy_j=6.,power_w=3.,area_mm2=5.)
        self.assertEqual(cost(m,m,'balanced'),1.)
        self.assertEqual(cost(m,m,'edp'),1.)
        self.assertIsNone(cost({**m,'feasible':False},m,'balanced'))

    def test_geometry_hit_cannot_bypass_mapping_policy_validation(self):
        w,c,s=self.fixture();oracle=SingleArrayEvaluator(w,c.hardware);oracle(s.mapping)
        for field in ('dataflow','weight_policy'):
            mapping=replace(s.mapping,layer_mappings=tuple(replace(m,**{field:'invalid-policy'}) for m in s.mapping.layer_mappings))
            with self.assertRaises(ValueError):oracle(mapping)

if __name__=='__main__':unittest.main()
