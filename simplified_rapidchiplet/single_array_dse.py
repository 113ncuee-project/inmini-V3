"""INMIN v0.2 text-only, checkpointed experiment entry point.

Example: python single_array_dse.py --model toy --queries 32 --seconds 120
Large models are explicitly selected. Common validated seeds are shared by
all methods; full evaluations, rejected oracle attempts and exports are kept
as separate ledgers. The source manifest must match on resume.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
import gzip
from collections import defaultdict
import os
from pathlib import Path
import sys
import time
from statistics import median
from types import SimpleNamespace

from simple_rapidchiplet.hybrid.auto_runtime import atomic_json
from simple_rapidchiplet.hybrid.mapping import initial_mapping
from simple_rapidchiplet.hybrid.rl_actions import apply_transaction
from simple_rapidchiplet.hybrid.rl_schema import DesignState, stable_hash
from simple_rapidchiplet.hybrid.rl_search import JointObjective, JointSearchConfig, run_joint_search
from simple_rapidchiplet.hybrid.single_array_hardware import PROFILE, enumerate_single_array_architectures
from simple_rapidchiplet.hybrid.single_array_proposals import SingleArrayJointProposals
from simple_rapidchiplet.hybrid.single_array_runtime import SingleArrayOraclePool
from simple_rapidchiplet.hybrid.single_array_seed import generate_single_array_seeds
from simple_rapidchiplet.hybrid.workload import make_toy_workload


ARMS = {'random': ('random', 'composite'), 'greedy': ('greedy', 'composite'),
        'atomic_rl': ('rl', 'atomic'), 'bottleneck_rl': ('rl', 'composite')}


@contextmanager
def exclusive_run(folder):
    """An OS-released file lock prevents duplicate jobs after heartbeat wakes."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'run.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def source_identity(workload, candidates):
    root = Path(__file__).resolve().parent
    sources = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted((root / 'simple_rapidchiplet' / 'hybrid').glob('*.py'))}
    sources[Path(__file__).name] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for relative in ('gui_request.py', 'gui_request_v3.py', 'single_array_gui.py', 'hybrid_gui.py', 'gui/app.js', 'gui/index.html'):
        path = root / relative
        if path.exists():
            sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    deps = {}
    for name in ('numpy', 'torch', 'torchvision'):
        try:
            deps[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            deps[name] = 'not_installed'
    data = {'sources': sources, 'workload': workload.fingerprint, 'model_source': workload.source,
            'hardware': {c.id: c.hardware.fingerprint for c in candidates},
            'python': sys.version, 'dependencies': deps, 'profile_id': PROFILE}
    return {**data, 'identity': stable_hash(data)}


def scalar_metrics(metrics):
    return {key: metrics.get(key) for key in ('feasible', 'latency_s', 'area_mm2', 'power_w', 'energy_j',
        'compute_chiplets', 'io_chiplets', 'executed_macs', 'recompute_macs', 'dram_read_bytes',
        'dram_write_bytes', 'noc_hop_bytes', 'nop_hop_bytes', 'unit_count', 'violations',
        'architecture_candidate_id', 'l1_l2_service_bytes', 'compute_utilization')}


def export_search_evidence(folder, result, pool, seed_data, candidates):
    checkpoint = json.loads((folder / 'checkpoint.json').read_text(encoding='utf-8'))
    diagnostics = [{'state_hash': metrics.get('design_state_hash'), 'feasible': metrics.get('feasible'),
                    'diagnostics': metrics['diagnostics']} for metrics in checkpoint['cache'].values()
                   if metrics.get('diagnostics')]
    atomic_json(folder / 'bottleneck_trace.json', diagnostics)
    depths = defaultdict(lambda: {'joint_attempted': 0, 'joint_structural_rejected': 0,
        'shortlisted_fusion_merge': 0, 'policy_selected_fusion_merge': 0,
        'completed_full_PPA': 0, 'completed_feasible_PPA': 0, 'observed_successful_compile': 0,
        'positive_selected_reward': 0, 'in_best_archive': 0})
    for history in checkpoint.get('proposal_extension_state', {}).get('history', ()):
        for attempt in history.get('attempts', ()):
            depth = attempt['depth']
            depths[depth]['joint_attempted'] += 1
            depths[depth]['joint_structural_rejected'] += int(attempt.get('status') != 'structurally_legal_physical_check_pending')
    for row in result.trace:
        for edit in row['action_plan']['ordered_edits']:
            if edit['action_id'] == 'A1' and edit['parameters'].get('operation', 'merge') == 'merge':
                depths[len(edit['parameters']['layer_ids'])]['policy_selected_fusion_merge'] += 1
        if row['valid'] and row['reward'] > 0:
            for stack in row['current_metrics'].get('diagnostics', {}).get('fusion', ()):
                depths[len(stack['layers'])]['positive_selected_reward'] += 1
    for path in (folder / 'shortlists').glob('*.json.gz'):
        for plan in json.loads(gzip.decompress(path.read_bytes()))['plans']:
            for edit in plan['ordered_edits']:
                if edit['action_id'] == 'A1' and edit['parameters'].get('operation', 'merge') == 'merge':
                    depths[len(edit['parameters']['layer_ids'])]['shortlisted_fusion_merge'] += 1
    for record in pool.records:
        if record['operation'] != 'evaluate':
            continue
        for depth in set(record.get('fusion_depths', ())):
            if record.get('full_evaluations'):
                depths[depth]['completed_full_PPA'] += 1
                depths[depth]['completed_feasible_PPA'] += int(record.get('ppa_feasible', False))
        for depth in set(record.get('compile_evidence', {}).get('fusion_depths', ())):
            depths[depth]['observed_successful_compile'] += 1
    if result.best_state:
        for stack in result.best_state.mapping.fusion_stacks:
            depths[len(stack.layer_ids)]['in_best_archive'] += 1
    atomic_json(folder / 'fusion_coverage.json', {'depths': dict(depths),
        'max_observed_compiled_depth': max((d for d, row in depths.items() if row['observed_successful_compile']), default=0),
        'max_full_evaluated_depth': max((d for d, row in depths.items() if row['completed_full_PPA']), default=0),
        'scope': 'new merge proposals and actual state depths counted separately; no artificial proxy PPA; not-selected or untested is not a DF loss'})
    coverage = []
    for candidate in candidates:
        seeds = [row for row in seed_data['attempts'] if row['architecture'] == candidate.id]
        records = [row for row in pool.records if row.get('architecture') == candidate.id and row['operation'] == 'evaluate']
        coverage.append({'architecture': candidate.id, 'seed_full_completed': sum(bool(row.get('ppa_completed')) for row in seeds),
            'search_full_completed': sum(row.get('full_evaluations', 0) for row in records),
            'search_feasible_completed': sum(bool(row.get('ppa_feasible')) for row in records),
            'timeouts': sum(row.get('status') == 'timeout' for row in records),
            'status': 'full_evaluated' if any(row.get('ppa_completed') for row in seeds) or any(row.get('full_evaluations') for row in records)
                      else 'attempted_without_complete_PPA' if records or seeds else 'not_evaluated_due_to_budget'})
    atomic_json(folder / 'architecture_coverage.json', coverage)


def run(args, *, objective_override=None, requested_ui=None, update=lambda **_: None):
    folder = Path(args.out).resolve()
    with exclusive_run(folder):
        started = time.monotonic()
        if args.model == 'toy':
            workload = make_toy_workload(batch=1, channels=5, spatial=7)
        else:
            from simple_rapidchiplet.hybrid.models import extract_model
            workload = extract_model(args.model, batch_size=1, input_size=args.input_size)
        candidates = enumerate_single_array_architectures()
        lookup = {c.id: c for c in candidates}
        identity = source_identity(workload, candidates)
        source_path = folder / 'source_identity.json'
        if source_path.exists():
            if not args.resume:
                raise ValueError('output exists; use --resume with identical sources, or a new output directory')
            if json.loads(source_path.read_text(encoding='utf-8'))['identity'] != identity['identity']:
                raise ValueError('resume rejected: source/model/hardware identity changed')
        else:
            atomic_json(source_path, identity)
        atomic_json(folder / 'workload.json', workload.to_dict())
        from rl_dse import make_objective
        objective = objective_override or make_objective({'preference': args.preference,
            'max_power': args.max_power, 'max_area': args.max_area, 'max_latency_ms': args.max_latency_ms,
            'strict_power': not args.soft_limits, 'strict_area': not args.soft_limits, 'strict_latency': not args.soft_limits})
        effective = {**vars(args), 'hardware_profile': PROFILE, 'batch_size': 1, 'horizon': 12,
                     'render_images': False, 'objective': asdict(objective),
                     'full_query_ceiling_per_arm_including_common_seeds': args.queries,
                     'wall_ceiling_per_arm_including_common_seed_charge_s': args.seconds,
                     'wall_extension_reason': 'user authorized evidence-driven extension beyond 1800s' if args.seconds > 1800 else None,
                     'query_accounting': 'completed full PPA includes capacity-invalid schedules; compiler rejections and timeouts separate; all consume wall time',
                     'seed_method': args.seed_method}
        effective['seed_full_query_ceiling'] = min(args.queries, max(1, min(8, math.ceil(args.queries * .20))))
        config_path = folder / 'effective_config.json'
        if config_path.exists() and args.resume:
            saved_config = json.loads(config_path.read_text(encoding='utf-8'))
            if any(saved_config.get(key) != value for key, value in effective.items() if key not in ('resume',)):
                raise ValueError('resume rejected: experiment settings changed; use a new output directory')
        atomic_json(config_path, effective)
        atomic_json(folder / 'requested_ui.json', requested_ui or {'model': args.model, 'preference': args.preference,
            'limits': {key: getattr(args, key) for key in ('max_power', 'max_area', 'max_latency_ms')},
            'report': 'text_numeric_tables_only'})
        atomic_json(folder / 'hardware_profile.json', {c.id: c.hardware.to_dict() for c in candidates})
        def make_state(candidate, mapping):
            obj = asdict(objective)
            return DesignState(candidate.id, mapping, workload.fingerprint, PROFILE, version=2,
                preferences={key: obj[key] for key in ('latency_weight', 'area_weight', 'power_weight', 'energy_weight')},
                constraints={key: value for key, value in obj.items() if key.startswith(('max_', 'soft_'))},
                workload_definition={'batch_size': 1, 'model': workload.name, 'source': workload.source})
        seed_file = folder / 'seed_attempts.json'
        seed_data = json.loads(seed_file.read_text(encoding='utf-8')) if seed_file.exists() else {'attempts': [], 'bootstrap': [], 'elapsed_s': time.monotonic() - started}
        bootstrap = [(DesignState.from_dict(row['state']), row['metrics']) for row in seed_data['bootstrap']]
        attempted = {row['state_hash'] for row in seed_data['attempts']}
        # One square-ish rectangle per scale. All fifteen remain reachable by
        # A9; omitted seed rectangles are recorded, never reported searched.
        seed_candidates = [min([c for c in candidates if c.hardware.compute_count == count],
                               key=lambda c: (abs(c.hardware.rows - c.hardware.cols), c.hardware.rows))
                           for count in (1, 2, 4, 8, 16)]
        seed_deadline = time.monotonic() + max(.1, args.seconds * .20 - seed_data['elapsed_s'])
        pool = SingleArrayOraclePool(workload, folder / 'seed_worker', deadline=seed_deadline,
                                     evaluation_timeout_s=args.eval_timeout)
        phase_start = time.monotonic()
        seed_proposals = {}
        for candidate in seed_candidates:
            if args.seed_method == 'tangram_style_v02':
                seed_proposals[candidate.id] = generate_single_array_seeds(workload, candidate.hardware,
                    max_candidates=3, timeout_s=min(3., max(.01, seed_deadline - time.monotonic())))
            else:
                seed_proposals[candidate.id] = ()
        # Preserve a known baseline, add a DP proposal at small scales, then
        # cover larger scales. Budget-truncated scales/proposals remain visible.
        planned = []
        for candidate in seed_candidates:
            proposals = seed_proposals[candidate.id]
            baseline = proposals[0].plan if proposals else initial_mapping(workload, candidate.package.mapping_core_ids,
                candidate.package.memory_ids, max_group_layers=1)
            planned.append((candidate, baseline, proposals[0].to_dict() if proposals else {'provenance': {'source': 'integer_stripes'}}))
            if candidate.hardware.compute_count <= 2 and len(proposals) > 1:
                planned.append((candidate, proposals[1].plan, proposals[1].to_dict()))
        for candidate in seed_candidates:
            for proposal in seed_proposals[candidate.id][2 if candidate.hardware.compute_count <= 2 else 1:]:
                planned.append((candidate, proposal.plan, proposal.to_dict()))
        atomic_json(folder / 'seed_proposals.json', [{'architecture': c.id, 'state_hash': make_state(c, p).fingerprint,
            'proposal': evidence} for c, p, evidence in planned])
        try:
            for candidate, mapping, proposal_evidence in planned:
                state = make_state(candidate, mapping)
                if state.fingerprint in attempted:
                    continue
                if pool.full_evaluations >= effective['seed_full_query_ceiling']:
                    break
                if time.monotonic() >= seed_deadline:
                    break
                update(message=f'{workload.name}: validating seed {candidate.id}')
                tick = time.monotonic()
                attempt = {'architecture': candidate.id, 'state_hash': state.fingerprint, 'status': 'attempting',
                           'proposal_provenance': proposal_evidence.get('provenance')}
                try:
                    result = pool.evaluate(candidate, mapping, phase='seed')
                    metrics = result['metrics']
                    attempt.update(status='full_completed', ppa_completed=True, metrics=scalar_metrics(metrics))
                    if metrics['feasible']:
                        bootstrap.append((state, metrics))
                        archive = folder / 'verified' / state.fingerprint
                        try:
                            pool.persist(candidate, mapping, archive, effective)
                            metrics['verified_artifact'] = str(archive)
                            attempt['detailed_export_status'] = 'completed'
                        except (ValueError, RuntimeError, TimeoutError) as error:
                            attempt['detailed_export_status'] = 'failed_after_complete_PPA'
                            attempt['detailed_export_error'] = str(error)
                except (ValueError, RuntimeError, TimeoutError) as error:
                    attempt.update(status='timeout' if isinstance(error, TimeoutError) else 'rejected', reason=str(error))
                attempt['elapsed_s'] = time.monotonic() - tick
                seed_data['attempts'].append(attempt)
                attempted.add(state.fingerprint)
                seed_data['bootstrap'] = [{'state': s.to_dict(), 'metrics': m} for s, m in bootstrap]
                seed_data['elapsed_s'] += time.monotonic() - phase_start
                phase_start = time.monotonic()
                atomic_json(seed_file, seed_data)
        finally:
            pool.close()
            seed_data['elapsed_s'] += time.monotonic() - phase_start
            atomic_json(seed_file, seed_data)
        coverage = []
        for candidate in candidates:
            attempts = [row for row in seed_data['attempts'] if row['architecture'] == candidate.id]
            status = ('full_completed_executable_seed' if any(row.get('metrics', {}).get('feasible') for row in attempts)
                      else 'full_completed_no_executable_seed' if any(row.get('ppa_completed') for row in attempts)
                      else 'attempted_without_complete_PPA' if attempts
                      else 'not_evaluated_due_to_budget' if candidate in seed_candidates else 'not_selected_for_seed')
            coverage.append({**candidate.to_dict(), 'seed_status': status, 'attempt_count': len(attempts),
                             'completed_full_PPA': sum(bool(row.get('ppa_completed')) for row in attempts)})
        atomic_json(folder / 'architecture_coverage.json', coverage)
        if not bootstrap:
            atomic_json(folder / 'run_state.json', {'status': 'no_completed_executable_seed', 'pid': os.getpid(),
                                                   'elapsed_s': time.monotonic() - started})
            raise RuntimeError('no completed executable v0.2 seed; inspect seed_attempts, not a claim that no feasible hardware exists')
        # One shared reference across all methods. The initial state is the best
        # fully evaluated seed under that fixed reference, not bootstrap[0].
        reference = bootstrap[0][1]
        initial, _ = min(bootstrap, key=lambda row: objective.penalized_cost(row[1], reference))
        bootstrap.sort(key=lambda row: row[0].fingerprint != initial.fingerprint)
        initial_cost = objective.cost(next(m for s, m in bootstrap if s.fingerprint == initial.fingerprint), reference)
        seed_full = pool.full_evaluations
        summaries = {}
        for arm in args.arms.split(','):
            arm_folder = folder / arm
            result_file = arm_folder / 'joint_search.json'
            if result_file.exists() and args.resume:
                result = json.loads(result_file.read_text(encoding='utf-8'))
                summaries[arm] = result['summary']
                continue
            atomic_json(folder / 'run_state.json', {'status': 'running', 'arm': arm, 'pid': os.getpid(),
                                                   'elapsed_s': time.monotonic() - started})
            checkpoint = arm_folder / 'checkpoint.json'
            prior_elapsed = json.loads(checkpoint.read_text(encoding='utf-8')).get('elapsed_s', 0.) if args.resume and checkpoint.exists() else 0.
            search_ceiling = max(.1, args.seconds - seed_data['elapsed_s'])
            remaining = max(.1, search_ceiling - prior_elapsed)
            deadline = time.monotonic() + remaining
            pool = SingleArrayOraclePool(workload, arm_folder / 'worker', deadline=deadline,
                                         evaluation_timeout_s=args.eval_timeout)
            # Reserve reporting time proportionally, bounded for short smoke.
            reserve = min(60., max(1., remaining * .05))
            pool.deadline = deadline - reserve
            best_saved = [min(objective.cost(m, reference) for _, m in bootstrap if objective.strict_feasible(m))
                          if any(objective.strict_feasible(m) for _, m in bootstrap) else float('inf')]
            def recent_full_cost():
                recent = [row.get('evaluation_elapsed_s', row.get('elapsed_s', 0.)) for row in pool.records
                          if row['operation'] == 'evaluate' and row.get('full_evaluations')]
                return median(recent[-5:]) if recent else median(
                    [row['elapsed_s'] for row in seed_data['attempts'] if row.get('ppa_completed')] or [.01])
            def factory(candidate):
                def evaluate(mapping):
                    if seed_full + pool.full_evaluations >= args.queries:
                        raise TimeoutError('completed full-query ceiling reached')
                    estimate = recent_full_cost()
                    if pool.deadline - time.monotonic() < estimate:
                        raise TimeoutError('insufficient remaining time for a recent complete oracle cost plus report reserve')
                    response = pool.evaluate(candidate, mapping, phase='search')
                    metrics = response['metrics']
                    update(message=f'{workload.name}: completed PPA {seed_full + pool.full_evaluations}/{args.queries}',
                           current_model=args.model, model_remaining_wall_s=max(0., deadline - time.monotonic()))
                    state = make_state(candidate, mapping)
                    if objective.strict_feasible(metrics) and objective.cost(metrics, reference) < best_saved[0]:
                        best_saved[0] = objective.cost(metrics, reference)
                        archive = folder / 'verified' / state.fingerprint
                        try:
                            pool.persist(candidate, mapping, archive, effective)
                            metrics['verified_artifact'] = str(archive)
                        except (ValueError, RuntimeError, TimeoutError) as error:
                            metrics['detailed_export_status'] = 'failed_after_complete_PPA'
                            metrics['detailed_export_error'] = str(error)
                    return metrics
                return evaluate
            method, proposal = ARMS[arm]
            config = JointSearchConfig(seed=args.seed, budget=max(32, args.queries * 8), max_steps=max(32, args.queries * 8),
                horizon=12, shortlist=args.shortlist, random_quota=min(12, args.shortlist // 2),
                method=method, proposal=proposal, checkpoint_every=1, fusion_enabled=args.fusion != 'off',
                max_wall_time_s=max(.001, search_ceiling - reserve))
            hook = SingleArrayJointProposals(workload, candidates, shortlist=args.shortlist,
                fusion_enabled=args.fusion != 'off') if proposal == 'composite' else None
            if hook:
                hook.deadline = pool.deadline
            def guard(_):
                if time.monotonic() >= pool.deadline:
                    return 'wall_time_budget_exhausted'
                if seed_full + pool.full_evaluations >= args.queries:
                    return 'full_query_budget_exhausted'
                if pool.deadline - time.monotonic() < recent_full_cost():
                    return 'insufficient_oracle_time_budget_exhausted'
                return None
            try:
                result = run_joint_search(workload, initial, candidates, factory, objective=objective,
                    config=config, checkpoint_path=checkpoint, resume=args.resume and checkpoint.exists(),
                    evaluator_identity=identity['identity'], bootstrap_evaluations=bootstrap,
                    proposal_hook=hook, resource_guard=guard, reference_metrics=reference)
                data = result.to_dict()
                best = result.best_metrics
                summary = {'status': result.status, 'full_ppa_completed': seed_full + pool.full_evaluations,
                    'common_seed_full_ppa': seed_full, 'search_full_ppa': pool.full_evaluations,
                    'oracle_miss_attempts': result.evaluations + getattr(result, 'oracle_timeouts', 0),
                    'oracle_completed_misses': result.evaluations, 'oracle_timeouts': getattr(result, 'oracle_timeouts', 0),
                    'cache_hits': data['cache_hits'], 'policy_updates': result.policy_updates,
                    'wall_s_including_common_seed_charge': seed_data['elapsed_s'] + result.elapsed_s,
                    'strict_feasible': bool(best), 'best_cost': result.best_cost,
                    'best': scalar_metrics(best) if best else None,
                    'improvement_over_best_seed_pct': (1 - result.best_cost / initial_cost) * 100 if best else None,
                    'limitations': 'one seed, analytical model, bounded Tangram-style DP/stripes; no global-optimality or statistically established RL advantage'}
                data['summary'] = summary
                atomic_json(result_file, data)
                export_search_evidence(arm_folder, result, pool, seed_data, candidates)
                atomic_json(arm_folder / 'verified_archive.json', result.architecture_archive)
                atomic_json(arm_folder / 'recommendation.json', {'state': result.best_state.to_dict() if result.best_state else None, 'metrics': best})
                summaries[arm] = summary
                atomic_json(folder / 'summary.json', summaries)
            finally:
                pool.close()
        final_identity = source_identity(workload, candidates)
        if final_identity['identity'] != identity['identity']:
            raise RuntimeError('sources changed during experiment; results must not be compared as a frozen-source suite')
        lines = ['# INMIN v0.2 實驗結果（文字／數字表格）', '',
            '本次是分析模型的有限預算驗證；Tangram-style 為本專案的有界 DP/beam adapter，未執行原始 Tangram。不代表晶片實測、全域最佳或統計上確立 RL 優勢。', '',
            '|方法|已完成 PPA（含共用種子）|Policy 更新|最佳成本|相對最佳種子改善 %|Latency µs|Area mm²|Power W|',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for arm, row in summaries.items():
            b = row['best'] or {}
            if b:
                lines.append(f"|{arm}|{row['full_ppa_completed']}|{row['policy_updates']}|{row['best_cost']:.6f}|{row['improvement_over_best_seed_pct']:.3f}|{b['latency_s']*1e6:.6f}|{b['area_mm2']:.6f}|{b['power_w']:.6f}|")
            else:
                lines.append(f"|{arm}|{row['full_ppa_completed']}|{row['policy_updates']}|not_feasible|—|—|—|—|")
        lines.extend(['', '|方法|Compute|IO|執行 MAC|重算 MAC|DRAM 讀 B|DRAM 寫 B|NoC hop-B|NoP hop-B|Units|',
                      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
        for arm, row in summaries.items():
            b = row['best']
            if b:
                lines.append('|' + '|'.join(str(value) for value in (arm, b['compute_chiplets'], b['io_chiplets'],
                    b['executed_macs'], b['recompute_macs'], b['dram_read_bytes'], b['dram_write_bytes'],
                    b['noc_hop_bytes'], b['nop_hop_bytes'], b['unit_count'])) + '|')
        if set(summaries) == set(ARMS) and all(row['full_ppa_completed'] == args.queries for row in summaries.values()):
            bottle = summaries['bottleneck_rl']['best_cost']
            others = [summaries[arm]['best_cost'] for arm in ARMS if arm != 'bottleneck_rl']
            if bottle is not None and all(value is not None for value in others):
                comparison = ('優於三個對照' if bottle < min(others) - 1e-9 else
                              '與最佳對照持平' if abs(bottle - min(others)) <= 1e-9 else '未優於最佳對照')
                lines.extend(['', f'本 Seed、相同已完成 PPA 查詢數與共同時間上限下，bottleneck-aware RL {comparison}。這不是跨 Seed 的統計保證。'])
        else:
            lines.extend(['', '四方法尚未全部達成相同完整 PPA 查詢數；保留實際查詢與時間，不宣稱已證明演算法優劣。'])
        if 'bottleneck_rl' in summaries:
            gain = summaries['bottleneck_rl']['improvement_over_best_seed_pct']
            if gain is not None:
                lines.extend(['', f'RL 相對最佳已驗證 Seed 的改善為 {gain:.4f}%。Seed 本身的收益不歸功於 RL。'])
        for arm in summaries:
            recommendation = json.loads((folder / arm / 'recommendation.json').read_text(encoding='utf-8'))
            state = recommendation.get('state')
            if not state:
                continue
            mapping = state['mapping']
            layer_group = {lid: index for index, group in enumerate(mapping['groups']) for lid in group['layer_ids']}
            fusion = {lid: stack for stack in mapping['fusion_stacks'] for lid in stack['layer_ids']}
            lines.extend(['', f'{arm} 最佳硬體：{state["architecture_candidate_id"]}。每個 Compute 固定 16 PE、共享 1MiB L2，沒有實體 Core。', '',
                          '|Layer|Group|PE 配額|B,K,H,W|DF depth|Sink tile|Cache|輸入／權重／輸出 DRAM|',
                          '|---|---:|---:|---|---:|---|---|---|'])
            for item in mapping['layer_mappings']:
                stack = fusion.get(item['layer_id'])
                part = item['partition']
                lines.append('|' + '|'.join(str(value) for value in (item['layer_id'], layer_group[item['layer_id']],
                    len(item['chiplets']), ','.join(str(part[key]) for key in ('b', 'k', 'h', 'w')),
                    len(stack['layer_ids']) if stack else 0, stack['tile_hw'] if stack else '—',
                    stack['overlap'] if stack else '—', '/'.join(item[key] for key in ('input_dram', 'weight_dram', 'output_dram')))) + '|')
        lines.extend(['', '完整帳本、來源、逐步交易與未評估架構保存在同目錄 JSON；不同完成查詢數／牆鐘截斷不能直接宣稱公平勝出。',
                      '共同 Seed 的已完成 PPA 與耗時對每個方法計費一次；實際唯一 backend 工作量為 Seed worker 加各方法 worker 帳本之和，不將共用 Seed 重複宣稱為實際執行。',
                      '完整且有順序的每層 PE IDs 見 recommendation.json；所有 shortlist 的完整 ordered edits 保存在 gzip JSON，避免把未被選中誤稱為已落敗。',
                      'v0.2 使用新的 Python 顯式網路與資源 calendar evaluator；本新 engine 未執行 native RapidChiplet backend。',
                      '資料型別與面積／功耗係數為明列的研究假設；片內採暫行 4×4 PE mesh、四個 L2 gateway。Whole-flow reservation 保守地一起保留通路與端點資源，可能低估可重疊程度；未提供 packet/VC cycle timing、SRAM bank-address 衝突、量化準確率或晶片量測校準。'])
        (folder / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        atomic_json(folder / 'run_state.json', {'status': 'completed', 'pid': os.getpid(),
                                               'elapsed_s': time.monotonic() - started, 'source_stable': True})
        print(json.dumps(summaries, ensure_ascii=False))
        return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=('toy', 'resnet18', 'resnet50', 'mobilenet_v2'), default='toy')
    parser.add_argument('--input-size', type=int, default=224)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--preference', choices=('balanced', 'low_power', 'small_area', 'low_latency'), default='balanced')
    parser.add_argument('--max-power', type=float)
    parser.add_argument('--max-area', type=float)
    parser.add_argument('--max-latency-ms', type=float)
    parser.add_argument('--soft-limits', action='store_true')
    parser.add_argument('--seed-method', choices=('stripes', 'tangram_style_v02'), default='tangram_style_v02')
    parser.add_argument('--queries', type=int, default=32)
    parser.add_argument('--seconds', type=float, default=1800.)
    parser.add_argument('--eval-timeout', type=float, default=180.)
    parser.add_argument('--shortlist', type=int, default=48)
    parser.add_argument('--fusion', choices=('on', 'off'), default='on')
    parser.add_argument('--arms', default=','.join(ARMS))
    parser.add_argument('--out', default='../output/inmin_v02_20261101/toy_development')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.queries < 6 or args.seconds < 10 or args.eval_timeout <= 0 or args.shortlist < 4 or any(arm not in ARMS for arm in args.arms.split(',')):
        parser.error('queries>=6, seconds>=10, positive timeout, shortlist>=4 and known arms required')
    run(args)


if __name__ == '__main__':
    main()
