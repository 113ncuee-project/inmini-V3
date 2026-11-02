"""Same-hardware balanced baseline versus delivered DP/dataflow/RL mapping."""
from pathlib import Path
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from simple_rapidchiplet.hybrid.models import extract_model
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.preferences import preference_objective
from simple_rapidchiplet.hybrid.report import write_json

FOLDER=ROOT/'simplified_rapidchiplet/results/hybrid_gui_oct09/d09e10000001'


def main():
    suite=json.loads((FOLDER/'suite.json').read_text(encoding='utf-8'))
    architecture=suite['best_architecture']
    objective=preference_objective(suite['config']['preference'])
    reference={key:1.0 for key in ('energy_j','latency_s','power_w','area_mm2')}
    rows=[]
    for run in suite['runs']:
        if run['architecture']!=architecture:
            continue
        hardware=HardwareSpec(**json.loads((Path(run['folder'])/'hardware.json').read_text(encoding='utf-8')))
        workload=extract_model(run['model'],suite['config']['batch'])
        evaluator=HybridEvaluator(workload,hardware,trace=False)
        plan=balanced_mapping(workload,evaluator.package.mapping_core_ids,evaluator.package.memory_ids,
                              max_group_layers=suite['config']['groups'],hardware=hardware)
        baseline=evaluator.evaluate(plan).metrics
        final=run['metrics']
        comparable=baseline['feasible'] and final['feasible']
        delta={}
        if comparable:
            for key in ('latency_s','energy_j','nop_hop_bytes','dram_read_bytes'):
                delta[key]=(final[key]/baseline[key]-1)*100 if baseline[key] else None
            delta['objective']=(objective.cost(final,reference)/objective.cost(baseline,reference)-1)*100
        rows.append({'model':run['model'],'architecture':architecture,'baseline':baseline,'final':final,
                     'comparable':comparable,'change_percent':delta,
                     'interpretation':'same physical hardware and full-batch oracle; balanced vs combined DP/intra-dataflow/RL; not an isolated RL causal gain'})
        print(run['model'],baseline['feasible'],delta,flush=True)
        write_json(FOLDER/'ablation.json',rows)


if __name__=='__main__':
    main()
