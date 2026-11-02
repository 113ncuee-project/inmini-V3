"""GUI03-input contract for the v0.2 engine, plus a real text-only toy run."""
import json
from pathlib import Path
import tempfile
import unittest

import hybrid_gui
from simple_rapidchiplet.hybrid.single_array_hardware import PROFILE
from single_array_gui import run_suite


class GUI04V3Tests(unittest.TestCase):
    def test_defaults_are_fixed_Batch1_new_profile_and_separate_from_v2(self):
        config, provenance = hybrid_gui.normalize_gui_request({'ui_schema_version': 3})
        self.assertEqual(config['models'], ['resnet18'])
        self.assertEqual(config['hardware_profile'], PROFILE)
        self.assertEqual(config['max_wall_time_s'], 1800.)
        self.assertEqual((config['batch'], config['seed'], config['horizon']), (1, 7, 12))
        self.assertFalse(config['render_images'])
        self.assertNotIn('ub_mib', config)
        self.assertNotIn('prefetch_slots', config)
        self.assertEqual(len(config['architecture_templates']), 15)
        old, _ = hybrid_gui.normalize_gui_request({'ui_schema_version': 2})
        self.assertEqual(old['engine_profile'], 'gui04_v2')
        self.assertEqual(old['max_wall_time_s'], 480.)
        self.assertEqual(provenance['microbatch_candidates'], [1])

    def test_constraints_preferences_and_deep_override_are_preserved(self):
        raw = {'ui_schema_version': 3, 'models': ['toy'], 'preference': 'low_power',
               'max_power': .7, 'max_area': 35., 'max_latency_ms': .1, 'strict_latency': False,
               'search_mode': 'deep', 'budget_mode': 'manual', 'budget': 17}
        config, _ = hybrid_gui.normalize_gui_request(raw)
        self.assertEqual(config['max_wall_time_s'], 3600.)
        for key in ('max_power', 'max_area', 'max_latency_ms', 'strict_latency', 'preference', 'budget'):
            self.assertEqual(config[key], raw[key])
        with self.assertRaises(ValueError):
            hybrid_gui.normalize_gui_request({'ui_schema_version': 3, 'chiplet_count': 8})

    def test_real_GUI_toy_produces_numerical_report_without_images(self):
        root = Path(__file__).resolve().parents[2] / 'tmp'
        root.mkdir(exist_ok=True)
        config, _ = hybrid_gui.normalize_gui_request({'ui_schema_version': 3, 'models': ['toy'],
                                                     'search_mode': 'fast', 'budget_mode': 'manual', 'budget': 3})
        # Bounded test time is an engine setting; it is not an exposed GUI knob.
        config.update(max_wall_time_s=20., evaluation_timeout_s=5.)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            result = run_suite(config, directory)
            self.assertEqual(result['chiplet_profile'], PROFILE)
            self.assertTrue(result['runs'])
            self.assertTrue(all(row.get('hardware_profile') == PROFILE for row in result['runs']))
            folder = Path(directory)
            report = folder / 'toy' / 'REPORT.md'
            self.assertTrue(report.exists())
            self.assertNotIn('![', report.read_text(encoding='utf-8'))
            self.assertEqual(list(folder.rglob('*.svg')), [])
            self.assertEqual(list(folder.rglob('*.png')), [])
            summary = json.loads((folder / 'toy' / 'summary.json').read_text(encoding='utf-8'))['bottleneck_rl']
            self.assertLessEqual(summary['full_ppa_completed'], 3)
            self.assertGreater(summary['policy_updates'], 0)


if __name__ == '__main__':
    unittest.main()
