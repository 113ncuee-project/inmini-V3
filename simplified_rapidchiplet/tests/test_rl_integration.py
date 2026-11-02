"""Production contracts: PPA semantics, multi-model ranking and persisted deployment."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import rl_dse


class ProductionJointDSETests(unittest.TestCase):
    def test_low_power_optimizes_power_independently_of_energy(self):
        objective=rl_dse.make_objective({'preference':'low_power'})
        reference={'latency_s':1.,'area_mm2':1.,'power_w':1.,'energy_j':1.}
        lower_power={**reference,'latency_s':2.,'power_w':.5,'energy_j':20.}
        self.assertAlmostEqual(objective.cost(lower_power,reference),.7)
        self.assertEqual(objective.energy_weight,0)

    def test_soft_goal_and_hard_limit_are_separate(self):
        metrics={'feasible':True,'latency_s':1.,'area_mm2':2.,'power_w':1.,'energy_j':1.}
        hard=rl_dse.make_objective({'max_area':1.,'strict_area':True})
        soft=rl_dse.make_objective({'max_area':1.,'strict_area':False})
        self.assertFalse(rl_dse.constraints(metrics,hard)['strict_compliant'])
        self.assertTrue(rl_dse.constraints(metrics,soft)['strict_compliant'])
        self.assertFalse(rl_dse.constraints(metrics,soft)['all_targets_met'])

    def test_no_recommendation_can_hide_one_model_missing_a_limit(self):
        rows=[dict(model='a',architecture='small',cost=1.,within_limits=True,
                   constraints={'physical_feasible':True,'limits':[]}),
              dict(model='b',architecture='small',cost=.1,within_limits=False,
                   constraints={'physical_feasible':True,'limits':[{'strict':True,'relative_excess':.2}]})]
        ranking,recommendation=rl_dse.rank_joint_rows(rows,['a','b'])
        self.assertIsNone(recommendation['recommended_architecture'])
        self.assertEqual(recommendation['closest_architecture'],'small')
        self.assertFalse(ranking[0]['feasible_for_all_models'])
        _,missing=rl_dse.rank_joint_rows(rows[:1],['a','b'])
        self.assertIsNone(missing['display_architecture'])

    def test_end_to_end_impossible_limit_saves_diagnostic_not_recommendation(self):
        temp=ROOT.parent/'tmp'
        temp.mkdir(exist_ok=True)
        config={'models':['toy'],'batch':1,'budget':2,'seed':7,'dies':[1],
                'seed_budget':1,'groups':2,'preference':'balanced','fusion':'off',
                'method':'rl','proposal':'composite','max_area':1.,'strict_area':True}
        with tempfile.TemporaryDirectory(dir=temp) as directory:
            result=rl_dse.run_suite(config,directory)
            self.assertIsNone(result['best_architecture'])
            self.assertIsNone(result['recommended_chiplets'])
            self.assertEqual(result['recommendation_status'],'no_feasible_solution')
            row=result['runs'][0]
            deployment=json.loads((Path(row['folder'])/'deployment.json').read_text(encoding='utf-8'))
            self.assertEqual(deployment['chiplet_profile'],'gemini_2x2_core_v1')
            self.assertEqual(deployment['compute_chiplets'],1)
            self.assertEqual(deployment['io_chiplets'],2)
            self.assertEqual(deployment['memory_dies'],2)
            self.assertTrue((Path(directory)/'toy'/'report.html').is_file())
            accounting=json.loads((Path(directory)/'toy'/'accounting.json').read_text(encoding='utf-8'))
            self.assertEqual(accounting['rl_unique_full_evaluations'],2)
            self.assertGreaterEqual(accounting['total_full_evaluations_this_process'],3)


if __name__=='__main__':
    unittest.main()
