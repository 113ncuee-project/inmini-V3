"""Executable depth-first tile DAG with exact box subtraction and paid reuse.

Recompute repeats overlap across sink tiles; horizontal_cache retains overlap
within one sink-tile row; full_cache retains it across all sink tiles. Branches
share values within a tile in every mode. Dense dilation envelopes are retained.
Storage is UB, never an unpriced L1 bypass. Exposed intermediate outputs forbid
fusion; closed residual subgraphs and multi-die Part/CG are supported.
"""
from dataclasses import replace
import math

from .mapping import (CompiledMapping, TensorRegion, WorkUnit, _fit_tile, _shards,
                      _tiles, compile_mapping, required_input_regions)

OVERLAP_MODES = ('recompute', 'horizontal_cache', 'full_cache')
SUPPORTED = {'Conv2d','Add','ReLU','BatchNorm2d','Identity','MaxPool2d','AvgPool2d'}


def subtract_box(box, cut):
    """Disjoint rectangles representing box minus cut, in four dimensions."""
    intersection = box.intersection(cut)
    if intersection is None:
        return (box,)
    middle = list(box.bounds)
    pieces = []
    for axis, (left, right) in enumerate(intersection.bounds):
        a, b = middle[axis]
        if a < left:
            region = list(middle); region[axis] = (a,left)
            pieces.append(TensorRegion(tuple(region)))
        if right < b:
            region = list(middle); region[axis] = (right,b)
            pieces.append(TensorRegion(tuple(region)))
        middle[axis] = (left,right)
    return tuple(pieces)


def legal_stack(workload, layer_ids):
    if len(layer_ids) < 2:
        return False
    members = set(layer_ids)
    order = tuple(layer.id for layer in workload.layers)
    start = order.index(layer_ids[0])
    if order[start:start+len(layer_ids)] != tuple(layer_ids):
        return False
    sink = layer_ids[-1]
    if any(workload.layer_map[lid].kind not in SUPPORTED for lid in layer_ids):
        return False
    for lid in layer_ids[:-1]:
        output = workload.layer_map[lid].output
        if output in workload.output_ids or any(user not in members for user in workload.consumers[output]):
            return False
    ancestors = {sink}
    for lid in reversed(layer_ids):
        if lid in ancestors:
            ancestors.update(workload.tensor_map[t].producer for t in workload.layer_map[lid].inputs)
    return members <= ancestors


def validate_stacks(workload, plan):
    seen = set()
    for stack in plan.fusion_stacks:
        if not legal_stack(workload,stack.layer_ids) or seen.intersection(stack.layer_ids):
            raise ValueError('fusion requires disjoint contiguous closed single-exit subgraphs')
        if len(stack.tile_hw)!=2 or any(type(v) is not int or v<1 for v in stack.tile_hw):
            raise ValueError('fusion tile H/W must be positive integers')
        if stack.overlap not in OVERLAP_MODES:
            raise ValueError('unsupported overlap policy')
        group = plan.group_map[stack.layer_ids[0]]
        if tuple(group.layer_ids) != stack.layer_ids:
            raise ValueError('each fusion stack must occupy exactly one layer group')
        seen.update(stack.layer_ids)


def compile_depth_first(workload, plan, hardware):
    regular = compile_mapping(workload,plan,hardware,_regular=True)
    fused = {lid for stack in plan.fusion_stacks for lid in stack.layer_ids}
    units = [u for u in regular.units if u.layer_id not in fused]
    spec = getattr(hardware,'spec',hardware)
    quota = (spec.core_global_buffer_bytes if spec.package_topology == 'gemini_mesh' else
             spec.pes_per_core*spec.l1_bytes_per_pe + spec.l2_bytes_per_die//spec.cores_per_die) if spec else None
    psum = spec.psum_bytes if spec else 3
    stats = []
    # Process stacks topologically. Regular output ownership is disjoint and
    # external requirements are connected after all executable units exist.
    for stack in plan.fusion_stacks:
        members = set(stack.layer_ids)
        sink_layer = workload.layer_map[stack.layer_ids[-1]]
        sink_tensor = workload.tensor_map[sink_layer.output]
        sink_mapping = plan.mapping_map[sink_layer.id]
        stack_units = []
        for mb, bs in enumerate(range(0,workload.batch_size,plan.microbatch_size)):
            be = bs+plan.microbatch_size
            caches = {}
            sequence = 0
            frame = 0

            def ensure(lid, requested, scope):
                nonlocal sequence
                layer = workload.layer_map[lid]
                mapping = plan.mapping_map[lid]
                output = workload.tensor_map[layer.output]
                available = caches.setdefault((lid,scope),[])
                used = []
                missing = [requested]
                for owner in available:
                    if owner.output_region.intersection(requested) is not None:
                        used.append(owner.id)
                        missing = [piece for box in missing for piece in subtract_box(box,owner.output_region)]
                shards = _shards(output.shape,mapping.partition,bs,be)
                for box in missing:
                    for shard_index, shard in enumerate(shards):
                        owned = box.intersection(shard)
                        if owned is None:
                            continue
                        dimensions, channel = owned.shape,mapping.channel_tile
                        if quota is not None:
                            dimensions, channel = _fit_tile(workload,layer,owned,dimensions,channel,quota,psum)
                        for region in _tiles(owned,dimensions):
                            inputs = required_input_regions(workload,layer,region)
                            dependencies = []
                            for req in inputs:
                                producer = workload.tensor_map[req.tensor_id].producer
                                if producer in members:
                                    dependencies.extend(ensure(producer,req.region,scope))
                            weight = (TensorRegion((region.bounds[1],(0,layer.weight_shape[1]),
                                      (0,layer.kernel[0]),(0,layer.kernel[1]))) if layer.weight_shape else None)
                            macs = region.elements*layer.weight_shape[1]*math.prod(layer.kernel) if weight else 0
                            input_bytes = sum(r.region.elements*workload.tensor_map[r.tensor_id].bytes_per_element for r in inputs)
                            output_bytes = region.elements*output.bytes_per_element
                            c = min(max(r.region.shape[1] for r in inputs),channel or max(r.region.shape[1] for r in inputs))
                            streamed_input = sum(math.ceil(r.region.elements*min(c,r.region.shape[1])/r.region.shape[1])*
                                                workload.tensor_map[r.tensor_id].bytes_per_element for r in inputs)
                            streamed_weight = weight.shape[0]*min(c,weight.shape[1])*math.prod(weight.shape[2:])*layer.weight_bits//8 if weight else 0
                            buffer = streamed_input+streamed_weight+output_bytes+region.elements*(psum if macs else output.bytes_per_element)
                            unit = WorkUnit(f'df:{lid}:mb{mb}:n{sequence}',lid,plan.group_map[lid].id,mb,
                                mapping.chiplets[shard_index],shard_index,sequence,layer.output,region,inputs,weight,
                                macs,region.elements*layer.vector_ops_per_element,
                                weight.elements*layer.weight_bits//8 if weight else 0,input_bytes,output_bytes,buffer,c,
                                tuple(dict.fromkeys(dependencies)),mapping.dataflow,mapping.microtile_shape,sequence,frame)
                            sequence += 1
                            stack_units.append(unit); available.append(unit); used.append(unit.id)
                return tuple(dict.fromkeys(used))

            # H/W then B/K correspondence. A row key includes the batch stripe;
            # sharing across core-shard columns is permitted and paid by NoP.
            targets = [(shard_index,region) for shard_index,shard in enumerate(_shards(sink_tensor.shape,sink_mapping.partition,bs,be))
                       for region in _tiles(shard,(0,0,*stack.tile_hw))]
            targets.sort(key=lambda row:(row[1].bounds[0],row[1].bounds[2],row[1].bounds[3],row[1].bounds[1]))
            for _,target in targets:
                scope = ('all',) if stack.overlap=='full_cache' else (target.bounds[0],target.bounds[2]) if stack.overlap=='horizontal_cache' else (frame,)
                ensure(sink_layer.id,target,scope)
                frame += 1
        units.extend(stack_units)
        executed = sum(u.macs for u in stack_units)
        logical = sum(workload.layer_map[lid].macs_per_sample for lid in stack.layer_ids)*workload.batch_size
        from .reuse import _union_elements
        unique = sum(_union_elements([u.output_region for u in stack_units if u.layer_id==lid])*
                     (workload.layer_map[lid].weight_shape[1]*math.prod(workload.layer_map[lid].kernel)
                      if workload.layer_map[lid].weight_shape else 0) for lid in stack.layer_ids)
        stats.append({'layers':stack.layer_ids,'tile_hw':stack.tile_hw,'overlap':stack.overlap,
                      'cache_level':'UB','logical_macs':logical,'executed_macs':executed,
                      'unique_macs':unique,'recompute_macs':executed-unique,
                      'pruned_macs':logical-unique,'units':len(stack_units)})
    owners = {}
    for unit in units:
        owners.setdefault((unit.output_tensor,unit.microbatch),[]).append(unit)
    result = []
    for unit in units:
        dependencies = list(unit.dependencies) if unit.execution_order>=0 else []
        for req in unit.inputs:
            producer = workload.tensor_map[req.tensor_id].producer
            internal = unit.execution_order>=0 and producer in plan.group_map[unit.layer_id].layer_ids
            if not internal:
                dependencies.extend(owner.id for owner in owners.get((req.tensor_id,unit.microbatch),())
                                    if owner.output_region.intersection(req.region) is not None)
        result.append(replace(unit,dependencies=tuple(dict.fromkeys(dependencies))))
    executed = sum(u.macs for u in result)
    unique = workload.total_macs-sum(s['logical_macs']-s['unique_macs'] for s in stats)
    group_index={group.id:i for i,group in enumerate(plan.groups)}
    layer_index={layer.id:i for i,layer in enumerate(workload.layers)}
    result.sort(key=lambda u:(group_index[u.group_id],u.microbatch,
                 u.execution_order if u.execution_order>=0 else layer_index[u.layer_id],u.shard_index,u.tile_index))
    return CompiledMapping(workload,plan,tuple(result),{'logical_macs':workload.total_macs,
        'executed_macs':executed,'unique_macs':unique,'recompute_macs':executed-unique,
        'pruned_macs':workload.total_macs-unique,'stacks':stats,
        'scope':'row-major depth-first; capacity-backed UB overlap reuse; dense dilation envelope'})
