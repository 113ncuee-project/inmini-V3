from dataclasses import replace
import itertools
import json
import math
import unittest

from simple_rapidchiplet.hybrid.mapping import (FusionStack, LayerGroup, LayerMapping, MappingPlan,
                                               Partition, TensorRegion, compile_mapping)
from simple_rapidchiplet.hybrid.workload import Workload, TensorSpec, LayerSpec
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.communication import build_communication
from simple_rapidchiplet.hybrid.depth_first import OVERLAP_MODES, subtract_box
from simple_rapidchiplet.hybrid.fusion_planner import fusion_proposals, select_fusion_plan, HierarchicalEvaluator
from simple_rapidchiplet.hybrid.search import SearchObjective, plan_from_dict


def chain(spatial=6, residual=False):
    tensors=[TensorSpec('x',(1,1,spatial,spatial))]
    layers=[]
    for i in range(3):
        lid=f'c{i}'; out=f'y{i}'
        layers.append(LayerSpec(lid,'Conv2d',('x' if i==0 else f'y{i-1}',),out,
                      kernel=(3,3),padding=(1,1),weight_shape=(1,1,3,3),macs_per_sample=spatial*spatial*9))
        tensors.append(TensorSpec(out,(1,1,spatial,spatial),producer=lid))
    if residual:
        layers.append(LayerSpec('add','Add',('y2','x'),'z',vector_ops_per_element=1))
        tensors.append(TensorSpec('z',(1,1,spatial,spatial),producer='add'))
    return Workload('df_residual' if residual else 'df_chain',tuple(tensors),tuple(layers),('x',),('z' if residual else 'y2',))


def plan_for(workload,mode='full_cache',tile=(2,2),multidie=False):
    ids=tuple(l.id for l in workload.layers)
    mappings=tuple(LayerMapping(lid,(f'compute:{i%2}/core:0',) if multidie else ('compute:0/core:0',),
                               weight_policy='persistent') for i,lid in enumerate(ids))
    return MappingPlan((LayerGroup('f',ids,'temporal'),),mappings,memory_ids=('memory:0',),
                       fusion_stacks=(FusionStack(ids,tile,mode),))


def numerical_replay(workload,compiled):
    """Execute every generated tile from selected owner values; compare full DAG.

    Dense zero-filled envelopes make padding/stride coordinate transforms explicit;
    generated work never reads an uncomputed intermediate value.
    """
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(1)
    values={'x':torch.arange(workload.tensor_map['x'].elements,dtype=torch.float64).reshape(workload.tensor_map['x'].shape)/37}
    weights={l.id:torch.arange(math.prod(l.weight_shape),dtype=torch.float64).reshape(l.weight_shape)/19 if l.weight_shape else None for l in workload.layers}
    def run(layer,inputs):
        if layer.kind=='Conv2d':
            return F.conv2d(inputs[0],weights[layer.id],stride=layer.stride,padding=layer.padding,dilation=layer.dilation,groups=layer.groups)
        if layer.kind=='Add': return inputs[0]+inputs[1]
        if layer.kind=='ReLU': return inputs[0].relu()
        raise ValueError(layer.kind)
    for layer in workload.layers:
        values[layer.output]=run(layer,[values[t] for t in layer.inputs])
    computed={}
    pending=list(compiled.units)
    while pending:
        progress=False
        for unit in list(pending):
            if not set(unit.dependencies)<=computed.keys(): continue
            layer=workload.layer_map[unit.layer_id]; inputs=[]
            for tid in layer.inputs:
                tensor=workload.tensor_map[tid]
                if not tensor.producer:
                    inputs.append(values[tid]); continue
                v=torch.zeros(tensor.shape,dtype=torch.float64)
                for name in unit.dependencies:
                    owner=compiled.unit_map[name]
                    if owner.output_tensor==tid:
                        v[tuple(slice(a,b) for a,b in owner.output_region.bounds)]=computed[name]
                inputs.append(v)
            actual=run(layer,inputs)[tuple(slice(a,b) for a,b in unit.output_region.bounds)]
            expected=values[layer.output][tuple(slice(a,b) for a,b in unit.output_region.bounds)]
            torch.testing.assert_close(actual,expected,rtol=1e-10,atol=1e-10)
            computed[unit.id]=actual;pending.remove(unit);progress=True
        if not progress: raise AssertionError('cyclic generated dependencies')
    output=workload.output_ids[0]
    result=torch.zeros_like(values[output]); covered=0
    for unit in compiled.tensor_owners[output]:
        result[tuple(slice(a,b) for a,b in unit.output_region.bounds)]=computed[unit.id]
        covered+=unit.output_region.elements
    assert covered==workload.tensor_map[output].elements
    torch.testing.assert_close(result,values[output],rtol=1e-10,atol=1e-10)


class DepthFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hw=HardwareSpec(cluster_rows=1,cluster_cols=1,compute_per_cluster=2,unified_buffer_bytes=2**20)

    def test_subtract_box_disjoint_and_exact(self):
        box=TensorRegion.full((2,3,5,6));cut=TensorRegion(((0,1),(1,2),(1,4),(2,5)))
        pieces=subtract_box(box,cut)
        self.assertEqual(sum(p.elements for p in pieces),box.elements-cut.elements)
        self.assertTrue(all(a.intersection(b) is None for a,b in itertools.combinations(pieces,2)))

    def test_three_modes_numerical_and_recompute_accounting(self):
        w=chain(); rows=[]
        for mode in OVERLAP_MODES:
            c=compile_mapping(w,plan_for(w,mode),self.hw)
            numerical_replay(w,c);build_communication(w,c)
            rows.append(c.execution_statistics)
        self.assertEqual(rows[2]['unique_macs'],w.total_macs)
        self.assertEqual(rows[2]['recompute_macs'],0)
        self.assertGreater(rows[0]['recompute_macs'],rows[1]['recompute_macs'])
        self.assertGreater(rows[1]['recompute_macs'],rows[2]['recompute_macs'])

    def test_residual_and_multidie_numerical(self):
        w=chain(residual=True)
        for mode in OVERLAP_MODES:
            c=compile_mapping(w,plan_for(w,mode,multidie=True),self.hw)
            numerical_replay(w,c);build_communication(w,c)

    def test_exported_intermediate_forbids_fusion(self):
        w=chain();w=replace(w,output_ids=('y0','y2'))
        with self.assertRaisesRegex(ValueError,'closed'):
            compile_mapping(w,plan_for(w),self.hw)

    def test_stride_and_multishard_regions_numerical(self):
        w=chain()
        w=replace(w,tensors=tuple(replace(t,shape=(1,1,3,3)) if t.id in ('y1','y2') else t for t in w.tensors),
                  layers=tuple(replace(l,stride=(2,2),macs_per_sample=81) if l.id=='c1' else
                               replace(l,macs_per_sample=81) if l.id=='c2' else l for l in w.layers))
        for mode in OVERLAP_MODES:
            p=plan_for(w,mode)
            p=replace(p,layer_mappings=tuple(replace(m,chiplets=('compute:0/core:0','compute:1/core:0'),
                                         partition=Partition(h=2)) for m in p.layer_mappings))
            c=compile_mapping(w,p,self.hw);numerical_replay(w,c);build_communication(w,c)

    def test_depthwise_and_two_microbatches_numerical(self):
        w=chain()
        w=replace(w,batch_size=2,tensors=tuple(replace(t,shape=(2,2,6,6)) for t in w.tensors),
                  layers=tuple(replace(l,groups=2,weight_shape=(2,1,3,3),macs_per_sample=648) for l in w.layers))
        for mode in OVERLAP_MODES:
            p=plan_for(w,mode)
            p=replace(p,layer_mappings=tuple(replace(m,chiplets=('compute:0/core:0','compute:1/core:0'),
                                         partition=Partition(k=2)) for m in p.layer_mappings))
            c=compile_mapping(w,p,self.hw);numerical_replay(w,c);build_communication(w,c)
            self.assertEqual(c.execution_statistics['unique_macs'],w.total_macs)

    def test_json_roundtrip(self):
        plan=plan_for(chain())
        self.assertEqual(plan_from_dict(json.loads(json.dumps(plan.to_dict()))),plan)

    def test_shared_boundary_read_cannot_bind_to_later_group(self):
        w=chain(residual=True)
        w=replace(w,layers=(*w.layers[:-1],replace(w.layers[-1],inputs=('y2','y0'))))
        p=plan_for(w)
        p=replace(p,groups=(LayerGroup('first',('c0',),'temporal'),
                            LayerGroup('fused',('c1','c2'),'temporal'),
                            LayerGroup('last',('add',),'temporal')),
                    fusion_stacks=(FusionStack(('c1','c2'),(2,2),'full_cache'),))
        result=HybridEvaluator(w,self.hw).evaluate(p,retain_trace=True)
        numerical_replay(w,result.compiled)
        self.assertTrue(result.metrics['feasible'])
        self.assertTrue(result.schedule.validate())
        self.assertTrue(any(t.kind=='inter_group_read' and len({result.compiled.unit_map[u].group_id
                         for u in t.consumer_units})>1 for t in result.communication.transfers))

    def test_oracle_copy_energy_capacity_and_order(self):
        w=chain();ev=HybridEvaluator(w,self.hw)
        cached=ev.evaluate(plan_for(w),retain_trace=True)
        cold=ev.evaluate(plan_for(w,'recompute'),retain_trace=True)
        self.assertTrue(cached.metrics['feasible']);self.assertTrue(cold.metrics['feasible'])
        self.assertGreater(cached.metrics['df_cache_copy_bytes'],0)
        self.assertGreater(cached.metrics['df_cache_copy_energy_j'],0)
        self.assertEqual(cold.metrics['df_cache_copy_bytes'],0)
        self.assertGreater(cold.metrics['energy_components']['mac_j'],cached.metrics['energy_components']['mac_j'])
        self.assertAlmostEqual(sum(cached.metrics['energy_components'].values()),cached.metrics['energy_j'])
        self.assertTrue(cached.schedule.validate())
        # Reducing actual physical UB invalidates the plan, never awards free reuse.
        small=HybridEvaluator(w,replace(self.hw,unified_buffer_bytes=1))
        self.assertFalse(small.evaluate(plan_for(w)).metrics['feasible'])

    def test_dp_vs_exhaustive_in_one_segment_space(self):
        w=chain();ev=HybridEvaluator(w,self.hw,trace=False);base=replace(plan_for(w),fusion_stacks=())
        objective=SearchObjective()
        exact,_=fusion_proposals(w,base,ev,tiles=((2,2),),max_depth=3,exhaustive=True)
        all_rows=[(objective.cost(ev.evaluate(p).metrics,{'energy_j':1,'latency_s':1}),p) for p in exact]
        # Independent enumeration of all chain cuts and three reuse choices.
        brute=[base]
        for cuts in itertools.product((False,True),repeat=2):
            segments=[];start=0
            for end in range(1,4):
                if end==3 or cuts[end-1]:
                    segments.append(tuple(f'c{i}' for i in range(start,end)));start=end
            options=[OVERLAP_MODES if len(ids)>1 else (None,) for ids in segments]
            for modes in itertools.product(*options):
                groups=tuple(LayerGroup(f'b{i}',ids,'temporal') for i,ids in enumerate(segments))
                stacks=tuple(FusionStack(ids,(2,2),mode) for ids,mode in zip(segments,modes) if mode)
                brute.append(replace(base,groups=groups,fusion_stacks=stacks))
        brute_best=min(objective.cost(ev.evaluate(p).metrics,{'energy_j':1,'latency_s':1}) for p in brute)
        self.assertAlmostEqual(min(c for c,p in all_rows),brute_best,places=18)
        chosen,evidence=select_fusion_plan(w,base,ev,objective,tiles=((2,2),),max_depth=3,
                                         exhaustive=True,query_budget=len(exact))
        self.assertEqual(objective.cost(ev.evaluate(chosen).metrics,{'energy_j':1,'latency_s':1}),min(c for c,p in all_rows))
        self.assertEqual(evidence['full_oracle_queries'],len(exact))
        inner=HierarchicalEvaluator(ev,objective,tiles=((2,2),),max_depth=3,query_budget=4)
        result=inner.evaluate(base);resolved,_=inner.resolve(base)
        self.assertEqual(result.metrics,ev.evaluate(resolved,retain_trace=False).metrics)
        self.assertGreater(inner.inner_queries,0)


if __name__=='__main__': unittest.main()
