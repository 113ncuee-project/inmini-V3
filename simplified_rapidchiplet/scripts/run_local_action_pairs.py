"""Budgeted replay of representative chosen actions at their exact before state.

Only invoked by a user-started P3. Two full-oracle requests per pair maximum;
completed durable responses are reused on resume. Failures remain unknown.
"""
import argparse
import gzip
import json
from pathlib import Path
import sys
import time

def main():
    p=argparse.ArgumentParser()
    for flag in ('snapshot','run','out'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--seconds',type=float,required=True)
    p.add_argument('--eval-timeout',type=float,required=True)
    p.add_argument('--max-pairs',type=int,default=5)
    p.add_argument('--stop-file',type=Path)
    args=p.parse_args();sys.path.insert(0,str(args.snapshot))
    from run_local_rl_diagnostics import read,write,sources
    from single_array_dse import exclusive_run,source_identity
    from simple_rapidchiplet.hybrid.workload import Workload,TensorSpec,LayerSpec
    from simple_rapidchiplet.hybrid.single_array_hardware import enumerate_single_array_architectures_v3
    from simple_rapidchiplet.hybrid.single_array_runtime import SingleArrayOraclePool
    from simple_rapidchiplet.hybrid.rl_schema import DesignState,ActionPlan,stable_hash
    from simple_rapidchiplet.hybrid.rl_actions import apply_transaction
    from simple_rapidchiplet.hybrid.rl_search import JointObjective
    from simple_rapidchiplet.hybrid.search_space import check_transition
    if not 1<=args.max_pairs<=10:raise ValueError('max pairs must be 1..10')
    with exclusive_run(args.out):
        manifest=read(args.snapshot/'snapshot_manifest.json')
        if sources(args.snapshot)!=manifest['files']:raise ValueError('source snapshot changed')
        config=read(args.run/'effective_config.json'); w=read(args.run/'workload.json')
        tuple_keys={'inputs','kernel','stride','padding','dilation','weight_shape','post_ops'}
        workload=Workload(w['name'],tuple(TensorSpec(**{**t,'shape':tuple(t['shape'])}) for t in w['tensors']),
            tuple(LayerSpec(**{k:tuple(v) if k in tuple_keys else v for k,v in l.items()}) for l in w['layers']),
            tuple(w['input_ids']),tuple(w['output_ids']),w['batch_size'],w['source'])
        candidates=tuple(c for c in enumerate_single_array_architectures_v3() if not config.get('fixed_architecture') or c.id==config['fixed_architecture'])
        if source_identity(workload,candidates)['identity']!=read(args.run/'source_identity.json')['identity']:
            raise ValueError('source/workload/hardware identity mismatch')
        lookup={c.id:c for c in candidates}; objective=JointObjective(**config['objective'])
        selection=read(args.out/'selection.json')
        if not selection:
            possibilities=[]
            for path in sorted(args.run.glob('*/checkpoint.json')):
                for step in read(path)['trace']:
                    evidence=step.get('candidate_shortlist') or {}
                    file=path.parent/'shortlists'/Path(evidence.get('path','missing')).name
                    if not file.exists():continue
                    raw=json.loads(gzip.decompress(file.read_bytes()))
                    before=raw.get('before_state')
                    if not before:continue
                    before=DesignState.from_dict(before);plan=ActionPlan.from_dict(step['action_plan'])
                    try:
                        after=apply_transaction(workload,before,plan,candidates)
                        check_transition(before,after,config['search_space'],plan)
                    except ValueError:continue
                    b=step.get('before_metrics',{});a=step.get('current_metrics',{})
                    category=('timeout_or_invalid' if not step['valid'] else
                        'recompute_increase' if a.get('recompute_macs',0)>b.get('recompute_macs',0) else
                        'positive_reward' if (step.get('reward') or 0)>0 else 'nonpositive_reward')
                    possibilities.append(dict(id=stable_hash([before.fingerprint,plan.id]),arm=path.parent.name,
                        step=step['step'],category=category,before=before.to_dict(),after=after.to_dict(),action=plan.to_dict(),
                        reference=raw['reference'],shortlist_sha256=evidence.get('sha256')))
            # Round-robin categories, then arm/step; missing categories stay absent.
            categories=('positive_reward','nonpositive_reward','recompute_increase','timeout_or_invalid')
            selected=[];seen=set()
            for index in range(max([sum(r['category']==c for r in possibilities) for c in categories] or [0])):
                for category in categories:
                    rows=[r for r in possibilities if r['category']==category]
                    if index<len(rows) and rows[index]['id'] not in seen and len(selected)<args.max_pairs:
                        selected.append(rows[index]);seen.add(rows[index]['id'])
            selection=dict(pairs=selected,available=len(possibilities),requested=args.max_pairs,
                absent_categories=[c for c in categories if not any(r['category']==c for r in possibilities)],
                source_identity=manifest['identity'],scope='chosen actions at exact before state, not best-to-best')
            write(args.out/'selection.json',selection)
        state=read(args.out/'summary.json',dict(pairs=[],elapsed_s=0))
        if state.get('status')=='completed':return
        started=time.monotonic();deadline=started+max(0,args.seconds-state['elapsed_s'])
        pool=SingleArrayOraclePool(workload,args.out/'worker',deadline=deadline,evaluation_timeout_s=args.eval_timeout)
        stopped=False
        try:
            for pair in selection['pairs']:
                row=next((r for r in state['pairs'] if r['id']==pair['id']),None)
                if row and row.get('status') in ('completed','incomplete_or_infeasible'):continue
                if args.stop_file and args.stop_file.exists():stopped=True;break
                if time.monotonic()>=deadline:break
                if row is None:
                    row=dict(id=pair['id'],arm=pair['arm'],step=pair['step'],category=pair['category'],metrics={},errors=[])
                    state['pairs'].append(row)
                for label in ('before','after'):
                    if label in row['metrics']:continue
                    if args.stop_file and args.stop_file.exists():stopped=True;break
                    design=DesignState.from_dict(pair[label])
                    try:
                        response=pool.evaluate(lookup[design.architecture_candidate_id],design.mapping,phase='chosen_action_pair')
                        row['metrics'][label]=response['metrics']
                    except (ValueError,RuntimeError,TimeoutError) as error:
                        row['errors'].append(dict(intervention=label,reason=str(error),physical_validity='unknown_without_completed_PPA'))
                    state['elapsed_s']+=time.monotonic()-started;started=time.monotonic()
                    write(args.out/'summary.json',state)
                if stopped:break
                matched=all(row['metrics'].get(k,{}).get('feasible') for k in ('before','after'))
                row['status']='completed' if matched else 'incomplete_or_infeasible'
                row['delta']={k:row['metrics']['after'][k]-row['metrics']['before'][k] for k in (
                    'latency_s','energy_j','power_w','area_mm2','dram_read_bytes','dram_write_bytes','noc_hop_bytes','nop_hop_bytes',
                    'executed_macs','recompute_macs','l1_l2_service_bytes')} if matched else None
                row['cost_delta']=objective.cost(row['metrics']['after'],pair['reference'])-objective.cost(row['metrics']['before'],pair['reference']) if matched else None
                write(args.out/'summary.json',state)
        finally:
            pool.close();state['elapsed_s']+=time.monotonic()-started
            state['extra_full_ppa']=pool.full_evaluations
            state['status']='interrupted' if stopped else 'completed' if len(state['pairs'])==len(selection['pairs']) else 'budget_exhausted'
            state['unattempted_pairs']=len(selection['pairs'])-len(state['pairs'])
            state['scope']='same before mapping plus selected ordered edits; paired analytical oracle; no silicon claim'
            write(args.out/'summary.json',state)
        if stopped:raise SystemExit(130)

if __name__=='__main__':main()
