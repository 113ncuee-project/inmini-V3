"""Isolated, deadline-bounded v0.2 oracle; reports are JSON/text only."""
from dataclasses import asdict
from pathlib import Path
import json
import hashlib
import os
import pickle
import subprocess
import sys
import time

from .auto_runtime import BoundedOraclePool, EvaluationTimeout, atomic_json


class SingleArrayOraclePool(BoundedOraclePool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ledger = self.folder / 'accounting.json'
        if ledger.exists():
            self.records = json.loads(ledger.read_text(encoding='utf-8'))
            self.full_evaluations = sum(row.get('full_evaluations', 0) for row in self.records)
            self.cache_hits = sum(row.get('cache_hits', 0) for row in self.records)

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        app = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env['PYTHONPATH'] = str(app) + os.pathsep + env.get('PYTHONPATH', '')
        self.log = (self.folder / 'worker.log').open('ab')
        self.process = subprocess.Popen([sys.executable, '-u', '-m', __name__, '--worker', str(self.folder)],
            cwd=app, env=env, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def evaluate(self, candidate, plan, *, deadline=None, phase='rl'):
        end = min(self.deadline, deadline if deadline is not None else self.deadline)
        index = len(self.records)
        try:
            result = self.request('evaluate', deadline=end, architecture=candidate.id,
                hardware=asdict(candidate.hardware), hardware_profile=candidate.hardware.profile_id, mapping=plan.to_dict(), phase=phase,
                worker_timeout_s=min(self.evaluation_timeout_s, max(0., end - time.monotonic())))
            if len(self.records) > index:
                self.records[index]['ppa_feasible'] = result['metrics']['feasible']
            return result
        except (ValueError, RuntimeError, TimeoutError) as error:
            if len(self.records) > index:
                self.records[index]['error'] = str(error)
                if isinstance(error, TimeoutError) or str(error).startswith('TimeoutError:'):
                    self.records[index]['status'] = 'timeout'
            if str(error).startswith('TimeoutError:'):
                raise EvaluationTimeout(str(error)) from error
            raise
        finally:
            if len(self.records) > index:
                mapping_hash = hashlib.sha256(json.dumps(plan.to_dict(), sort_keys=True).encode()).hexdigest()
                self.records[index].update(mapping_hash=mapping_hash,
                                           fusion_depths=[len(stack.layer_ids) for stack in plan.fusion_stacks])
                evidence_file = self.folder / 'compile_evidence.json'
                if evidence_file.exists():
                    try:
                        evidence = json.loads(evidence_file.read_text(encoding='utf-8'))
                        if evidence.get('mapping_hash') == mapping_hash and evidence.get('architecture') == candidate.id:
                            self.records[index]['compile_evidence'] = evidence['evidence']
                    except (OSError, ValueError):
                        self.records[index]['compile_evidence_status'] = 'unavailable'
                atomic_json(self.folder / 'accounting.json', self.records)


def worker(folder):
    from .search import plan_from_dict
    from .single_array_evaluator import SingleArrayEvaluator
    from .single_array_hardware import ExperimentalAssumptions, SingleArrayHardware, SingleArrayHardwareV3, PROFILE_V3
    folder = Path(folder)
    with (folder / 'workload.pkl').open('rb') as stream:
        workload = pickle.load(stream)
    atomic_json(folder / 'worker_started.json', {'worker_pid': os.getpid(), 'parent_pid': os.getppid()})
    evaluators, last = {}, None
    for line in sys.stdin.buffer:
        req, started = json.loads(line), time.monotonic()
        full = hits = 0
        try:
            key = req['architecture']
            plan = plan_from_dict(req['mapping'])
            if req['operation'] == 'evaluate':
                if key not in evaluators:
                    data = dict(req['hardware'])
                    a = dict(data.pop('assumptions'))
                    a['l2_gateway_pes'] = tuple(a['l2_gateway_pes'])
                    a['vector_cycles_per_element'] = tuple(tuple(row) for row in a['vector_cycles_per_element'])
                    data['assumptions'] = ExperimentalAssumptions(**a)
                    hardware_class = SingleArrayHardwareV3 if req.get('hardware_profile') == PROFILE_V3 else SingleArrayHardware
                    evaluators[key] = SingleArrayEvaluator(workload, hardware_class(**data))
                oracle = evaluators[key]
                mapping_hash = hashlib.sha256(json.dumps(req['mapping'], sort_keys=True).encode()).hexdigest()
                oracle.compile_hook = lambda evidence: atomic_json(folder / 'compile_evidence.json',
                    {'architecture': key, 'mapping_hash': mapping_hash, 'evidence': evidence})
                oracle.deadline = started + req['worker_timeout_s']
                before, old_hits = oracle.evaluations, oracle.cache_hits
                result = oracle(plan)
                full, hits = oracle.evaluations - before, oracle.cache_hits - old_hits
                last = (key, req['mapping'], result, oracle)
                for item in evaluators.values():
                    item.cache.clear()
                value = {'metrics': result.metrics}
            elif req['operation'] == 'persist':
                if last is None or last[:2] != (key, req['mapping']):
                    raise ValueError('persist requires the last completed exact evaluation')
                _, _, result, oracle = last
                target = Path(req['folder'])
                compact = oracle.hardware.profile_id == PROFILE_V3
                artifact = ({'metrics': result.metrics, 'mapping': result.compiled.plan.to_dict(),
                    'buffer_statistics': result.buffer_statistics, 'diagnostics': result.metrics['diagnostics'],
                    'detail_scope': 'compact export; bounded diagnostics; full calendar was evaluated'} if compact else result.to_dict())
                atomic_json(target / 'evaluation.json', artifact)
                atomic_json(target / 'hardware_profile.json', oracle.hardware.to_dict())
                atomic_json(target / 'workload.json', workload.to_dict())
                atomic_json(target / 'config.json', req['config'])
                value = {'folder': str(target), 'metrics': result.metrics}
            else:
                raise ValueError('unknown v0.2 operation')
            atomic_json(req['response'], {'status': 'complete', 'full_evaluations': full, 'cache_hits': hits,
                'evaluation_elapsed_s': time.monotonic() - started, **value})
        except Exception as exc:
            atomic_json(req['response'], {'status': 'error', 'error_type': type(exc).__name__,
                'error': f'{type(exc).__name__}: {exc}', 'full_evaluations': full, 'cache_hits': hits,
                'evaluation_elapsed_s': time.monotonic() - started})


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('internal worker entry only')
    worker(sys.argv[2])
