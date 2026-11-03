"""Profile one stored, fully specified mapping without parsing a neural model."""
import argparse
import cProfile
import json
from pathlib import Path
import pstats
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simple_rapidchiplet.hybrid.workload import Workload,TensorSpec,LayerSpec
from simple_rapidchiplet.hybrid.rl_schema import DesignState
from simple_rapidchiplet.hybrid.single_array_hardware import enumerate_single_array_architectures_v3
from simple_rapidchiplet.hybrid.single_array_evaluator import SingleArrayEvaluator

def load_workload(path):
    w=json.loads(Path(path).read_text(encoding='utf-8')); keys={'inputs','kernel','stride','padding','dilation','weight_shape','post_ops'}
    return Workload(w['name'],tuple(TensorSpec(**{**t,'shape':tuple(t['shape'])}) for t in w['tensors']),
        tuple(LayerSpec(**{k:tuple(v) if k in keys else v for k,v in l.items()}) for l in w['layers']),
        tuple(w['input_ids']),tuple(w['output_ids']),w['batch_size'],w['source'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--arm',default='seed_only');p.add_argument('--no-profile',action='store_true')
    p.add_argument('--calendar',default='auto',choices=('coalesced','indexed','native','auto'));args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True); w=load_workload(args.case/'workload.json')
    saved=json.loads((args.case/args.arm/'recommendation.json').read_text(encoding='utf-8'));s=DesignState.from_dict(saved['state'])
    candidate=next(c for c in enumerate_single_array_architectures_v3() if c.id==s.architecture_candidate_id)
    oracle=SingleArrayEvaluator(w,candidate.hardware,calendar_backend=args.calendar); prof=cProfile.Profile();start=time.perf_counter()
    if not args.no_profile:prof.enable()
    result=oracle(s.mapping)
    if not args.no_profile:
        prof.disable();prof.dump_stats(str(args.out/'oracle.prof'))
        with (args.out/'profile.txt').open('w',encoding='utf-8') as stream:pstats.Stats(prof,stream=stream).sort_stats('cumtime').print_stats(45)
    comparison={k:dict(old=saved['metrics'].get(k),new=result.metrics.get(k)) for k in (
        'latency_s','energy_j','power_w','area_mm2','executed_macs','dram_read_bytes','dram_write_bytes','noc_hop_bytes','nop_hop_bytes','unit_count')}
    data=dict(elapsed_s=time.perf_counter()-start,metrics=result.metrics,comparison=comparison)
    (args.out/'result.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps(dict(elapsed_s=data['elapsed_s'],feasible=result.metrics['feasible'],phases=result.metrics.get('oracle_phase_wall_s'),comparison=comparison)))

if __name__=='__main__':main()
