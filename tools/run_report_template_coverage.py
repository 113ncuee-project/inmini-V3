"""Supplementary actual full-evaluator coverage; never called production RL."""
import sys,json,time,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'simplified_rapidchiplet'
sys.path.insert(0,str(APP))
from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.models import extract_model
from simple_rapidchiplet.hybrid.tangram_seed import build_tangram_seed
from simple_rapidchiplet.hybrid.report import write_json,save_evaluation
from rl_dse import make_objective,source_identity

out=ROOT/'output/detailed_project_report_20261031/template_coverage'
out.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--finalize-known',action='store_true',help='Finalize completed evidence; do not launch any further template evaluation')
args=parser.parse_args()
config={'models':['resnet18'],'batch':1,'input_size':224,'preference':'low_latency',
        'max_power':40.,'max_area':500.,'max_latency_ms':.8,'strict_power':True,'strict_area':True,'strict_latency':True,
        'fusion':'off','protocol':'15-template coverage, area validity screen and at most one bounded Tangram seed per remaining template; earlier completed evaluations are reused; no RL in this supplementary audit'}
write_json(out/'config.json',config)
workload=extract_model('resnet18',1,input_size=224);objective=make_objective(config)
saved=json.loads((out/'results.json').read_text(encoding='utf-8')) if (out/'results.json').is_file() else {}
rows=list(saved.get('rows',[]));reference=next((r['metrics'] for r in rows if 'metrics' in r),{});best=None;started=time.perf_counter();identity=source_identity()
done={r['architecture'] for r in rows}
for candidate in enumerate_gemini_architectures():
    if candidate.id in done:continue
    area=sum(n.width_mm*n.height_mm for n in candidate.package.nodes.values())
    if area>config['max_area']:
        rows.append({'architecture':candidate.id,'hard_pruned_area':True,'silicon_area_mm2':area,
                     'strict_feasible':False,'seed_queries':0,'reason':'fixed physical silicon area exceeds hard area limit; no latency/power fabricated'})
        write_json(out/'results.json',{'config':config,'rows':rows,'elapsed_s':time.perf_counter()-started,
                   'source_identity':identity,'source_stable':identity==source_identity()})
        print(candidate.id,'hard area prune',flush=True)
        continue
    if args.finalize_known:
        rows.append({'architecture':candidate.id,'not_completed':True,'silicon_area_mm2':area,
                     'strict_feasible':None,'reason':'supplementary audit stopped after prolonged 16-chiplet evaluation; no completed mapping PPA claimed'})
        continue
    tick=time.perf_counter();evaluator=HybridEvaluator(workload,candidate.hardware,trace=False)
    try:
        seed=build_tangram_seed(workload,evaluator.package.mapping_core_ids,evaluator.package.memory_ids,
            candidate.hardware,evaluator=evaluator,microbatch_sizes=(1,),max_group_layers=3,
            max_candidates=1,max_evaluations=1)
        row={'architecture':candidate.id,'compute':candidate.hardware.compute_count,
             'rows':candidate.hardware.cluster_rows,'cols':candidate.hardware.cluster_cols,
             'seed_queries':seed.evaluator_queries,'seed_status':seed.status}
        if seed.plan is not None:
            m=seed.metrics
            if not reference:reference.update(m)
            row.update(metrics=m,strict_feasible=objective.strict_feasible(m),violation=objective.violation(m),
                       fixed_reference_cost=objective.cost(m,reference))
            rank=(not row['strict_feasible'],row['violation'],row['fixed_reference_cost'])
            if best is None or rank<best[0]:best=(rank,candidate,seed.plan,evaluator)
            write_json(out/candidate.id/'mapping.json',seed.plan.to_dict())
            write_json(out/candidate.id/'hardware.json',candidate.hardware.to_dict())
        row['elapsed_s']=time.perf_counter()-tick
        rows.append(row)
    except Exception as exc:
        rows.append({'architecture':candidate.id,'error':f'{type(exc).__name__}: {exc}','elapsed_s':time.perf_counter()-tick})
    write_json(out/'results.json',{'config':config,'rows':rows,'elapsed_s':time.perf_counter()-started,
               'source_identity':identity,'source_stable':identity==source_identity()})
    print(candidate.id,rows[-1].get('strict_feasible'),round(time.perf_counter()-tick,2),flush=True)
valid=[r for r in rows if 'metrics' in r]
write_json(out/'results.json',{'config':config,'rows':rows,'elapsed_s_this_finalize_process':time.perf_counter()-started,
    'completed_evaluation_wall_s':sum(r.get('elapsed_s',0) for r in rows),
    'status':'partial' if any(r.get('not_completed') for r in rows) else 'complete',
    'source_identity':identity,'source_stable':identity==source_identity()})
if valid:
    chosen=min(valid,key=lambda r:(not r['strict_feasible'],r['violation'],r['fixed_reference_cost']))
    candidate=next(c for c in enumerate_gemini_architectures() if c.id==chosen['architecture'])
    from simple_rapidchiplet.hybrid.search import plan_from_dict
    plan=plan_from_dict(json.loads((out/candidate.id/'mapping.json').read_text(encoding='utf-8')))
    evaluator=HybridEvaluator(workload,candidate.hardware,trace=False)
    ev=evaluator.evaluate(plan,retain_trace=True)
    save_evaluation(out/'selected',ev,evaluator,plan,planning={'method':config['protocol']},arguments=config)
    write_json(out/'best.json',{'architecture':candidate.id,'strict_feasible':objective.strict_feasible(ev.metrics),
        'metrics':ev.metrics,'screened_templates':len(rows),'evaluated_templates':len(valid),
        'hard_pruned_templates':sum(bool(r.get('hard_pruned_area')) for r in rows),
        'not_completed_templates':sum(bool(r.get('not_completed')) for r in rows),'source_identity':identity,
        'source_stable':identity==source_identity(),'elapsed_s':time.perf_counter()-started,
        'note':'supplementary template coverage result, not the output of the limited-budget production RL episode'})
