"""Gemini-like fixed 2x2-core chiplets: Tangram seed -> joint candidate RL DSE."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import time

from simple_rapidchiplet.hybrid.report import write_json, save_evaluation

PPA_PREFERENCES = {
    'balanced': {'label': '均衡', 'power': 1/3, 'area': 1/3, 'latency': 1/3},
    'low_power': {'label': '低功率', 'power': .8, 'area': .1, 'latency': .1},
    'small_area': {'label': '小面積', 'power': .1, 'area': .8, 'latency': .1},
    'low_latency': {'label': '低延遲', 'power': .1, 'area': .1, 'latency': .8},
}


def make_objective(config):
    from simple_rapidchiplet.hybrid.rl_search import JointObjective
    weights = PPA_PREFERENCES[config.get('preference', 'balanced')]
    limits = {'power_w': config.get('max_power'), 'area_mm2': config.get('max_area'),
              'latency_s': None if config.get('max_latency_ms') is None else config['max_latency_ms']/1000}
    kwargs = {}
    for metric, value in limits.items():
        strict_key = {'power_w':'power', 'area_mm2':'area', 'latency_s':'latency'}[metric]
        kwargs[('max_' if config.get('strict_'+strict_key, True) else 'soft_')+metric] = value
    return JointObjective(latency_weight=weights['latency'], area_weight=weights['area'],
                          power_weight=weights['power'], energy_weight=0, **kwargs)


def source_identity():
    root = Path(__file__).resolve().parent
    paths = sorted((root/'simple_rapidchiplet'/'hybrid').glob('*.py'))+[Path(__file__).resolve()]
    if (root/'auto_dse.py').is_file():paths.append(root/'auto_dse.py')
    return hashlib.sha256(b''.join(path.name.encode()+path.read_bytes() for path in paths)).hexdigest()


def constraints(metrics, objective):
    from simple_rapidchiplet.hybrid.preferences import constraint_report
    return constraint_report(metrics, objective)


def run_joint_model(config, workload, folder, *, resume=False, update=lambda **_:None):
    """One episode varies architecture as well as mapping; no outer fixed-count RL."""
    from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures, resource_totals
    from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
    from simple_rapidchiplet.hybrid.hardware import GEMINI_CHIPLET_PROFILE
    from simple_rapidchiplet.hybrid.tangram_seed import build_tangram_seed
    from simple_rapidchiplet.hybrid.rl_schema import DesignState
    from simple_rapidchiplet.hybrid.rl_search import run_joint_search, JointSearchConfig
    from simple_rapidchiplet.hybrid.search import plan_from_dict
    from simple_rapidchiplet.hybrid.rl_report import write_search_report

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    candidates = enumerate_gemini_architectures(compute_counts=tuple(config.get('dies',(1,2,4,8,16))))
    objective = make_objective(config)
    evaluators = {}
    def evaluator_for(candidate):
        if candidate.id not in evaluators:
            evaluators[candidate.id] = HybridEvaluator(workload, candidate.hardware,
                max_inflight_microbatches=config.get('pipeline_window',2), trace=False)
        return evaluators[candidate.id]

    identity = source_identity()
    context = {'source_identity':identity,'workload_fingerprint':workload.fingerprint,
               'config':config,'architecture_candidates':[candidate.to_dict() for candidate in candidates]}
    context_path = folder/'context.json'
    if resume and context_path.is_file() and json.loads(context_path.read_text(encoding='utf-8')) != json.loads(json.dumps(context)):
        raise ValueError('resume source, workload, hardware or configuration differs; choose a new output folder')
    write_json(context_path, context)
    write_json(folder/'workload.json',workload.to_dict())
    # Seed generation is paid separately and reported; the RL evaluator budget is explicit.
    initial = None
    seed_records = []
    seed_reference = {}
    def seed_score(metrics):
        if not seed_reference:
            seed_reference.update(metrics)
        return objective.penalized_cost(metrics,seed_reference)
    for architecture in candidates:
        evaluator = evaluator_for(architecture)
        seed_path = folder/'seed.json'
        if resume and seed_path.is_file():
            saved = json.loads(seed_path.read_text(encoding='utf-8'))
            initial = DesignState(saved['architecture_candidate_id'],plan_from_dict(saved['mapping']),workload.fingerprint)
            seed_records = saved['attempts']
            break
        update(message=f'{workload.name}：Tangram DP/beam 起點 / {architecture.id}')
        seed = build_tangram_seed(workload, evaluator.package.mapping_core_ids,
            evaluator.package.memory_ids, architecture.hardware, evaluator=evaluator,
            microbatch_sizes=tuple(b for b in (1,2,4,8) if workload.batch_size%b==0),
            max_group_layers=config.get('groups',3), max_candidates=config.get('seed_budget',4),
            max_evaluations=config.get('seed_budget',4),score_fn=seed_score)
        seed_records.append({'architecture':architecture.id, **seed.to_dict()})
        if seed.plan is not None:
            initial = DesignState(architecture.id,seed.plan,workload.fingerprint)
            write_json(seed_path,{'architecture_candidate_id':architecture.id,'mapping':seed.plan.to_dict(),
                'attempts':seed_records,'interpretation':'source-traced Tangram-style DP/beam adapter; see provenance'})
            break
    if initial is None:
        raise ValueError('no executable Tangram seed in the declared architecture templates')
    # Initialization and RL have separate paid oracle budgets. Recompute the
    # initial design once for RL so a seed-cache hit is never called a full query.
    if not resume:
        for evaluator in evaluators.values():
            evaluator.cache.clear()
    initial = replace(initial, hardware_template_version=GEMINI_CHIPLET_PROFILE,
        preferences=PPA_PREFERENCES[config.get('preference','balanced')],
        constraints={key:config.get(key) for key in ('max_power','max_area','max_latency_ms','strict_power','strict_area','strict_latency')},
        workload_definition={'batch_size':workload.batch_size,'model':workload.name,'source':workload.source})
    if config.get('dataflow','auto') != 'auto':
        initial=replace(initial,mapping=replace(initial.mapping,layer_mappings=tuple(
            replace(item,dataflow=config['dataflow']) for item in initial.mapping.layer_mappings)))
    search_config = JointSearchConfig(seed=config.get('seed',7), budget=config.get('budget',64),
        max_steps=config.get('max_steps',max(16,config.get('budget',64)*4)),
        horizon=config.get('horizon',16), shortlist=config.get('shortlist',48),
        random_quota=config.get('random_quota',12), max_per_family=config.get('max_per_family',12),
        proposal=config.get('proposal','composite'), method=config.get('method','rl'))
    # Feature flags are declared by the action backend, never silently supplied to an inner optimizer.
    supported_fields = search_config.__dataclass_fields__
    overrides = {key:value for key,value in {
        'fusion_enabled':config.get('fusion','dp')!='off',
        'max_fusion_depth':config.get('fusion_depth',4),
    }.items() if key in supported_fields}
    search_config = replace(search_config,**overrides)
    update(message=f'{workload.name}：候選式 RL，聯合搜尋顆數／分割／資料流')
    result = run_joint_search(workload,initial,candidates,lambda candidate:evaluator_for(candidate).evaluate,
        objective=objective,config=search_config,checkpoint_path=folder/'checkpoint.json',
        resume=resume,evaluator_identity=identity)
    serialized = result.to_dict()
    write_json(folder/'joint_search.json',serialized)
    write_json(folder/'seed_attempts.json',seed_records)
    rows = []
    archive = result.architecture_archive
    for architecture in candidates:
        entry = archive.get(architecture.id)
        if not entry:
            continue
        state = DesignState.from_dict(entry['state'])
        evaluator = evaluator_for(architecture)
        evaluation = evaluator.evaluate(state.mapping,retain_trace=True)
        run_folder = folder/architecture.id
        save_evaluation(run_folder,evaluation,evaluator,state.mapping,
                        planning={'method':'Tangram seed + transactional joint RL','seed_file':'../seed.json'},arguments=config)
        report = constraints(evaluation.metrics,objective)
        row = {'model':workload.name,'architecture':architecture.id,'folder':str(run_folder.resolve()),
            'hardware_resources':resource_totals(architecture.hardware),'chiplet_profile':GEMINI_CHIPLET_PROFILE,
            'metrics':evaluation.metrics,'constraints':report,'within_limits':report['strict_compliant'],
            'all_targets_met':report['all_targets_met'],'cost':entry['cost'],'violation':entry['violation'],
            'method':search_config.method,'seed':search_config.seed,'error':None}
        rows.append(row)
        write_json(run_folder/'run.json',row)
    accounting = {'rl_unique_full_evaluations':result.evaluations,'rl_evaluation_requests':result.requests,
        'total_full_evaluations_this_process':sum(e.evaluations for e in evaluators.values()),
        'seed_budget_per_attempt':config.get('seed_budget',4),'seed_attempts':len(seed_records),
        'report_replay_included':True,'elapsed_s':time.monotonic()-started,
        'resume_note':'this-process counters and checkpoint cumulative RL counters are intentionally separate'}
    write_json(folder/'accounting.json',accounting)
    write_search_report(folder,workload,result,rows,accounting)
    return rows, {'status':result.status,'folder':str(folder.resolve()),'accounting':accounting,
                  'search_config':asdict(search_config),'search_file':'joint_search.json'}


def rank_joint_rows(rows, models):
    """Each model has fixed episode references shared by its architecture archive."""
    ranking = []
    for architecture in sorted({row['architecture'] for row in rows}):
        trials = [row for row in rows if row['architecture']==architecture]
        complete = {row['model'] for row in trials}==set(models)
        physical = complete and all(row['constraints']['physical_feasible'] for row in trials)
        feasible = physical and all(row['within_limits'] for row in trials)
        gaps = [limit['relative_excess'] for row in trials for limit in row['constraints']['limits'] if limit['strict']]
        cost = sum(row['cost'] for row in trials)/len(trials) if physical else None
        ranking.append({'architecture':architecture,'feasible_for_all_models':feasible,
            'physical_feasible_for_all_models':physical,'cost':cost,
            'worst_strict_excess':max(gaps,default=0) if physical else None})
    eligible = [row for row in ranking if row['feasible_for_all_models']]
    best = min(eligible,key=lambda row:(row['cost'],row['architecture'])) if eligible else None
    valid = [row for row in ranking if row['physical_feasible_for_all_models']]
    closest = min(valid,key=lambda row:(row['worst_strict_excess'],row['cost'],row['architecture'])) if valid and best is None else None
    selected = best or closest
    return ranking, {'best_architecture':best['architecture'] if best else None,
        'recommended_architecture':best['architecture'] if best else None,
        'closest_architecture':closest['architecture'] if closest else None,
        'display_architecture':selected['architecture'] if selected else None,
        'recommendation_status':'estimated_compliant' if best else 'no_feasible_solution' if closest else 'no_common_executable_candidate',
        'constraint_reports':[dict(model=row['model'],**row['constraints']) for row in rows if selected and row['architecture']==selected['architecture']]}


def run_suite(config, folder, update=lambda **_:None, *, resume=False):
    if config.get('engine_profile')=='gui04_v2':
        from auto_dse import run_auto_suite
        return run_auto_suite(config,folder,update,resume=resume)
    from simple_rapidchiplet.hybrid.models import extract_model
    from simple_rapidchiplet.hybrid.workload import make_toy_workload
    from simple_rapidchiplet.hybrid.hardware import GEMINI_CHIPLET_PROFILE
    folder = Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/'config.json'
    if resume and path.is_file() and json.loads(path.read_text(encoding='utf-8'))!=config:
        raise ValueError('saved suite configuration differs')
    write_json(path,config)
    rows, searches, models = [], {}, {}
    names = config['models']
    for index, model in enumerate(names):
        update(completed=index,total=len(names),message=f'抽取 {model} DAG')
        workload = (make_toy_workload(batch=config['batch'],channels=config.get('toy_channels',8),spatial=config.get('toy_spatial',8))
            if model=='toy' else extract_model(model,config['batch'],input_size=config.get('input_size',224)))
        # Stable model identity is the user's selection, even for Toy's descriptive graph name.
        models[model] = {'layers':len(workload.layers),'macs':workload.total_macs,'fingerprint':workload.fingerprint,'source':workload.source}
        trial_rows, evidence = run_joint_model(config,workload,folder/model,resume=resume,update=update)
        for row in trial_rows:
            row['model']=model
        rows.extend(trial_rows)
        searches[model]=evidence
        write_json(folder/'trials.json',rows)
        update(completed=index+1,total=len(names),rows=rows)
    ranking,recommendation = rank_joint_rows(rows,names)
    selected = recommendation['display_architecture']
    selected_rows = [row for row in rows if row['architecture']==selected]
    recommendation.update(chiplet_profile=GEMINI_CHIPLET_PROFILE,
        recommended_chiplets=selected_rows[0]['hardware_resources']['compute_dies'] if recommendation['best_architecture'] else None,
        closest_chiplets=selected_rows[0]['hardware_resources']['compute_dies'] if selected_rows and not recommendation['best_architecture'] else None,
        candidate_counts=config.get('dies',[1,2,4,8,16]),
        deployments=[{'model':row['model'],'folder':row['folder'],'layout_file':'layout.html'} for row in selected_rows])
    result = {'config':config,'models':models,'runs':rows,'searches':searches,'ranking':ranking,
        'weights':PPA_PREFERENCES[config.get('preference','balanced')],**recommendation,
        'cost_profile':'literature16_v1',
        'objective':'mean across models of fixed-reference weighted L/Lref + A/Aref + P/Pref, plus explicit soft-goal penalties',
        'interpretation':'best feasible design visited within declared templates and finite search budget; analytical PPA'}
    write_json(folder/'suite.json',result)
    write_json(folder/'recommendation.json',recommendation)
    update(completed=len(names),total=len(names),result=result,
        message='完成：找到符合嚴格限制的估算方案' if recommendation['best_architecture'] else '完成：未找到可行解；可檢查最接近方案的違反量')
    return result


def main(argv=None):
    import hybrid_dse
    args = hybrid_dse.parser().parse_args(argv)
    if args.method == 'sa':
        raise ValueError('SA is available with --engine legacy_v2; joint candidate search supports rl/random/greedy')
    if args.hardware or args.mapping:
        raise ValueError('Gemini production engine uses its fixed hardware template and Tangram seed; use --engine legacy_v2 for historical overrides')
    config = {'models':[args.model],'preference':args.preference or 'balanced','batch':args.batch,
        'budget':args.budget,'seed':args.seed,'groups':args.groups,'method':args.method,
        'dies':[args.dies] if args.mode in ('search','evaluate','compare') else list((1,2,4,8,16)),
        'max_power':args.max_power,'max_area':args.max_area,
        'max_latency_ms':None if args.max_latency is None else args.max_latency*1000,
        'strict_power':not args.soft_power,'strict_area':not args.soft_area,'strict_latency':not args.soft_latency,
        'fusion':args.fusion,'fusion_depth':args.fusion_depth,'proposal':args.rl_proposal,
        'input_size':args.input_size,'seed_budget':args.planning_budget,
        'toy_channels':args.toy_channels,'toy_spatial':args.toy_spatial,'pipeline_window':args.pipeline_window}
    if min(args.batch,args.budget,args.planning_budget,args.groups,args.pipeline_window) < 1:
        raise ValueError('batch and budgets must be positive')
    if args.mode=='evaluate':
        config['budget']=1
    if args.workload:
        workload = hybrid_dse.read_workload(args.workload)
        config['batch']=workload.batch_size
        rows,evidence = run_joint_model(config,workload,args.out,resume=args.resume,
            update=lambda **kw:print(kw.get('message',''),flush=True))
        ranking,recommendation=rank_joint_rows(rows,[workload.name])
        write_json(args.out/'recommendation.json',recommendation)
        return 0 if recommendation['best_architecture'] else 2
    if args.mode=='compare':
        experiments=[]
        for seed in (int(value) for value in args.seeds.split(',')):
            for proposal,method in (('atomic','rl'),('guided_atomic','rl'),('composite','rl'),('composite','random'),('composite','greedy')):
                trial={**config,'seed':seed,'proposal':proposal,'method':method}
                result=run_suite(trial,args.out/f'{proposal}_{method}_seed{seed}')
                experiments.append({'seed':seed,'proposal':proposal,'method':method,'ranking':result['ranking'],'searches':result['searches']})
                write_json(args.out/'ablation.json',{'experiments':experiments,'fairness':'same seed initialization, complete evaluator and unique RL query budget; all initialization/report overhead separately recorded'})
        return 0
    result=run_suite(config,args.out,lambda **kw:print(kw.get('message',''),flush=True) if 'message' in kw else None,resume=args.resume)
    print(json.dumps({'status':result['recommendation_status'],'architecture':result['best_architecture'],
        'compute_chiplets':result['recommended_chiplets'],'output':str(args.out.resolve())},ensure_ascii=False))
    return 0 if result['best_architecture'] else 2


if __name__=='__main__':
    raise SystemExit(main())
