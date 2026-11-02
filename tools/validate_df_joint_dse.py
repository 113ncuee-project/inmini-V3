"""Reproducible algorithm/cost evidence; no pretrained weights or downloads."""
from dataclasses import replace
from pathlib import Path
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet/tests'))
import hybrid_dse
from test_hybrid_depth_first import chain,plan_for,numerical_replay
from simple_rapidchiplet.hybrid.models import extract_model
from simple_rapidchiplet.hybrid.depth_first import legal_stack,OVERLAP_MODES
from simple_rapidchiplet.hybrid.fusion_planner import _local_workload
from simple_rapidchiplet.hybrid.mapping import FusionStack,LayerGroup,LayerMapping,MappingPlan,compile_mapping
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.report import save_evaluation,write_json


def main():
    out=ROOT/'output/df_joint_20261011';out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();evidence={}
    hw=HardwareSpec(cluster_rows=1,cluster_cols=1,compute_per_cluster=2,unified_buffer_bytes=2**20)
    w=chain(8,residual=True);ev=HybridEvaluator(w,hw,trace=False)
    rows=[]
    for mode in OVERLAP_MODES:
        plan=plan_for(w,mode,tile=(2,2),multidie=True)
        result=ev.evaluate(plan,retain_trace=True)
        numerical_replay(w,result.compiled)
        assert result.metrics['feasible'] and result.schedule.validate()
        save_evaluation(out/'residual_modes'/mode,result,ev,plan)
        rows.append({'mode':mode,'metrics':result.metrics})
    evidence['numerically_verified_residual_modes']=rows
    # Real torchvision ResNet50 bottleneck shape/branch graph at 32x32 input.
    full=extract_model('resnet50',input_size=32)
    ids=tuple(l.id for l in full.layers if l.id.startswith('layer1_0'))
    # FX Add IDs are not module paths: extend until the first matching Add.
    first=next(i for i,l in enumerate(full.layers) if l.id.startswith('layer1_0'))
    last=next(i for i,l in enumerate(full.layers[first:],first) if l.kind=='Add')
    ids=tuple(l.id for l in full.layers[first:last+1])
    assert legal_stack(full,ids)
    local=_local_workload(full,ids)
    ev=HybridEvaluator(local,hw,trace=False)
    mappings=tuple(LayerMapping(lid,(f'compute:{i%2}/core:0',),weight_policy='persistent') for i,lid in enumerate(ids))
    bottleneck=[]
    for mode in OVERLAP_MODES:
        plan=MappingPlan((LayerGroup('bottleneck',ids,'temporal'),),mappings,memory_ids=('memory:0',),
                         fusion_stacks=(FusionStack(ids,(4,4),mode),))
        result=ev.evaluate(plan,retain_trace=True)
        assert result.metrics['feasible'] and result.schedule.validate()
        save_evaluation(out/'resnet50_bottleneck'/mode,result,ev,plan)
        bottleneck.append({'mode':mode,'metrics':result.metrics})
    evidence['resnet50_bottleneck']={'full_model_input_size':32,'layers':ids,'rows':bottleneck,
                                   'scope':'real FX operator shapes, isolated bottleneck PPA; no numerical accuracy claim for quantized ResNet'}
    # Full CLI integration on the same workload/hardware and budget, four methods.
    w=hybrid_dse.make_toy_workload(batch=1,channels=2,spatial=6)
    args=hybrid_dse.parser().parse_args(['--model','toy','--batch','1','--toy-channels','2','--toy-spatial','6',
         '--planner','traffic_dp','--fusion','dp','--fusion-tiles','2x2,4x4','--fusion-budget','4',
         '--budget','3','--max-per-operator','2'])
    spec=HardwareSpec(); trials=[]
    for method in ('rl','greedy','sa','random'):
        row=hybrid_dse.run_one(args,w,spec,out/'methods'/method,method=method)
        assert row['metrics']['feasible'];trials.append(row)
    evidence['methods']=trials
    args.budget=2
    hybrid_dse.run_one(args,w,spec,out/'resume',method='rl')
    args.budget=3;args.resume=True
    resumed=hybrid_dse.run_one(args,w,spec,out/'resume',method='rl')
    straight=trials[0]
    a=json.loads((out/'resume/checkpoint.json').read_text(encoding='utf8'))
    b=json.loads((out/'methods/rl/checkpoint.json').read_text(encoding='utf8'))
    for key in ('best_plan','best_metrics','current_plan','policy','rng_state','evaluations','steps'):
        assert a[key]==b[key],key
    evidence['exact_resume_2_to_3']=True
    evidence['elapsed_s']=time.monotonic()-started
    evidence['source_sha256']=ev.source_hashes
    write_json(out/'validation.json',evidence)
    print(json.dumps({'modes':len(rows),'real_bottleneck_modes':len(bottleneck),'methods':len(trials),
                      'exact_resume':True,'elapsed_s':evidence['elapsed_s']},ensure_ascii=False))


if __name__=='__main__':main()
