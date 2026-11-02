"""GUI04 v2 orchestration. Numeric v1 replay stays in rl_dse.run_joint_model."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from statistics import median
import json,math,time

from simple_rapidchiplet.hybrid.report import write_json
from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures,resource_totals
from simple_rapidchiplet.hybrid.hardware import GEMINI_CHIPLET_PROFILE
from simple_rapidchiplet.hybrid.rl_schema import DesignState
from simple_rapidchiplet.hybrid.rl_search import run_joint_search,JointSearchConfig,executable
from simple_rapidchiplet.hybrid.auto_runtime import BoundedOraclePool,EvaluationTimeout,atomic_json
from simple_rapidchiplet.hybrid.auto_proposals import AutoProposals
from simple_rapidchiplet.hybrid.tangram_seed import diverse_tangram_seeds
from simple_rapidchiplet.hybrid.search import plan_from_dict
from rl_dse import make_objective,source_identity,PPA_PREFERENCES,constraints,rank_joint_rows

def _read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def _state(candidate,plan,workload,config):
    return DesignState(candidate.id,plan,workload.fingerprint,hardware_template_version=GEMINI_CHIPLET_PROFILE,
        preferences=PPA_PREFERENCES[config['preference']],
        constraints={k:config.get(k) for k in ('max_power','max_area','max_latency_ms','strict_power','strict_area','strict_latency')},
        workload_definition={'batch_size':workload.batch_size,'model':workload.name,'source':workload.source})

def run_auto_model(config,workload,folder,*,resume=False,update=lambda **_:None,started_at=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);started=started_at if started_at is not None else time.monotonic()
    identity=source_identity();context={'source_identity':identity,'config':config,'workload_fingerprint':workload.fingerprint}
    if resume and (folder/'context.json').is_file() and _read(folder/'context.json')!=context:
        raise ValueError('resume source/workload/effective settings differ; use a new folder')
    write_json(folder/'context.json',context);write_json(folder/'workload.json',workload.to_dict())
    old_accounting=_read(folder/'accounting.json') if resume and (folder/'accounting.json').is_file() else {}
    elapsed_before=old_accounting.get('cumulative_elapsed_s',0.)
    deadline=started+max(0.,config['max_wall_time_s']-elapsed_before)
    work_end=deadline-config['report_reserve_s']
    candidates=enumerate_gemini_architectures(compute_counts=tuple(config['dies']));by_id={c.id:c for c in candidates}
    objective=make_objective(config);reference={};archive={};seed_records=[];bootstrap=[];allocation=[]
    if resume and (folder/'seed_states.json').is_file():
        data=_read(folder/'seed_states.json');seed_records=data['records'];reference=data['reference']
        bootstrap=[(DesignState.from_dict(v['state']),v['metrics']) for v in data['states']]
        archive=_read(folder/'verified_archive.json') if (folder/'verified_archive.json').is_file() else {}
    pool=BoundedOraclePool(workload,folder/'oracle_runtime',deadline=deadline,
                          evaluation_timeout_s=config['evaluation_timeout_s'])
    def recent_cost():
        values=[r['evaluation_elapsed_s'] for r in pool.records if r['operation']=='evaluate' and r['status']=='complete' and r.get('full_evaluations')]
        return median(values[-5:]) if values else 0.
    def save_seed_states():
        atomic_json(folder/'seed_states.json',{'states':[{'state':s.to_dict(),'metrics':m} for s,m in bootstrap],
            'reference':reference,'records':seed_records,'source_identity':identity})
    def evaluate(candidate,plan,phase='rl'):
        update(message=f'{workload.name}：{phase} 完整評估 {candidate.id}；剩餘 {max(0,work_end-time.monotonic()):.1f}s')
        result=pool.evaluate(candidate,plan,deadline=work_end,phase=phase);m=result['metrics']
        if executable(m):
            if not reference:reference.update(m)
            state=_state(candidate,plan,workload,config)
            rank=(not objective.strict_feasible(m),objective.violation(m),objective.cost(m,reference))
            old=archive.get(candidate.id)
            if old is None or rank<tuple(old['rank']):
                path=folder/candidate.id
                pool.persist(candidate,plan,path,config)
                entry={'state':state.to_dict(),'metrics':m,'rank':list(rank),'cost':rank[2],
                       'violation':rank[1],'strict_feasible':not rank[0],'folder':str(path.resolve())}
                archive[candidate.id]=entry
                atomic_json(folder/'verified_archive.json',archive)
        return SimpleNamespace(metrics=m)
    try:
        if not bootstrap:
            # Geometry/DRAM + MAC proxy orders shapes within each count.
            # The whole 15-template action domain remains available to RL.
            ordered=[];proxy=[]
            for c in candidates:
                area=sum(n.width_mm*n.height_mm for n in c.package.nodes.values())
                pruned=config['strict_area'] and config['max_area'] is not None and area>config['max_area']
                bound=workload.total_macs/(c.hardware.macs_per_second*c.hardware.compute_count)+sum(l.weight_bytes for l in workload.layers)/(len(c.package.memory_ids)*c.hardware.dram_bandwidth_Bps)
                proxy.append({'architecture':c.id,'silicon_area_mm2':area,'proxy_compute_plus_weight_s':bound,
                              'hard_area_pruned':pruned,'proxy_is_final_ppa':False})
            legal=[c for c in candidates if not next(p for p in proxy if p['architecture']==c.id)['hard_area_pruned']]
            for count in config['dies']:
                members=[c for c in legal if c.hardware.compute_count==count]
                members.sort(key=lambda c:next(p['proxy_compute_plus_weight_s'] for p in proxy if p['architecture']==c.id))
                if members:ordered.append(members[0])
            ordered.extend(c for c in legal if c not in ordered)
            write_json(folder/'architecture_seed_proxy.json',proxy)
            proposals={};attempts=0;coverage=set();attempted=set()
            def try_seed(c,row):
                nonlocal attempts
                key=(c.id,repr(row.plan))
                if key in attempted:return
                attempted.add(key)
                attempts+=1;tick=time.monotonic();record={'architecture':c.id,'origin':row.origin,
                    'proxy_delay_s':row.estimated_delay_s,'proxy_energy_j':row.estimated_energy_j,
                    'proxy_is_final_ppa':False}
                try:
                    m=evaluate(c,row.plan,'seed').metrics
                    record.update(status='complete',physical_executable=executable(m),metrics=m)
                    if executable(m):bootstrap.append((_state(c,row.plan,workload,config),m));coverage.add(c.id)
                except EvaluationTimeout as error:record.update(status='timeout',error=str(error))
                except ValueError as error:record.update(status='rejected',error=str(error))
                record['elapsed_s']=time.monotonic()-tick;seed_records.append(record);save_seed_states()
            for c in ordered:
                if attempts>=config['seed_budget'] or time.monotonic()>=work_end:break
                proposals[c.id]=diverse_tangram_seeds(workload,c.package.mapping_core_ids,c.package.memory_ids,c.hardware,max_candidates=4)
                for row in proposals[c.id][:2]:
                    if attempts>=config['seed_budget'] or time.monotonic()>=work_end:break
                    try_seed(c,row)
                    if c.id in coverage:break
                if len(coverage)>=config['seed_architecture_target']:break
            # Spend remaining seed quota on both P and K / sized-tile variants,
            # round-robin across covered architectures, if time permits.
            for variant in range(1,6):
                for key in list(proposals):
                    if attempts>=config['seed_budget'] or work_end-time.monotonic()<max(1,recent_cost()):break
                    if variant<len(proposals[key]):try_seed(by_id[key],proposals[key][variant])
            write_json(folder/'seed_attempts.json',seed_records)
        if not bootstrap:
            status='timeout_no_completed_seed' if time.monotonic()>=work_end or any(r['status']=='timeout' for r in seed_records) else 'no_executable_seed'
            result=None;hook=None
        else:
            initial=bootstrap[0][0];hook=AutoProposals(workload,candidates,config);hook.deadline=work_end
            search_config=JointSearchConfig(seed=config['seed'],budget=config['budget'],
                max_steps=max(16,config['budget']*4),horizon=config.get('horizon',4),
                shortlist=config.get('shortlist',48),random_quota=12,max_per_family=12,
                fusion_enabled=config['fusion']!='off',max_fusion_depth=config['fusion_depth'],
                checkpoint_every=1,max_wall_time_s=max(.001,work_end-time.monotonic()))
            limits_path=folder/'rl_effective_config.json'
            if resume and limits_path.is_file():
                search_config=JointSearchConfig(**_read(limits_path))
            else:write_json(limits_path,asdict(search_config))
            def guard(oracle):
                left=work_end-time.monotonic();cost=recent_cost()
                predicted=int(left/max(.05,cost)) if cost else config['budget']
                allocation.append({'elapsed_s':time.monotonic()-started,'remaining_wall_s':left,
                    'measured_recent_eval_s':cost,'predicted_additional_queries':max(0,predicted),
                    'declared_query_ceiling':config['budget'],'used_exact_RL_queries':oracle.evaluations})
                if left<=0:return 'wall_time_budget_exhausted'
                if cost and left<cost*.65:return 'measured_cost_budget_exhausted'
                return None
            result=run_joint_search(workload,initial,candidates,lambda c:lambda p:evaluate(c,p,'rl'),
                objective=objective,config=search_config,checkpoint_path=folder/'checkpoint.json',
                resume=resume and (folder/'checkpoint.json').is_file(),
                evaluator_identity=identity,bootstrap_evaluations=bootstrap,proposal_hook=hook,resource_guard=guard)
            status=result.status;write_json(folder/'joint_search.json',result.to_dict())
            write_json(folder/'fusion_proposal_coverage.json',hook.state_dict())
    finally:
        pool.close()
    rows=[]
    for key,entry in archive.items():
        m=entry['metrics'];report=constraints(m,objective)
        row={'model':workload.name,'architecture':key,'folder':entry['folder'],'metrics':m,
            'hardware_resources':resource_totals(by_id[key].hardware),'chiplet_profile':GEMINI_CHIPLET_PROFILE,
            'constraints':report,'within_limits':report['strict_compliant'],'all_targets_met':report['all_targets_met'],
            'cost':entry['cost'],'violation':entry['violation'],'method':'rl','seed':config['seed'],
            'artifact_available':True,'error':None}
        rows.append(row);write_json(Path(entry['folder'])/'run.json',row)
    complete=lambda phase:sum(r.get('full_evaluations',0) for r in pool.records if r['operation']=='evaluate' and r['phase']==phase)
    accounting={'source_identity':identity,'backend':'official_rapidchiplet','search_profile':config['search_mode'],
        'declared_RL_query_ceiling':config['budget'],'declared_wall_ceiling_s':config['max_wall_time_s'],
        'seed_full_evaluations_this_process':complete('seed'),'seed_attempts_this_process':sum(r['operation']=='evaluate' and r['phase']=='seed' for r in pool.records),
        'rl_full_evaluations_this_process':complete('rl'),'rl_unique_full_evaluations':result.evaluations if result else 0,
        'rl_cache_hits':result.requests-result.evaluations if result else 0,'report_replay_full_evaluations':0,
        'total_full_evaluations_this_process':pool.full_evaluations,'oracle_cache_hits':pool.cache_hits,
        'timed_out_attempts':sum(r['status']=='timeout' for r in pool.records),
        'archive_save_operations':sum(r['operation']=='persist' and r['status']=='complete' for r in pool.records),
        'archive_save_s':sum(r.get('elapsed_s',0) for r in pool.records if r['operation']=='persist'),
        'seed_evaluation_s':sum(r.get('elapsed_s',0) for r in pool.records if r['operation']=='evaluate' and r['phase']=='seed'),
        'rl_evaluation_s':sum(r.get('elapsed_s',0) for r in pool.records if r['operation']=='evaluate' and r['phase']=='rl'),
        'local_dp_full_evaluator_calls':0,'local_dp_compile_queries':sum(x['local_compile_queries'] for e in (hook.history if hook else []) for x in e['local_dp']),
        'bootstrap_architectures':sorted({s.architecture_candidate_id for s,m in bootstrap}),
        'verified_archive_architectures':list(archive),'stop_reason':status,'elapsed_s_this_process':time.monotonic()-started,
        'cumulative_elapsed_s':elapsed_before+time.monotonic()-started,
        'note':'Only completed full evaluations provide PPA. Seed bootstrap cache reads are not counted as RL full queries. Archive exports reuse retained completed traces; report replay count is zero.'}
    write_json(folder/'accounting.json',accounting);write_json(folder/'adaptive_allocations.json',allocation)
    if result:
        from simple_rapidchiplet.hybrid.rl_report import write_search_report
        write_search_report(folder,workload,result,rows,accounting)
    return rows,{'status':status,'accounting':accounting,'folder':str(folder.resolve()),
        'search_file':'joint_search.json' if result else None}

def run_auto_suite(config,folder,update=lambda **_:None,*,resume=False):
    from simple_rapidchiplet.hybrid.models import extract_model
    from simple_rapidchiplet.hybrid.workload import make_toy_workload
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    if resume and (folder/'config.json').is_file() and _read(folder/'config.json')!=config:raise ValueError('effective configuration differs')
    write_json(folder/'config.json',config);rows=[];searches={};models={}
    for i,name in enumerate(config['models']):
        model_started=time.monotonic()
        update(completed=i,total=len(config['models']),message='解析 '+name+' DAG')
        workload=make_toy_workload(batch=1,channels=8,spatial=8) if name=='toy' else extract_model(name,1,input_size=config['input_size'])
        models[name]={'layers':len(workload.layers),'macs':workload.total_macs,'fingerprint':workload.fingerprint,'source':workload.source}
        trial,evidence=run_auto_model(config,workload,folder/name,resume=resume,update=update,started_at=model_started)
        for row in trial:row['model']=name
        rows.extend(trial);searches[name]=evidence
        write_json(folder/'trials.json',rows);update(completed=i+1,total=len(config['models']),rows=rows)
    ranking,recommendation=rank_joint_rows(rows,config['models']);selected=recommendation['display_architecture']
    selected_rows=[r for r in rows if r['architecture']==selected]
    truncated=any(any(t in v['status'] for t in ('wall_time','measured_cost','timeout')) for v in searches.values())
    state='budget_truncated' if truncated and rows else 'timeout' if truncated else 'complete'
    recommendation.update(chiplet_profile=GEMINI_CHIPLET_PROFILE,
        recommended_chiplets=selected_rows[0]['hardware_resources']['compute_dies'] if recommendation['best_architecture'] else None,
        deployments=[{'model':r['model'],'folder':r['folder'],'layout_file':'layout.html'} for r in selected_rows],candidate_counts=config['dies'])
    result={'config':config,'models':models,'runs':rows,'searches':searches,'ranking':ranking,**recommendation,
        'execution_status':state,'best_so_far_is_fully_evaluated':True,'weights':PPA_PREFERENCES[config['preference']],
        'objective':'fixed-reference weighted L/Lref + A/Aref + P/Pref; unchanged physical difference reward',
        'capabilities':{'local_fusion_DP':'bounded compiled-region proposal optimizer; full PPA evaluated globally',
                        'C10_local_partition_DP':False,'arbitrary_floorplan':False,'arbitrary_routing':False},
        'interpretation':'finite-budget analytical estimates; no global optimality or measured silicon claim'}
    write_json(folder/'suite.json',result);write_json(folder/'recommendation.json',recommendation)
    write_json(folder/'accounting.json',{m:s['accounting'] for m,s in searches.items()})
    update(result=result,completed=len(config['models']),total=len(config['models']),
        message=('時間／成本預算截斷；保留已完整評估的 best-so-far。' if truncated else '完成有限預算搜尋。')+
                ('找到符合硬限制的估算方案。' if recommendation['best_architecture'] else '未找到共同可行推薦；請檢查覆蓋與違反量。'))
    return result
