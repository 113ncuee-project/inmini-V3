"""Deadline isolation, completed PPA/export separation and cumulative ledgers."""
from pathlib import Path
import tempfile
import time
import unittest

from simple_rapidchiplet.hybrid.auto_runtime import EvaluationTimeout
from simple_rapidchiplet.hybrid.mapping import initial_mapping
from simple_rapidchiplet.hybrid.single_array_hardware import enumerate_single_array_architectures
from simple_rapidchiplet.hybrid.single_array_runtime import SingleArrayOraclePool
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class SingleArrayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2] / 'tmp'
        self.root.mkdir(exist_ok=True)
        self.workload = make_toy_workload(batch=1, channels=3, spatial=5)
        self.candidate = enumerate_single_array_architectures((1,))[0]
        self.mapping = initial_mapping(self.workload, self.candidate.package.mapping_core_ids,
                                       self.candidate.package.memory_ids)

    def test_completed_PPA_is_counted_once_and_export_never_replays_oracle(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            path = Path(directory)
            pool = SingleArrayOraclePool(self.workload, path / 'worker', deadline=time.monotonic() + 30,
                                         evaluation_timeout_s=10)
            try:
                response = pool.evaluate(self.candidate, self.mapping, phase='unit')
                self.assertTrue(response['metrics']['feasible'])
                self.assertEqual(pool.full_evaluations, 1)
                pool.persist(self.candidate, self.mapping, path / 'report', {'render_images': False})
                self.assertEqual(pool.full_evaluations, 1)
                self.assertEqual(len(pool.records), 2)
                self.assertTrue((path / 'report' / 'evaluation.json').exists())
                self.assertEqual(list((path / 'report').glob('*.png')), [])
            finally:
                pool.close()
            resumed = SingleArrayOraclePool(self.workload, path / 'worker', deadline=time.monotonic() + 10,
                                            evaluation_timeout_s=5)
            self.assertEqual(resumed.full_evaluations, 1)
            self.assertEqual(len(resumed.records), 2)
            self.assertTrue(resumed.records[0]['mapping_hash'])
            self.assertEqual(resumed.records[0]['fusion_depths'], [])
            resumed.close()

    def test_hard_timeout_returns_no_partial_PPA_and_owned_worker_is_stopped(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            pool = SingleArrayOraclePool(self.workload, directory, deadline=time.monotonic() + 10,
                                         evaluation_timeout_s=.001)
            try:
                with self.assertRaises(EvaluationTimeout):
                    pool.evaluate(self.candidate, self.mapping)
                self.assertEqual(pool.full_evaluations, 0)
                self.assertEqual(pool.records[-1]['status'], 'timeout')
                self.assertTrue(pool.process is None or pool.process.poll() is not None)
            finally:
                pool.close()


if __name__ == '__main__':
    unittest.main()
