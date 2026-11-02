"""Bounded communication-aware interval DP for tile/fusion/overlap scheduling.

Outer Part/CG/FD are fixed. Closed segments are nodes; boundary tensors use paid
DRAM materialization. Local region traffic and bank/core service form an E/T
proposal proxy; only full-plan oracle evaluation decides feasibility and reward.
EDP is never summed. Proxy Pareto + beam pruning is explicitly approximate.
"""
from dataclasses import replace
import math

from .depth_first import OVERLAP_MODES, legal_stack
from .mapping import FusionStack, LayerGroup, MappingPlan
from .workload import Workload


def segment_plan(base, ids, tile=None, overlap='full_cache'):
    cores = [core for lid in ids for core in base.mapping_map[lid].chiplets]
    mode = 'spatial' if len(cores)==len(set(cores)) else 'temporal'
    group = LayerGroup('df_'+'_'.join(ids),tuple(ids),mode)
    return MappingPlan((group,),tuple(base.mapping_map[lid] for lid in ids),base.microbatch_size,
                       base.collective,base.memory_ids,
                       (FusionStack(tuple(ids),tuple(tile),overlap),) if tile else ())


def _local_workload(workload, ids):
    members = set(ids)
    layers = tuple(workload.layer_map[lid] for lid in ids)
    needed = {t for layer in layers for t in (*layer.inputs,layer.output)}
    external = tuple(t.id for t in workload.tensors if t.id in needed and t.producer not in members)
    tensors = tuple(replace(t,producer='' if t.id in external else t.producer)
                    for t in workload.tensors if t.id in needed)
    return Workload(workload.name+':segment',tensors,layers,external,(layers[-1].output,),workload.batch_size,'DF proposal')


def _proxy(workload, plan, evaluator, outer):
    local = _local_workload(workload,plan.groups[0].layer_ids)
    # The source of a boundary input is the original producer's output FD,
    # even when the consumer's input FD differs. External model input uses IF.
    mappings = []
    for item in plan.layer_mappings:
        layer = workload.layer_map[item.layer_id]
        producers = [workload.tensor_map[t].producer for t in layer.inputs
                     if workload.tensor_map[t].producer not in plan.group_map and workload.tensor_map[t].producer]
        selectors = [outer.mapping_map[p].output_dram for p in producers]
        mappings.append(replace(item,input_dram=selectors[0]) if len(set(selectors))==1 else item)
    plan = replace(plan,layer_mappings=tuple(mappings))
    import json
    key=(local.fingerprint,json.dumps(plan.to_dict(),sort_keys=True),
         tuple((lid,outer.mapping_map[lid].output_dram) for lid in
               sorted({workload.tensor_map[t].producer for layer in local.layers for t in layer.inputs
                       if workload.tensor_map[t].producer and workload.tensor_map[t].producer not in plan.group_map})))
    if not hasattr(evaluator,'df_segment_cache'):
        evaluator.df_segment_cache={}; evaluator.df_segment_evaluations=0
    if key in evaluator.df_segment_cache:
        value=evaluator.df_segment_cache[key]
        if value is None:
            raise ValueError('cached local capacity violation')
        return value
    # Reuse the same physical package context without invoking Rapid again.
    # Each local node runs the real service/calendar/capacity model. Its E/T is
    # still a global proposal proxy: branch-boundary sources may differ and
    # whole-DAG lifetimes must be checked in the final full-model evaluation.
    import copy
    node_oracle=copy.copy(evaluator)
    node_oracle.workload=local; node_oracle.cache={}; node_oracle.evaluations=0
    evaluator.df_segment_evaluations+=1
    result=node_oracle.evaluate(plan,retain_trace=False)
    if not result.metrics['feasible']:
        evaluator.df_segment_cache[key]=None
        raise ValueError('local fusion/cache node exceeds physical capacity')
    value=(result.metrics['energy_j'],result.metrics['latency_s'],result.metrics['unit_count'])
    if len(evaluator.df_segment_cache)>=4096:
        evaluator.df_segment_cache.pop(next(iter(evaluator.df_segment_cache)))
    evaluator.df_segment_cache[key]=value
    return value


def fusion_proposals(workload, base, evaluator, *, tiles=((8,8),(16,16)), max_depth=4,
                     beam_width=6, max_units=12000, exhaustive=False):
    if max_depth<1 or beam_width<1 or max_units<1 or not tiles or any(len(t)!=2 or any(type(v)!=int or v<1 for v in t) for t in tiles):
        raise ValueError('invalid fusion search bounds')
    # Store fixed boundary ownership in each frontier identity. Closed nodes
    # cannot export intermediates, so grouping history behind it is irrelevant
    # to future source locations. Cross-node pipeline overlap is not assumed.
    order = tuple(layer.id for layer in workload.layers)
    frontier = {0:[(0.0,0.0,(),())]}
    cache = {}; transitions = rejected = 0
    node_queries_before=getattr(evaluator,'df_segment_evaluations',0)
    for end in range(1,len(order)+1):
        rows = []
        for start in range(max(0,end-max_depth),end):
            ids = order[start:end]
            if start not in frontier or (len(ids)>1 and not legal_stack(workload,ids)):
                continue
            choices = [(None,'full_cache')] if len(ids)==1 else [(tile,mode) for tile in tiles for mode in OVERLAP_MODES]
            for tile,mode in choices:
                segment = segment_plan(base,ids,tile,mode)
                key = (ids,tile,mode)
                try:
                    if key not in cache:
                        cache[key] = _proxy(workload,segment,evaluator,base)
                    e,t,n = cache[key]
                except ValueError:
                    rejected += 1; continue
                if n>max_units:
                    rejected += 1; continue
                for pe,pt,groups,stacks in frontier[start]:
                    rows.append((pe+e,pt+t,(*groups,*segment.groups),(*stacks,*segment.fusion_stacks)))
                    transitions += 1
        if not exhaustive:
            # Proxy dominance only, not a guarantee about full oracle outcomes.
            rows.sort(key=lambda row:(row[0],row[1]))
            pareto=[]; best_t=math.inf
            for row in rows:
                if row[1]<best_t:
                    pareto.append(row); best_t=row[1]
            if len(pareto)>beam_width:
                indices={round(i*(len(pareto)-1)/(beam_width-1)) for i in range(beam_width)} if beam_width>1 else {len(pareto)//2}
                pareto=[row for i,row in enumerate(pareto) if i in indices]
            rows=pareto
        frontier[end]=rows
    proposals = [base]
    for e,t,groups,stacks in sorted(frontier[len(order)],key=lambda row:row[0]*row[1]):
        candidate = replace(base,groups=groups,fusion_stacks=stacks)
        if candidate not in proposals:
            proposals.append(candidate)
    return tuple(proposals), {'method':'closed-subgraph tile/fusion/reuse interval DP',
        'approximate':not exhaustive,'proxy_is_final_ppa':False,'proxy_pareto_is_safe_for_full_ppa':False,
        'boundary':'fixed Part/CG/output-FD; external DAG tensors materialized in DRAM',
        'tiles':tiles,'max_depth':max_depth,'beam_width':beam_width,'transitions':transitions,
        'segment_evaluations':len(cache),'rejected_segments':rejected,'proposal_count':len(proposals),
        'segment_oracle_queries':getattr(evaluator,'df_segment_evaluations',0)-node_queries_before,
        'node_cost':'shared physical oracle on isolated subgraph; capacity-gated; E/T retained separately',
        'cache_placement':'capacity-backed UB; local reuse copies are paid',
        'scope':'single-exit closed DAG segments, row-major tiles, three overlap modes'}


def select_fusion_plan(workload, base, evaluator, objective, *, query_budget=6, **bounds):
    if query_budget<1:
        raise ValueError('positive inner oracle budget required')
    candidates,evidence = fusion_proposals(workload,base,evaluator,**bounds)
    # Preserve no-fusion fallback. All selected rows use identical E/T/P/A scales.
    reference={key:1.0 for key in ('energy_j','latency_s','area_mm2','power_w')}
    rows=[]
    for plan in candidates[:query_budget]:
        try:
            result=evaluator.evaluate(plan,retain_trace=False)
            metrics=result.metrics
        except ValueError as error:
            metrics={'feasible':False,'evaluation_error':str(error),'violations':[str(error)]}
        rows.append((objective.cost(metrics,reference),plan,metrics))
    best=min(rows,key=lambda row:row[0])
    evidence.update(full_oracle_queries=len(rows),oracle_query_budget=query_budget,
                    selected_has_fusion=bool(best[1].fusion_stacks),
                    candidates=[{'cost':cost if math.isfinite(cost) else None,'groups':len(plan.groups),
                                 'stacks':plan.to_dict()['fusion_stacks'],'metrics':metrics} for cost,plan,metrics in rows])
    return best[1] if math.isfinite(best[0]) else base,evidence


class HierarchicalEvaluator:
    """RL proposes Part/CG/FD; deterministic inner DP completes each proposal."""
    def __init__(self,evaluator,objective,*,query_budget=6,**bounds):
        self.oracle=evaluator; self.objective=objective; self.query_budget=query_budget
        self.bounds=bounds; self.cache={}; self.inner_queries=0; self.segment_queries=0

    def evaluate(self,plan):
        import json
        # Keep the legal outer action domain; fusion cuts are inner decisions.
        base=plan
        key=json.dumps(base.to_dict(),sort_keys=True)
        if key not in self.cache:
            selected,evidence=select_fusion_plan(self.oracle.workload,base,self.oracle,self.objective,
                                                 query_budget=self.query_budget,**self.bounds)
            self.inner_queries+=evidence['full_oracle_queries']
            self.segment_queries+=evidence['segment_oracle_queries']
            self.cache[key]=(selected,evidence)
        selected,evidence=self.cache[key]
        return self.oracle.evaluate(selected,retain_trace=False)

    __call__=evaluate

    def resolve(self,plan):
        self.evaluate(plan)
        import json
        base=plan
        return self.cache[json.dumps(base.to_dict(),sort_keys=True)]


def bounded_window_dp(workload, base, hardware, ids, *, tiles=((8,8),(16,16),(32,32),(64,64)),
                      max_depth=4, beam_width=3, unit_cap=512, transition_cap=48,max_proxy_s=None):
    """Cheap bounded local DP proposals, never a full PPA or hidden completion.

    Fixed Part/CG/FD. Proxy uses exact compiled local regions/MACs and simple
    unoverlapped bandwidth/compute bounds; global lifetimes/cache/schedule must
    still pass HybridEvaluator. Bounds are heuristic proposal pruning only.
    """
    from collections import defaultdict,Counter
    from .mapping import compile_mapping
    import time
    started=time.perf_counter();ids=tuple(ids);local=_local_workload(workload,ids)
    frontier={0:[(0.,0.,(),())]};reasons=Counter();depths=Counter();queries=0
    cache={};retained=[]
    def choices_for(members):
        if len(members)==1:return [(None,'recompute')]
        sink=workload.tensor_map[workload.layer_map[members[-1]].output]
        canonical=tuple(dict.fromkeys((min(t[0],sink.shape[2]),min(t[1],sink.shape[3])) for t in tiles))
        return [(tile,mode) for tile in canonical for mode in OVERLAP_MODES]
    def node(members,tile,mode):
        nonlocal queries
        key=members,tile,mode
        if key in cache:return cache[key]
        if max_proxy_s is not None and time.perf_counter()-started>=max_proxy_s:
            reasons['local_proxy_time_ceiling']+=1;return None
        if queries>=transition_cap:
            reasons['local_transition_ceiling']+=1;return None
        sink=workload.tensor_map[workload.layer_map[members[-1]].output]
        if tile and math.ceil(sink.shape[2]/tile[0])*math.ceil(sink.shape[3]/tile[1])*len(members)>unit_cap:
            reasons['estimated_unit_ceiling_heuristic']+=1;return None
        queries+=1
        try:
            part=segment_plan(base,members,tile,mode)
            sub=_local_workload(workload,members);compiled=compile_mapping(sub,part,hardware)
            if len(compiled.units)>unit_cap:
                reasons['compiled_unit_ceiling']+=1;cache[key]=None;return None
            per_core=defaultdict(int);external=internal=0
            for u in compiled.units:
                per_core[u.chiplet]+=u.macs
                for req in u.inputs:
                    amount=req.region.elements*sub.tensor_map[req.tensor_id].bytes_per_element
                    if sub.tensor_map[req.tensor_id].producer in members:internal+=amount
                    else:external+=amount
                if u.weight_region:external+=u.weight_region.elements*hardware.weight_bits/8
                if u.layer_id==members[-1]:external+=u.output_bytes
            macs=sum(per_core.values())
            t=max(per_core.values(),default=0)/hardware.per_core_mac_rate+external/(hardware.dram_bandwidth_Bps*len(base.memory_ids))+internal/hardware.noc_bandwidth_Bps
            e=macs*hardware.effective_mac_energy_pj*1e-12+external*8*hardware.dram_energy_pj_per_bit*1e-12+internal*8*hardware.noc_energy_pj_per_bit*1e-12
            cache[key]=(max(e,1e-30),max(t,1e-30),part);depths[len(members)]+=1
            return cache[key]
        except (ValueError,KeyError) as error:
            reasons['compile_rejected:'+str(error)[:100]]+=1;cache[key]=None;return None
    # Reserve the no-fusion path, and evaluate some 0->N edges before shorter
    # prefixes exhaust the finite budget. These are real interval-DP edges.
    for lid in ids:node((lid,),None,'recompute')
    if 3<len(ids)<=max_depth and legal_stack(workload,ids):
        for tile,mode in sorted(choices_for(ids),key=lambda x:-(x[0][0]*x[0][1]))[:6]:node(ids,tile,mode)
    for end in range(1,len(ids)+1):
        rows=[]
        for start in range(max(0,end-max_depth),end):
            members=ids[start:end]
            if start not in frontier or not frontier[start]:continue
            if len(members)>1 and not legal_stack(workload,members):
                reasons['not_closed_single_exit']+=1;continue
            for tile,mode in choices_for(members):
                value=node(members,tile,mode)
                if value is None:continue
                e,t,part=value
                for pe,pt,groups,stacks in frontier[start]:
                    rows.append((pe+e,pt+t,(*groups,*part.groups),(*stacks,*part.fusion_stacks)))
        rows.sort(key=lambda r:r[0]*r[1])
        # Keep a representative for each observed depth, plus the lowest E*T
        # proposals. This preserves fusion exploration, not a reward bonus.
        kept=[];seen=set();seen_plans=set()
        for row in rows:
            plan_key=row[2:]
            if plan_key in seen_plans:continue
            seen_plans.add(plan_key)
            depth=max((len(s.layer_ids) for s in row[3]),default=1)
            if len(kept)<beam_width or depth not in seen:
                kept.append(row);seen.add(depth)
            if len(kept)>=beam_width+max_depth:break
        frontier[end]=kept
    for e,t,groups,stacks in frontier.get(len(ids),[]):
        if not stacks:continue
        # Splice the explicitly selected interval back into the full graph,
        # splitting original boundary groups where necessary.
        indices={lid:i for i,lid in enumerate(layer.id for layer in workload.layers)}
        lo,hi=indices[ids[0]],indices[ids[-1]];changed=[];inserted=False
        for group in base.groups:
            before=tuple(l for l in group.layer_ids if indices[l]<lo)
            after=tuple(l for l in group.layer_ids if indices[l]>hi)
            touching=any(l in ids for l in group.layer_ids)
            if not touching:changed.append(group);continue
            if before:changed.append(LayerGroup(group.id+'_pre',before,group.mode))
            if not inserted:changed.extend(groups);inserted=True
            if after:changed.append(LayerGroup(group.id+'_post',after,group.mode))
        candidate=replace(base,groups=tuple(changed),fusion_stacks=(*base.fusion_stacks,*stacks))
        if candidate not in retained:retained.append(candidate)
    singles=[cache.get(((lid,),None,'recompute')) for lid in ids]
    baseline_e=sum(x[0] for x in singles if x);baseline_t=sum(x[1] for x in singles if x)
    improvements=sum(e*t<baseline_e*baseline_t for e,t,g,s in frontier.get(len(ids),[]) if s) if all(singles) else 0
    return tuple(retained),{'method':'bounded local interval DP with compiled-region proxy','proxy_is_final_ppa':False,
        'global_reward_unchanged':True,'full_evaluator_calls':0,'local_compile_queries':queries,
        'elapsed_s':time.perf_counter()-started,'max_depth':max_depth,'depth_coverage':dict(depths),
        'pruned_or_rejected':dict(reasons),'proposals':len(retained),'window':ids,'proxy_improvement_candidates':improvements,
        'limits':{'beam_width':beam_width,'unit_cap':unit_cap,'transition_cap':transition_cap}}
