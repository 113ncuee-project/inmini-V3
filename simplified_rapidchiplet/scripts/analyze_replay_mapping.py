"""Audit v0.4 physical ledgers and report policy evidence without extra PPA.

Held-out control-arm trials never train the RL model. Their measured utilities
test prediction ordering; this is not an off-policy estimate of search wins.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from replay_mapping_dse import cost
from simple_rapidchiplet.hybrid.rl_schema import DesignState
from simple_rapidchiplet.hybrid.replay_q import ReplayQ


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line] if path.exists() else []


def close(a, b):
    return math.isclose(a, b, rel_tol=2e-7, abs_tol=1e-12)


def ranks(values):
    values = np.asarray(values)
    order = np.argsort(values, kind='stable')
    result = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        result[order[start:end]] = (start + end - 1) / 2
        start = end
    return result


def ranking_metrics(predicted, actual):
    predicted, actual = np.asarray(predicted), np.asarray(actual)
    if len(actual) < 3:
        return {'n': len(actual), 'status': 'insufficient_unseen_trials'}
    a, b = ranks(predicted), ranks(actual)
    rho = float(np.corrcoef(a, b)[0, 1]) if np.std(a) and np.std(b) else None
    pairs = [(i, j) for i in range(len(actual)) for j in range(i) if abs(actual[i]-actual[j]) > 1e-9]
    concordance = sum(.5 if predicted[i] == predicted[j] else float((predicted[i]-predicted[j])*(actual[i]-actual[j]) > 0) for i, j in pairs) / len(pairs) if pairs else None
    selected = np.argsort(predicted)[-max(1, math.ceil(len(actual)/4)):]
    return dict(n=len(actual), spearman=rho, pairwise_concordance=concordance,
                mse=float(np.mean((predicted-actual)**2)),
                selected_top_quartile_mean_utility=float(np.mean(actual[selected])),
                all_mean_utility=float(np.mean(actual)))


def physical_errors(metrics, initial):
    errors = []
    for key in ('latency_s', 'energy_j', 'power_w', 'area_mm2', 'dram_read_bytes',
                'dram_write_bytes', 'noc_hop_bytes', 'nop_hop_bytes', 'executed_macs'):
        value = metrics.get(key)
        if value is None or not math.isfinite(value) or value < 0:
            errors.append('invalid physical metric '+key)
    if errors:
        return errors
    if not close(metrics['power_w']*metrics['latency_s'], metrics['energy_j']):
        errors.append('power * latency != energy')
    if metrics['executed_macs'] != initial['executed_macs'] + metrics.get('recompute_macs', 0):
        errors.append('MAC conservation failed')
    if metrics.get('feasible'):
        for row in metrics.get('diagnostics', {}).get('memory', []):
            if row['peak_live_bytes'] > row['capacity_bytes']:
                errors.append('feasible result exceeds '+row.get('pool_id',row.get('resource','unknown pool')))
    return errors


def analyze(out,offline_feature_ablation=False):
    config = read(out/'effective_config.json')
    common = read(out/'common.json')
    manifest = read(out/'source_snapshot_manifest.json')
    errors, warnings = [], []
    inputs=read(out/'seed_input_manifest.json')
    if inputs:
        for name,digest in inputs['files'].items():
            path=Path(config['seed_case'])/name
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                errors.append('seed input mismatch: '+name)
    else:
        warnings.append('legacy development cohort: source seed path was external; newer cohorts freeze seed inputs too')
    for rel, digest in manifest['files'].items():
        path = out/'source_snapshot'/rel
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append('snapshot mismatch: '+rel)
    common_ledger = read(out/'common_worker/accounting.json', [])
    if sum(r.get('full_evaluations', 0) for r in common_ledger) != common['full_ppa']:
        errors.append('common ledger query mismatch')
    reference, initial = common['reference'], common['metrics']
    seed_cost = cost(initial, reference, config['objective'])
    errors += physical_errors(initial, initial)
    summaries, all_events, rows, curves, mapping_changes, archive_rows = {}, {}, [], [], [], []
    arms = config['methods'].split(',')
    status = read(out/'status.json', {})
    for method in arms:
        folder = out/method
        checkpoint = read(folder/'checkpoint.json', {})
        if not checkpoint:
            warnings.append(method+': no checkpoint yet')
            continue
        ev = events(folder/'events.jsonl')
        all_events[method] = ev
        ledger = read(folder/'worker/accounting.json', [])
        full = sum(r.get('full_evaluations', 0) for r in ledger)
        journal_full = sum(r['new_full_ppa'] for r in ev)
        if journal_full > full:
            errors.append(method+': journal exceeds durable full PPA ledger')
        if journal_full < full:
            warnings.append(method+': '+str(full-journal_full)+' completed PPA recovered outside decision journal; no synthetic policy update assumed')
        if common['full_ppa'] + full > config['queries']:
            errors.append(method+': query ceiling exceeded')
        previous_updates = 0
        best = seed_cost
        entropy = []
        for event in ev:
            prefix = method+'/step '+str(event['step'])+': '
            if event['source_identity'] != manifest['identity']:
                errors.append(prefix+'source identity differs')
            if event['new_full_ppa'] not in (0, 1):
                errors.append(prefix+'invalid per-trial query charge')
            probabilities = np.asarray(event['probabilities'])
            if len(probabilities) != event['candidate_count'] or np.any(probabilities < 0) or not close(float(probabilities.sum()), 1.):
                errors.append(prefix+'invalid probability distribution')
            index = event['candidate_hashes'].index(event['state_hash'])
            if not close(event['behavior_probability'], float(probabilities[index])):
                errors.append(prefix+'selected probability mismatch')
            h = -float(np.dot(probabilities, np.log(np.maximum(probabilities,1e-300))))/max(math.log(len(probabilities)), 1e-30)
            if not close(h, event['entropy']):
                errors.append(prefix+'entropy mismatch')
            entropy.append(h)
            updates = event['policy_updates_after'] - event['policy_updates_before']
            if event['policy_updates_before'] != previous_updates:
                warnings.append(prefix+'policy update gap (possible resumed durable response)')
            previous_updates = event['policy_updates_after']
            if updates and (method != 'replay_rl' or event['status'] != 'full_completed' or not event['feasible'] or event['new_full_ppa'] != 1):
                errors.append(prefix+'policy trained without new feasible physical PPA')
            if event['status'] == 'full_completed':
                m = event['metrics']
                errors.extend(prefix+x for x in physical_errors(m, initial))
                value = cost(m, reference, config['objective'])
                if value is not None:
                    expected = -100*math.log(value/seed_cost)
                    if not close(value, event['cost']) or not close(expected, event['utility']):
                        errors.append(prefix+'objective/reward differs from physical PPA')
                    best = min(best, value)
                elif event['utility'] is not None:
                    errors.append(prefix+'infeasible PPA supplied utility')
                artifact = read(folder/'evaluations'/(event['state_hash']+'.json'))
                if not artifact:
                    errors.append(prefix+'missing complete selected mapping')
                else:
                    state = DesignState.from_dict(artifact['state'])
                    if state.fingerprint != event['state_hash']:
                        errors.append(prefix+'mapping hash mismatch')
                    if state.architecture_candidate_id != common['initial_state']['architecture_candidate_id'] or state.mapping.fusion_stacks:
                        errors.append(prefix+'fixed hardware/Fusion scope changed')
            elif event['utility'] is not None:
                errors.append(prefix+'timeout/reject supplied a fictitious reward')
            curves.append(dict(method=method, step=event['step'], charged_full_ppa=event['charged_full_ppa'],
                               charged_wall_s=common['wall_s']+event['search_wall_s'],
                               best_cost=event['best_cost'], gain_vs_seed_pct=100*(1-event['best_cost']/seed_cost),
                               status=event['status']))
        # Read full durable metrics as well: compact event rows do not contain
        # the actual per-resource lifetime peaks.
        for path in sorted((folder/'worker/completed').glob('*.json')):
            result = read(path)
            errors.extend(method+'/'+path.name+': '+x for x in physical_errors(result['metrics'], initial))
        verified=[]
        for event in ev:
            if event['status']=='full_completed' and event['feasible']:
                m=event['metrics']
                verified.append(dict(state_hash=event['state_hash'],step=event['step'],
                    full_ppa=event['charged_full_ppa'],wall_s=common['wall_s']+event['search_wall_s'],
                    cost=event['cost'],latency=m['latency_s'],energy=m['energy_j'],
                    edp=m['latency_s']*m['energy_j']))
        original=dict(state_hash=DesignState.from_dict(common['initial_state']).fingerprint,step=0,
            full_ppa=common['full_ppa'],wall_s=common['wall_s'],cost=seed_cost,
            latency=initial['latency_s'],energy=initial['energy_j'],edp=initial['latency_s']*initial['energy_j'])
        for objective in ('cost','latency','energy','edp'):
            best_observed=min([original]+verified,key=lambda r:r[objective])
            archive_rows.append(dict(method=method,metric=objective,value=best_observed[objective],
                gain_vs_seed_pct=100*(1-best_observed[objective]/original[objective]),
                state_hash=best_observed['state_hash'],at_full_ppa=best_observed['full_ppa'],
                at_charged_wall_s=best_observed['wall_s'],
                interpretation='best measured archive metric; search trained only on '+config['objective']))
        summary = read(folder/'summary.json')
        if summary:
            if summary['full_ppa'] != common['full_ppa']+full:
                errors.append(method+': summary full count differs')
            if not close(summary['best_cost'], checkpoint['elite_cost']):
                errors.append(method+': summary/checkpoint best differs')
            summaries[method] = summary
        row = dict(method=method, status=checkpoint['status'], full_ppa=common['full_ppa']+full,
                   feasible_search_ppa=sum(r.get('full_evaluations', 0) for r in ledger if r.get('ppa_feasible')),
                   search_full_ppa=full, timeouts=sum(r.get('status') == 'timeout' for r in ledger),
                   compiler_or_worker_rejects=sum(r.get('status') == 'error' for r in ledger),
                   best_cost=checkpoint['elite_cost'], gain_vs_seed_pct=100*(1-checkpoint['elite_cost']/seed_cost),
                   policy_updates=checkpoint['policy_updates'],
                   last_10_entropy=float(np.mean(entropy[-10:])) if entropy else None,
                   search_wall_s=checkpoint['elapsed_s'],
                   full_ppa_per_minute=60*full/checkpoint['elapsed_s'] if checkpoint['elapsed_s'] else None)
        baseline_state=DesignState.from_dict(common['initial_state'])
        best_state=DesignState.from_dict(checkpoint['elite'])
        used_dies=set();quotas=[];changed_count=0
        for mapping in best_state.mapping.layer_mappings:
            old=baseline_state.mapping.mapping_map[mapping.layer_id]
            quotas.append(len(mapping.chiplets));used_dies.update(p.split('/')[0] for p in mapping.chiplets)
            if mapping==old:continue
            changed_count+=1
            mapping_changes.append(dict(method=method,layer=mapping.layer_id,
                pe_count_before=len(old.chiplets),pe_count_after=len(mapping.chiplets),
                partition_before=str(old.partition.as_tuple()),partition_after=str(mapping.partition.as_tuple()),
                placement_before=';'.join(old.chiplets),placement_after=';'.join(mapping.chiplets),
                dataflow_before=old.dataflow,dataflow_after=mapping.dataflow,
                retention_before=old.weight_policy,retention_after=mapping.weight_policy,
                input_dram_before=old.input_dram,input_dram_after=mapping.input_dram,
                weight_dram_before=old.weight_dram,weight_dram_after=mapping.weight_dram,
                output_dram_before=old.output_dram,output_dram_after=mapping.output_dram))
        row.update(changed_layers=changed_count,active_compute_dies=len(used_dies),
                   min_pe_per_layer=min(quotas),max_pe_per_layer=max(quotas),
                   mean_pe_per_layer=float(np.mean(quotas)))
        for key in ('latency_s', 'energy_j', 'power_w', 'dram_read_bytes', 'noc_hop_bytes', 'nop_hop_bytes'):
            row[key] = checkpoint['elite_metrics'][key]
            row[key+'_improvement_pct'] = 100*(1-row[key]/initial[key])
        rows.append(row)

    heldout = {'status': 'not_run'}
    rl = out/'replay_rl'
    ck = read(rl/'checkpoint.json', {})
    if ck.get('policy_file') and (rl/'policy_initial.pt').exists():
        train_hashes = {e['state_hash'] for e in all_events.get('replay_rl', []) if e['policy_update']}
        control = [e for m, es in all_events.items() if m != 'replay_rl' for e in es
                   if e.get('utility') is not None and e['new_full_ppa'] == 1 and e['state_hash'] not in train_hashes]
        control = list({e['state_hash']: e for e in control}.values())
        if control:
            x = np.asarray([e['features'] for e in control], dtype=np.float32)
            y = np.asarray([e['utility'] for e in control])
            first, final = ReplayQ(x.shape[1], config['seed']), ReplayQ(x.shape[1], config['seed'])
            first.load(rl/'policy_initial.pt'); final.load(rl/ck['policy_file'])
            masked = x.copy(); masked[:, 20:28] = 0
            delta = final.predict(x)-final.predict(masked)
            heldout = dict(status='measured_control_trials_excluded_from_training',
                           initial=ranking_metrics(first.predict(x), y),
                           final=ranking_metrics(final.predict(x), y),
                           measured_bottleneck_mask_mean_abs_q_change=float(np.mean(np.abs(delta))),
                           measured_bottleneck_mask_max_abs_q_change=float(np.max(np.abs(delta))),
                           interpretation='Unseen completed control PPA tests ranking generalization. Feature masking measures influence, not causal search benefit. Contexts may differ between methods.')
            if offline_feature_ablation and config['bottleneck_features']=='on':
                began=time.perf_counter();ablation={}
                # Both fits consume the same actually measured training trials
                # in the same order. Control-arm PPA is exclusively a test set.
                training=[e for e in all_events['replay_rl'] if e['policy_update']]
                for variant in ('measured_features_on','measured_features_off'):
                    fitted=ReplayQ(x.shape[1],config['seed']);fitted.load(rl/'policy_initial.pt')
                    for event in training:
                        feature=np.asarray(event['features'],dtype=np.float32).copy()
                        if variant.endswith('off'):feature[20:28]=0
                        fitted.observe(feature,event['utility'],event['policy_updates_after']-event['policy_updates_before'])
                    test=x.copy()
                    if variant.endswith('off'):test[:,20:28]=0
                    ablation[variant]=ranking_metrics(fitted.predict(test),y)
                    if variant.endswith('on'):
                        ablation['reconstructed_final_max_abs_difference']=float(np.max(np.abs(fitted.predict(x)-final.predict(x))))
                heldout['offline_feature_ablation']=dict(**ablation,wall_s=time.perf_counter()-began,
                    additional_physical_ppa=0,training_trials=len(training),
                    interpretation='Fixed-data prediction ablation only. Does not establish a causal on-policy search win and does not train the saved search policy.')

    equal_queries = []
    if rows:
        maximum = min(r['full_ppa'] for r in rows)
        for budget in sorted({4, 8, 16, 24, 32, 48, 64, 128, 256, maximum}):
            if budget < common['full_ppa'] or budget > maximum:
                continue
            for method in all_events:
                values = [r for r in curves if r['method'] == method and r['charged_full_ppa'] <= budget]
                value = min([seed_cost]+[r['best_cost'] for r in values])
                equal_queries.append(dict(method=method, full_ppa_budget=budget, best_cost=value,
                                          gain_vs_seed_pct=100*(1-value/seed_cost)))
    equal_time = []
    if rows:
        maximum = min(r['search_wall_s']+common['wall_s'] for r in rows)
        for seconds in (60, 120, 300, 600, 900, 1800, 3600):
            if seconds < common['wall_s'] or seconds > maximum:
                continue
            for method in all_events:
                values = [r for r in curves if r['method'] == method and r['charged_wall_s'] <= seconds]
                value = min([seed_cost]+[r['best_cost'] for r in values])
                equal_time.append(dict(method=method, charged_wall_budget_s=seconds, best_cost=value,
                                       full_ppa=max([common['full_ppa']]+[r['charged_full_ppa'] for r in values]),
                                       gain_vs_seed_pct=100*(1-value/seed_cost)))
    result = dict(passed=not errors, errors=errors, warnings=warnings, run_status=status,
                  source_identity=manifest['identity'], actual_unique_physical_ppa=common['full_ppa']+sum(r['search_full_ppa'] for r in rows),
                  rows=rows, heldout_policy=heldout,
                  limitations=['Single source/RNG case is not stable multi-seed superiority.',
                               'Balanced cost and latency/energy must be reported separately.',
                               'Shared proposal/inner improvements are not evidence of RL selection advantage.',
                               'No additional physical PPA performed by this analysis.'])
    destination = out/'analysis'; destination.mkdir(exist_ok=True)
    (destination/'audit.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    for name, values in (('comparison', rows), ('curves', curves), ('equal_queries', equal_queries), ('equal_time', equal_time), ('best_mapping_changes',mapping_changes),('best_measured_archive_metrics',archive_rows)):
        with (destination/(name+'.csv')).open('w', encoding='utf-8-sig', newline='') as stream:
            if values:
                writer = csv.DictWriter(stream, fieldnames=list(values[0])); writer.writeheader(); writer.writerows(values)
    lines = ['# INMIN v0.4 數字審計', '', 'Audit passed: '+str(not errors),
             'Run status: '+str(status.get('status')), '',
             '|Method|Full PPA|Cost 改善 %|Latency 改善 %|Energy 改善 %|PPA/min（搜尋）|最後10步 entropy|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        keys = ('method', 'full_ppa', 'gain_vs_seed_pct', 'latency_s_improvement_pct', 'energy_j_improvement_pct', 'full_ppa_per_minute', 'last_10_entropy')
        lines.append('|'+ '|'.join(f'{r[k]:.6f}' if isinstance(r[k], float) else str(r[k]) for k in keys)+'|')
    lines += ['', '## Policy 的未見候選驗證', '', '```json', json.dumps(heldout, ensure_ascii=False, indent=2), '```', '',
              '共同 query/time 預算的結果見 equal_queries.csv / equal_time.csv；全步數值曲線見 curves.csv。',
              '沒有產生圖片。未見候選排序與 feature mask 只是模型行為證據；實際搜尋勝負以相同預算的完整 PPA 結果為準。',
              'SGD 更新次數不是 PPA 次數；內層最佳化、warmup 與 RL 選擇的效果必須分開歸因。']
    for e in errors:
        lines.append('- ERROR: '+e)
    for w in warnings:
        lines.append('- '+w)
    (destination/'ANALYSIS.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=not errors, errors=len(errors), warnings=len(warnings), rows=rows, heldout_policy=heldout), ensure_ascii=False))
    return not errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--offline-feature-ablation',action='store_true')
    args=parser.parse_args()
    raise SystemExit(not analyze(args.out.resolve(),args.offline_feature_ablation))
