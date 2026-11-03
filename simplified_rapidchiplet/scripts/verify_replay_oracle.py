"""Controlled exact-calendar benchmark and seed/inner counterfactuals.

Uses the original measured seed, one new frozen source snapshot and a global
experiment lock. Runs locally, without a model download or any LLM service.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from run_local_rl_diagnostics import read, write, sources, sha, lock
from profile_mapping_oracle import load_workload
from simple_rapidchiplet.hybrid.rl_schema import DesignState
from simple_rapidchiplet.hybrid.single_array_hardware import enumerate_single_array_architectures_v3
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator
from simple_rapidchiplet.hybrid.mapping_proposals_v4 import StructuredMappings
from replay_mapping_dse import compact, cost


def run(args):
    out, original = args.out, args.run
    config, common = read(original/'effective_config.json'), read(original/'common.json')
    workload=load_workload(Path(config['seed_case'])/'workload.json')
    seed=DesignState.from_dict(common['initial_state'])
    candidate=next(c for c in enumerate_single_array_architectures_v3() if c.id==seed.architecture_candidate_id)
    reference=common['reference']; seed_value=cost(common['metrics'],reference,config['objective'])
    manifest=read(out/'source_snapshot_manifest.json')
    if sources(APP)!=manifest['files']:raise ValueError('snapshot changed')
    result=dict(source_identity=manifest['identity'],source_run=str(original),full_ppa=0,benchmark=[],controls=[],
                interpretation='Exact CPU oracle benchmark and independently charged seed counterfactuals; never added to RL training or search wins.')
    if args.mode in ('benchmark','both'):
        # Alternating fresh evaluators avoids confusing memo warm-up with a
        # calendar speedup. No profiler and no model parsing in either timing.
        for repeat in range(args.repeats):
            for backend in (('coalesced','native') if repeat%2==0 else ('native','coalesced')):
                oracle=SingleArrayEvaluator(workload,candidate.hardware,calendar_backend=backend,
                    deadline=time.monotonic()+args.eval_timeout)
                start=time.perf_counter(); evaluated=oracle(seed.mapping); elapsed=time.perf_counter()-start
                for key in ('latency_s','energy_j','power_w','area_mm2','executed_macs','dram_read_bytes','dram_write_bytes','noc_hop_bytes','nop_hop_bytes'):
                    if evaluated.metrics[key]!=common['metrics'][key]:raise ValueError('benchmark changed physical '+key)
                result['full_ppa']+=oracle.evaluations
                result['benchmark'].append(dict(repeat=repeat,backend=backend,wall_s=elapsed,
                    schedule_s=evaluated.metrics['oracle_phase_wall_s']['schedule'],metrics=compact(evaluated.metrics)))
                write(out/'result.json',result)
        import statistics
        medians={b:statistics.median(r['wall_s'] for r in result['benchmark'] if r['backend']==b) for b in ('coalesced','native')}
        result['benchmark_medians_s']=medians
        result['exact_full_oracle_speedup']=medians['coalesced']/medians['native']
    if args.mode in ('controls','both'):
        bank=StructuredMappings(workload,candidate,seed)
        oracle=SingleArrayEvaluator(workload,candidate.hardware)
        for name,flow,retention in (('original',False,False),('dataflow_inner_only',True,False),
                                    ('retention_auto_only',False,True),('dataflow_and_retention_inner_only',True,True)):
            mappings=tuple(replace(m,
                dataflow=bank.inner_flow(m.layer_id,m.partition.as_tuple()) if flow else m.dataflow,
                weight_policy=bank.retention_policy(m.layer_id,m.partition,m.chiplets,'auto') if retention else m.weight_policy)
                for m in seed.mapping.layer_mappings)
            mapping=replace(seed.mapping,layer_mappings=mappings)
            # The spatial mapping is held fixed: no placement, partition,
            # allocation, group, Fusion or DRAM-flow change is hidden here.
            for a,b in zip(seed.mapping.layer_mappings,mapping.layer_mappings):
                assert replace(a,dataflow=b.dataflow,weight_policy=b.weight_policy)==b
            oracle.deadline=time.monotonic()+args.eval_timeout
            start=time.perf_counter(); before=oracle.evaluations; evaluated=oracle(mapping)
            elapsed=time.perf_counter()-start; value=cost(evaluated.metrics,reference,config['objective'])
            result['full_ppa']+=oracle.evaluations-before
            result['controls'].append(dict(name=name,full_ppa=oracle.evaluations-before,
                exact_cache_hit=oracle.evaluations==before,wall_s=elapsed,metrics=compact(evaluated.metrics),
                cost=value,gain_vs_seed_pct=100*(1-value/seed_value) if value is not None else None,
                state=replace(seed,mapping=mapping).to_dict(),violations=evaluated.metrics.get('violations',[])))
            write(out/'result.json',result)
    result['source_stable']=sources(APP)==manifest['files'];write(out/'result.json',result)
    lines=['# Oracle exactness and attribution controls','',
           'Full PPA (separate from search): '+str(result['full_ppa']),
           'Source stable: '+str(result['source_stable']),'',
           '|Variant|Full PPA|Feasible|Cost improvement %|Latency ms|Energy mJ|Wall s|',
           '|---|---:|---|---:|---:|---:|---:|']
    for r in result['controls']:
        lines.append(f"|{r['name']}|{r['full_ppa']}|{r['metrics']['feasible']}|{r['gain_vs_seed_pct']}|{1000*r['metrics']['latency_s']:.6f}|{1000*r['metrics']['energy_j']:.6f}|{r['wall_s']:.6f}|")
    if result['benchmark']:
        lines+=['','Same source, same exact seed, fresh evaluators, alternating order, no profiler.',
                'Median full oracle speedup: '+str(result['exact_full_oracle_speedup'])]
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('controls','benchmark')},ensure_ascii=False))
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--mode',choices=('benchmark','controls','both'),default='both')
    p.add_argument('--repeats',type=int,default=2);p.add_argument('--eval-timeout',type=float,default=300)
    p.add_argument('--frozen-child',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args();args.run=args.run.resolve();args.out=args.out.resolve()
    if args.repeats<1 or args.eval_timeout<=0:p.error('positive repeats and timeout required')
    if args.frozen_child:return run(args)
    with lock(APP.parent/'output/.local_rl_diagnostics.lock'),lock(args.out/'run.lock'):
        if any(p.name!='run.lock' for p in args.out.iterdir()):raise ValueError('choose a new output; existing evidence is immutable')
        files=sources(APP);snapshot=args.out/'source_snapshot'
        for rel in files:
            target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(APP/rel,target)
        write(args.out/'source_snapshot_manifest.json',dict(identity=sha(files),files=files))
        command=[sys.executable,'-u','-X','utf8',str(snapshot/'scripts/verify_replay_oracle.py'),
            '--frozen-child','--run',str(args.run),'--out',str(args.out),'--mode',args.mode,
            '--repeats',str(args.repeats),'--eval-timeout',str(args.eval_timeout)]
        return subprocess.call(command)


if __name__=='__main__':raise SystemExit(main())
