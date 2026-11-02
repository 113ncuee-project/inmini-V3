"""Versioned GUI04 proposal extension; no PPA modification or policy bonus."""
from collections import Counter
import time
from .depth_first import legal_stack
from .fusion_planner import bounded_window_dp
from .mapping import enumerate_partitions
from .rl_actions import make_action_plan,apply_transaction,_has_overlap
from .rl_schema import ActionEdit

class AutoProposals:
    version='bounded_window_dp_v1'
    def __init__(self,workload,candidates,config):
        self.workload=workload;self.candidates={c.id:c for c in candidates};self.config=config
        self.calls=0;self.depth_cap=config['fusion_depth'];self.history=[]
        self.deadline=None
    def state_dict(self):return {'calls':self.calls,'depth_cap':self.depth_cap,'history':self.history}
    def load_state_dict(self,data):
        self.calls=data['calls'];self.depth_cap=data['depth_cap'];self.history=data['history']
    def __call__(self,state,report,plans,stats):
        self.calls+=1;extra=[];rejected=Counter();depths=Counter();dp=[]
        hw=self.candidates[state.architecture_candidate_id].hardware
        # Give both spatial-output (weight sharing) and channel-output
        # (activation sharing) A2 directions access to the same shortlist.
        layers=[x for x in state.mapping.layer_mappings if len(x.chiplets)>1]
        if layers:
            item=layers[(self.calls-1)%len(layers)]
            opts=enumerate_partitions(self.workload,item.layer_id,len(item.chiplets),state.mapping.microbatch_size)
            for name,options in [('weight_shared_P',[p for p in opts if p.k==1 and p.h*p.w>1]),
                                 ('activation_shared_K',[p for p in opts if p.k>1 and p.h*p.w==1])]:
                if not options:continue
                part=options[(self.calls-1)%len(options)]
                if part==item.partition:continue
                extra.append(make_action_plan(state,'A2',[ActionEdit('A2',{'layer_id':item.layer_id,'partition':list(part.as_tuple())})],
                    targets=(item.layer_id,),reason='balanced partition coverage: '+name,sources=('GUI04 engineering proposal',)))
        if self.config.get('fusion')!='off' and self.config.get('local_fusion_dp',True):
            fused={lid for stack in state.mapping.fusion_stacks for lid in stack.layer_ids}
            order=[l.id for l in self.workload.layers];windows=[]
            depth_order=(self.depth_cap,3,2) if self.depth_cap>4 and self.calls%3==1 else (min(3,self.depth_cap),2,self.depth_cap)
            for depth in depth_order:
                options=[tuple(order[i:i+depth]) for i in range(len(order)-depth+1)
                         if not fused.intersection(order[i:i+depth]) and legal_stack(self.workload,order[i:i+depth])]
                if options:
                    ids=options[(self.calls-1)%len(options)]
                    if ids not in windows:windows.append(ids)
            # A bounded local DP completes explicit candidate groups/stacks;
            # it never overwrites a mapping behind the actor's back.
            for ids in windows[:2]:
                proposed,evidence=bounded_window_dp(self.workload,state.mapping,hw,ids,
                    max_depth=self.depth_cap,transition_cap=36,unit_cap=256,
                    max_proxy_s=min(self.config.get('local_dp_timeout_s',3.),max(0,self.deadline-time.monotonic()) if self.deadline else float('inf')))
                dp.append(evidence)
                for mapping in proposed[:4]:
                    edits=[ActionEdit('A10',{'groups':[{'id':g.id,'layer_ids':list(g.layer_ids),'mode':g.mode} for g in mapping.groups]})]
                    for stack in mapping.fusion_stacks:
                        if stack in state.mapping.fusion_stacks:continue
                        if stack.overlap!='recompute' and not _has_overlap(self.workload,stack.layer_ids):continue
                        flags={'recompute':(False,False),'horizontal_cache':(True,False),'full_cache':(True,True)}
                        h,v=flags.get(stack.overlap,(False,False))
                        edits.append(ActionEdit('A1',{'operation':'merge','layer_ids':list(stack.layer_ids),
                            'tile_hw':list(stack.tile_hw),'cache_h':h,'cache_v':v}))
                        depths[len(stack.layer_ids)]+=1
                    if len(edits)>1:extra.append(make_action_plan(state,'C6',edits,targets=ids,
                        reason='bounded local fusion DP proposal; full global evaluator decides reward',sources=('DeFiNES','GUI04 engineering proposal')))
            if self.config.get('adaptive_depth') and self.calls%3==0 and any(x.get('proxy_improvement_candidates') for x in dp):
                self.depth_cap=min(self.config.get('fusion_depth_max',8),len(order),self.depth_cap+2)
        seen=set();valid=[]
        # Keep the bounded extra depth/partition directions without duplicating equivalent
        # transitions. Remaining slots retain generic/diagnostic exploration.
        for p in (*extra,*plans):
            try:trial=apply_transaction(self.workload,state,p,self.candidates)
            except (ValueError,KeyError,TypeError,IndexError) as error:
                rejected[str(error)[:120]]+=1;continue
            if trial.fingerprint==state.fingerprint or trial.fingerprint in seen:continue
            seen.add(trial.fingerprint);valid.append(p)
        valid=valid[:self.config.get('shortlist',48)]
        evidence={'depth_cap':self.depth_cap,'proposed_depths':dict(depths),'local_dp':dp,
                  'rejected':dict(rejected),'additional_proposals':len(extra),
                  'selected_families':dict(Counter(p.family_id for p in valid))}
        self.history.append(evidence)
        stats['gui04_proposals']=evidence
        for p in extra:stats['proposed'][p.family_id]=stats['proposed'].get(p.family_id,0)+1
        stats['selected_families']=evidence['selected_families']
        return tuple(valid),stats
