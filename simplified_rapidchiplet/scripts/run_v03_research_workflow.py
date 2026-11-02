"""One finite, locked research job: preflight, comparisons, paired DF, audit.

This is a batch experiment, not a recurring automation. The user's paused
heartbeat is preserved. Each child uses a frozen source and its own checkpoint.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    snapshot, out = Path(args.snapshot).resolve(), Path(args.out).resolve()
    sys.path.insert(0, str(snapshot))
    from single_array_dse import exclusive_run
    from simple_rapidchiplet.hybrid.auto_runtime import atomic_json
    with exclusive_run(out / 'workflow_control'):
        manifest = json.loads((snapshot / 'snapshot_manifest.json').read_text())
        for relative, expected in manifest['files'].items():
            if hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() != expected:
                raise ValueError('frozen source mismatch: ' + relative)
        status_path = out / 'workflow_control/workflow_status.json'
        status = {'owner_pid': os.getpid(), 'status': 'running', 'snapshot_identity': manifest['identity'], 'phases': []}
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        power = ctypes.windll.kernel32.SetThreadExecutionState if os.name == 'nt' else None
        if power:
            power.argtypes, power.restype = [ctypes.c_uint], ctypes.c_uint
            status['temporary_system_awake_request'] = bool(power(0x80000001))
        def execute(name, command):
            prior = next((row for row in previous.get('phases', ()) if row['phase'] == name and row['status'] == 'completed'), None)
            if prior:
                status['phases'].append(prior)
                return
            row = {'phase': name, 'status': 'running', 'started_unix': time.time(), 'command': command}
            status['phases'].append(row)
            with (out / ('workflow_' + name + '.log')).open('ab') as log:
                child = subprocess.Popen(command, cwd=snapshot, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                row['pid'] = child.pid
                atomic_json(status_path, status)
                code = child.wait()
            row.update(return_code=code, elapsed_s=time.time() - row['started_unix'],
                       status='completed' if code == 0 else 'failed')
            atomic_json(status_path, status)
            if code:
                raise RuntimeError(name + ' failed; inspect the preserved phase log')
        py = [sys.executable, '-X', 'utf8']
        try:
            target = out / 'resnet18_preflight'
            command = py + [str(snapshot / 'single_array_dse.py'), '--engine', 'v03', '--model', 'resnet18',
                '--arms', 'bottleneck_rl', '--queries', '12', '--seed-queries', '4', '--seed-seconds', '1200',
                '--seed-dp-seconds', '120', '--seconds', '1200', '--eval-timeout', '600', '--shortlist', '64', '--out', str(target)]
            if (target / 'source_identity.json').exists(): command.append('--resume')
            execute('resnet18_preflight', command)
            execute('comparisons', py + [str(snapshot / 'scripts/run_single_array_research_suite.py'),
                '--snapshot', str(snapshot), '--out', str(out / 'results'), '--queries', '128', '--seconds', '7200',
                '--seed-seconds', '7200', '--seed-queries', '16', '--seed-dp-seconds', '120',
                '--eval-timeout', '1800', '--toy-queries', '64', '--toy-seconds', '600'])
            for model in ('resnet18', 'resnet50', 'mobilenet_v2'):
                execute('paired_' + model, py + [str(snapshot / 'scripts/run_single_array_counterfactual.py'),
                    '--snapshot', str(snapshot), '--run', str(out / 'results' / model / 'fusion_on'),
                    '--out', str(out / ('counterfactual_' + model)), '--seconds', '3600', '--eval-timeout', '1800'])
            execute('audit', py + [str(snapshot / 'scripts/audit_single_array_results.py'), '--root', str(out)])
            status['status'] = 'completed'
        except Exception as error:
            status.update(status='failed', error=str(error))
            raise
        finally:
            status['updated_unix'] = time.time()
            atomic_json(status_path, status)
            if power: power(0x80000000)


if __name__ == '__main__': main()
