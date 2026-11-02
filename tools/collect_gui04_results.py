"""Collect measured GUI04 evidence; never writes October 31 report files."""
from pathlib import Path
from collections import Counter,defaultdict
import sys,json,csv,hashlib,math

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/gui04_20261101'
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from collect_detailed_report_data import deployment,workload_from,csvfile
from rl_dse import source_identity
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def partition_class(part):
    b,k,h,w=part
    return 'weight_shared_P' if k==1 and h*w>1 else 'activation_shared_K' if k>1 and h*w==1 else 'mixed_PK' if k>1 and h*w>1 else 'serial_single_core'
def annotate(detail):
    w=workload_from(detail['workload']);counts=Counter();conv=Counter();macs=Counter();rows=[]
    for item in detail['layers']:
        layer=w.layer_map[item['layer']];kind=partition_class(item['partition_BKHW'])
        counts[kind]+=1;macs[kind]+=layer.macs_per_sample*w.batch_size
        if layer.kind=='Conv2d':conv[kind]+=1
        rows.append({'layer':layer.id,'operator':layer.kind,'partition_class':kind,
            'partition_BKHW':item['partition_BKHW'],'cores':item['ordered_cores'],'weight_bytes':layer.weight_bytes,
            'input_tensor_bytes':sum(w.tensor_map[t].bytes for t in layer.inputs),
            'output_bytes':w.tensor_map[layer.output].bytes,'logical_MACs':layer.macs_per_sample*w.batch_size,
            'DF_depth':item['DF_depth'],'DF_sink_tile_HW':item['DF_sink_tile_HW'],'overlap':item['overlap']})
    banks=defaultdict(lambda:defaultdict(int))
    for core in detail['metrics']['diagnostics']['memory']:
        for bank,access in core.get('bank_accesses',{}).items():
            for mode,value in access.items():banks[bank][mode]+=value
    ledger={bank:{'read_bytes':v.get('read_bits',0)/8,'write_bytes':v.get('write_bits',0)/8,
        'reads_per_filled_byte':v.get('read_bits',0)/v['write_bits'] if v.get('write_bits') else None} for bank,v in banks.items()}
    detail['partition_analysis']={'all_layer_counts':dict(counts),'conv_layer_counts':dict(conv),'logical_MACs_by_class':dict(macs),'sram_ledger':ledger}
    csvfile(BASE/'evidence'/detail['case']/detail['model']/'partition_classification.csv',rows)
    return detail

def main():
    cases=[];summary=[];controls=[]
    batch=read(BASE/'final_batch.json') if (BASE/'final_batch.json').is_file() else {}
    cohorts=read(BASE/'source_cohorts.json') if (BASE/'source_cohorts.json').is_file() else {}
    accepted=cohorts.get('accepted_source_identities',[source_identity()])
    experiment_root=Path(batch.get('root',str(BASE)))
    for folder in sorted((experiment_root/'experiments').iterdir()):
        if not (folder/'status.json').is_file():continue
        spec=read(folder/'experiment.json');status=read(folder/'status.json')
        case={'id':spec['id'],'spec':spec,'status':status,'deployments':[]}
        if status['status']!='complete':cases.append(case);continue
        if not status.get('source_stable') or status.get('source_after') not in accepted:
            case['status']={**status,'status':'waiting_for_current_source','note':'previous revision evidence is not a final-current-source result'}
            cases.append(case);continue
        if spec['kind']=='auto':
            suite=read(folder/'run/suite.json');case['suite']=suite
            case['accounting']=read(folder/'run/accounting.json');selected=suite['display_architecture']
            selected_rows=[r for r in suite['runs'] if r['architecture']==selected]
            for row in selected_rows:
                m=row['metrics'];detail=annotate(deployment(spec['id'],row['model'],row,BASE/'evidence'))
                case['deployments'].append(detail)
                assert math.isclose(m['power_w'],m['energy_j']/m['latency_s'],rel_tol=1e-12)
            for model,a in case['accounting'].items():
                path=folder/'run'/model/'joint_search.json'
                search=read(path) if path.is_file() else {}
                coverage_path=folder/'run'/model/'fusion_proposal_coverage.json'
                coverage=read(coverage_path) if coverage_path.is_file() else {'history':[]}
                proposed=Counter();evaluated=set()
                for event in coverage['history']:
                    for d,count in event['proposed_depths'].items():proposed[int(d)]+=count
                for t in search.get('trace',[]):
                    if not t['valid']:continue
                    for edit in t['action_plan']['ordered_edits']:
                        if edit['action_id']=='A1' and edit['parameters'].get('operation') in ('merge','shift_boundary'):
                            evaluated.add(len(edit['parameters']['layer_ids']))
                row=next((r for r in selected_rows if r['model']==model),None)
                detail=next((d for d in case['deployments'] if d['model']==model),None)
                m=row['metrics'] if row else {}
                entry={'case':spec['id'],'model':model,'profile':suite['config']['search_mode'],
                    'preference':suite['config']['preference'],'budget_mode':suite['config']['budget_mode'],
                    'query_ceiling':suite['config']['budget'],'wall_ceiling_s':suite['config']['max_wall_time_s'],
                    'wall_s':status['elapsed_s'],'execution_status':suite['execution_status'],'stop_reason':a['stop_reason'],
                    'source_identity':status['source_after'],'source_stable':status['source_stable'],
                    'recommendation_status':suite['recommendation_status'],'best_architecture':suite['best_architecture'],
                    'display_architecture':selected,'compute':m.get('compute_chiplets'),
                    'latency_ms':m['latency_s']*1000 if m else None,'power_W':m.get('power_w'),
                    'area_mm2':m.get('area_mm2'),'energy_mJ':m['energy_j']*1000 if m else None,
                    'seed_full_evaluations':a['seed_full_evaluations_this_process'],
                    'RL_full_evaluations':a['rl_unique_full_evaluations'],'policy_updates':search.get('policy_updates',0),
                    'cache_hits':a['rl_cache_hits'],'report_replay_evaluations':a['report_replay_full_evaluations'],
                    'local_DP_compile_queries':a['local_dp_compile_queries'],'timed_out_attempts':a['timed_out_attempts'],
                    'bootstrap_architectures':a['bootstrap_architectures'],'archive_architectures':a['verified_archive_architectures'],
                    'proposed_fusion_depths':sorted(proposed),'selected_and_evaluated_fusion_depths':sorted(evaluated),
                    'best_DF_depths':[len(s['layer_ids']) for s in detail['mapping']['fusion_stacks']] if detail else [],
                    'best_conv_partition_counts':detail['partition_analysis']['conv_layer_counts'] if detail else {}}
                summary.append(entry)
                case.setdefault('search_evidence',{})[model]={'summary':entry,'depth_proposals':dict(proposed),
                    'coverage':coverage,'trace':[{'step':t['step'],'family':t['action_plan']['family_id'],'valid':t['valid'],
                        'reward':t['reward'],'edits':t['action_plan']['ordered_edits'],'rejection_reason':t['rejection_reason']} for t in search.get('trace',[])]}
                csvfile(BASE/'evidence'/spec['id']/model/'search_transitions.csv',case['search_evidence'][model]['trace'])
        else:
            results=read(folder/'controlled_results.json');case['controlled']=results
            for result in results:
                m=result.get('metrics',{});variant=result['variant'];id=spec['id']+'_'+variant
                value={'case':spec['id'],'model':spec['model'],'variant':variant,'status':result['status'],
                    'matched_temporal_tile_BKHW':spec.get('matched_temporal_tile_BKHW'),
                    'architecture':result['architecture'],'compute':m.get('compute_chiplets'),
                    'physical_feasible':m.get('feasible'),'source_identity':status['source_after'],'source_stable':status['source_stable'],
                    'latency_ms':m['latency_s']*1000 if m else None,'power_W':m.get('power_w'),'area_mm2':m.get('area_mm2'),
                    'energy_mJ':m['energy_j']*1000 if m else None,'wall_s':result['elapsed_s'],
                    'fallback_layers':result['fallback_layers_no_exact_target_partition'],'violations':m.get('violations')}
                if m:
                    row={'architecture':result['architecture'],'folder':str(folder/variant),'metrics':m,
                        'within_limits':m['feasible'],'all_targets_met':m['feasible'],'constraints':{'limits':[]}}
                    detail=annotate(deployment(id,spec['model'],row,BASE/'evidence'));case['deployments'].append(detail)
                    value.update(detail_id=id,partition_counts=detail['partition_analysis']['conv_layer_counts'],
                        SRAM_ledger=detail['partition_analysis']['sram_ledger'],flow_ledger=result['flow_ledger'],
                        weight_reuse=m['weight_reuse'],recompute_MACs=m['recompute_macs'],
                        DF_depths=[len(s['layer_ids']) for s in detail['mapping']['fusion_stacks']])
                controls.append(value)
        cases.append(case)
    log=BASE/'full_regression_delivery.log'
    if not log.is_file():log=BASE/'full_regression_release.log'
    text=log.read_text(encoding='utf-8') if log.is_file() else ''
    import re
    match=re.search(r'Ran (\d+) tests',text)
    test_result=(match.group(1)+' tests / OK') if match and text.rstrip().endswith('OK') else 'full regression not confirmed'
    dump(BASE/'gui04_report_data.json',{'cases':cases,'auto_results':summary,'controlled_results':controls,
        'test_result':test_result,'historical_files_protected':578,'final_source_identity':source_identity()})
    csvfile(BASE/'auto_results.csv',summary);csvfile(BASE/'partition_and_fusion_controls.csv',controls)
    print(json.dumps({'cases':len(cases),'auto_results':len(summary),'controls':len(controls)},ensure_ascii=False))

if __name__=='__main__':main()
