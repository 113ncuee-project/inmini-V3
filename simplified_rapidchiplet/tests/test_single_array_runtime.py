"""Deadline isolation, completed PPA/export separation and cumulative ledgers."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import subprocess
import os
import sys
import json

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

    def test_idle_cleanup_uses_EOF_without_external_taskkill(self):
        from simple_rapidchiplet.hybrid.auto_runtime import BoundedOraclePool
        pool=object.__new__(BoundedOraclePool);pool.process=Mock();pool.log=Mock()
        process=pool.process;log=pool.log
        with patch('simple_rapidchiplet.hybrid.auto_runtime.subprocess.run') as taskkill:
            pool.close()
            taskkill.assert_not_called()
        process.stdin.close.assert_called_once();process.wait.assert_called_once()
        self.assertIsNone(pool.process);log.close.assert_called_once()

    def test_taskkill_timeout_can_reap_verified_owned_worker(self):
        from simple_rapidchiplet.hybrid.auto_runtime import BoundedOraclePool
        pool=object.__new__(BoundedOraclePool);pool.process=Mock();pool.log=None
        process=pool.process;process.wait.side_effect=[subprocess.TimeoutExpired('worker',2),0]
        process.poll.return_value=None
        with patch('simple_rapidchiplet.hybrid.auto_runtime.os.name','nt'), \
             patch('simple_rapidchiplet.hybrid.auto_runtime.subprocess.run',side_effect=subprocess.TimeoutExpired('taskkill',5)), \
             patch.object(pool,'_stop_recorded_windows_worker',return_value=True) as verified:
            pool.close()
            verified.assert_called_once();process.kill.assert_called_once()
        self.assertIsNone(pool.process)

    @unittest.skipUnless(os.name=='nt','Windows venv launcher lifecycle')
    def test_real_windows_launcher_fallback_stops_only_its_recorded_child(self):
        from simple_rapidchiplet.hybrid.auto_runtime import BoundedOraclePool
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            folder=Path(directory);marker=folder/'worker_started.json'
            code="import os,sys,json,time; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps(dict(worker_pid=os.getpid(),parent_pid=os.getppid()))); time.sleep(8)"
            process=subprocess.Popen([sys.executable,'-c',code,str(marker)],stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            pool=object.__new__(BoundedOraclePool);pool.process=process;pool.folder=folder;pool.log=None
            try:
                deadline=time.monotonic()+5
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(marker.exists())
                with patch('simple_rapidchiplet.hybrid.auto_runtime.subprocess.run',side_effect=subprocess.TimeoutExpired('taskkill',5)):
                    pool.close()
                self.assertIsNotNone(process.poll())
                self.assertIsNone(pool.process)
            finally:
                # The test helper is independently self-bounded to 8 seconds
                # even if the fallback assertion fails.
                process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
