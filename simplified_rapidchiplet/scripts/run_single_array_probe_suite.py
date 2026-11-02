"""Sequential representative-model pipeline probes, with a persistent ledger.

These short probes validate the oracle and accounting, not RL effectiveness.
The formal fair algorithm comparisons follow after the remaining integration.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root.parent / 'output' / 'inmin_v02_20261101' / 'pipeline_probes_v3'
    folder.mkdir(parents=True, exist_ok=True)
    ledger = folder / 'suite_status.json'
    rows = json.loads(ledger.read_text(encoding='utf-8'))['models'] if ledger.exists() else []
    from_paths = [row['model'] for row in rows if row['status'] in ('completed', 'failed')]
    for model in ('resnet18', 'resnet50', 'mobilenet_v2'):
        if model in from_paths:
            continue
        row = {'model': model, 'status': 'running', 'started_unix': time.time()}
        rows.append(row)
        command = [sys.executable, '-X', 'utf8', str(root / 'single_array_dse.py'),
                   '--model', model, '--queries', '8', '--seconds', '600', '--eval-timeout', '150',
                   '--arms', 'bottleneck_rl', '--out', str(folder / model)]
        with (folder / (model + '.log')).open('ab') as log:
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            row['pid'] = process.pid
            ledger.write_text(json.dumps({'status': 'running', 'owner_pid': os.getpid(), 'models': rows}, indent=2), encoding='utf-8')
            code = process.wait()
        row.update(status='completed' if code == 0 else 'failed', return_code=code,
                   elapsed_s=time.time() - row['started_unix'])
        ledger.write_text(json.dumps({'status': 'running', 'owner_pid': os.getpid(), 'models': rows}, indent=2), encoding='utf-8')
    ledger.write_text(json.dumps({'status': 'completed', 'owner_pid': os.getpid(), 'models': rows}, indent=2), encoding='utf-8')
    print(json.dumps(rows))


if __name__ == '__main__':
    main()
