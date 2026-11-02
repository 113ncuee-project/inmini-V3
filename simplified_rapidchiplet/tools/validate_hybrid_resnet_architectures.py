"""Full ResNet50 one-sample architecture granularity comparison.

All six candidates retain the same total PE/core/MAC/L1/L2/UB/DRAM budget.
This isolates the balanced initialization across physical candidates; RL
quality curves are a separate experiment.
"""
from dataclasses import asdict
import hashlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simple_rapidchiplet.hybrid.architecture import enumerate_architectures,resource_totals
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.ondie import core_service
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.report import write_json,package_svg
from simple_rapidchiplet.hybrid.workload import extract_resnet50


def pins():
    return {path.name:hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/'simple_rapidchiplet'/'hybrid').glob('*.py')}


def main():
    out = ROOT/'results'/'hybrid_resnet_architectures'
    out.mkdir(parents=True,exist_ok=True)
    workload = extract_resnet50(batch_size=1)
    source = pins()
    rows = []
    for candidate in enumerate_architectures():
        start = time.monotonic()
        print('Starting',candidate.id,flush=True)
        core_service.cache_clear()
        evaluator = HybridEvaluator(workload,candidate.hardware,trace=False)
        plan = balanced_mapping(workload,evaluator.package.mapping_core_ids,evaluator.package.memory_ids,
                                hardware=candidate.hardware,max_group_layers=3,weight_policy='cold')
        result = evaluator(plan)
        folder = out/candidate.id
        folder.mkdir(parents=True,exist_ok=True)
        row = {'id':candidate.id,'folder':str(folder),'hardware':asdict(candidate.hardware),
               'resources':resource_totals(candidate.hardware),'metrics':result.metrics,
               'elapsed_s':time.monotonic()-start,'mapping':plan.to_dict()}
        rows.append(row)
        write_json(folder/'summary.json',row)
        write_json(folder/'buffers.json',result.buffer_statistics)
        write_json(folder/'network.json',evaluator.context.to_dict())
        package_svg(evaluator.package,folder/'package.svg')
        write_json(out/'comparison.json',{'source_before':source,'source_at_result':pins(),'runs':rows,
            'protocol':'fixed balanced initialization; no RL per candidate; whole fixed batch EDP in common physical units'})
        print(candidate.id,result.metrics['feasible'],result.metrics['latency_s'],result.metrics['energy_j'],flush=True)
        if pins() != source:
            raise RuntimeError('Oracle changed during architecture validation')
    write_json(out/'comparison.json',{'source_before':source,'source_after':pins(),'source_stable':pins()==source,
             'completed':True,'runs':rows,'protocol':'equal resource budget; full ResNet50 batch1; fixed balanced initialization, no per-candidate RL'})


if __name__=='__main__':
    main()
