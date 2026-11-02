"""Exact v0.2 tiles; MAC tiles fit L1, die-level VPU tiles use shared L2.

The first version deliberately uses full input-channel tiles on one PE. It
does not claim input-channel parallelism or an unimplemented streaming panel
pipeline. Oversized receptive fields fail explicitly instead of free spill.
Historical ownership/DF box algebra is reused; no old hardware is used.
"""
from __future__ import annotations

from dataclasses import replace
import math

from .mapping import (CompiledMapping, TensorRegion, _tiles, compile_mapping,
                      required_input_regions, validate_plan)


def tile_requirements(workload, layer, region, psum_bytes=3):
    inputs = required_input_regions(workload, layer, region)
    activation = sum(req.region.elements * workload.tensor_map[req.tensor_id].bytes_per_element for req in inputs)
    weight = (region.shape[1] * math.prod(layer.weight_shape[1:]) if layer.weight_shape else 0)
    output = region.elements * workload.tensor_map[layer.output].bytes_per_element
    psum = region.elements * psum_bytes if layer.weight_shape else 0
    return {"inputs": inputs, "activation_bytes": activation, "weight_bytes": weight,
            "output_bytes": output, "psum_bytes": psum}


def _fit_full_channel_tile(workload, layer, owned, spec):
    dimensions = list(owned.shape)
    activation_capacity = spec.l1_activation_bytes if layer.weight_shape else spec.l2_activation_bytes - spec.assumptions.quantization_parameter_bytes
    output_capacity = spec.l1_output_bytes if layer.weight_shape else spec.l2_output_bytes
    while True:
        region = TensorRegion(tuple((left, left + size) for (left, _), size in zip(owned.bounds, dimensions)))
        req = tile_requirements(workload, layer, region, spec.assumptions.psum_storage_bytes)
        pressure = max(req['weight_bytes'] / spec.l1_weight_bytes,
                       req['activation_bytes'] / activation_capacity,
                       (req['psum_bytes'] if layer.weight_shape else req['output_bytes']) / output_capacity,
                       region.shape[1] * 8 / spec.assumptions.quantization_parameter_bytes if layer.weight_shape else 0)
        if pressure <= 1:
            return tuple(dimensions)
        options = []
        for axis, extent in enumerate(dimensions):
            if extent > 1:
                proposal = list(dimensions)
                proposal[axis] = math.ceil(extent / 2)
                smaller = TensorRegion(tuple((left, left + size) for (left, _), size in zip(owned.bounds, proposal)))
                demand = tile_requirements(workload, layer, smaller, spec.assumptions.psum_storage_bytes)
                score = max(demand['weight_bytes'] / spec.l1_weight_bytes,
                            demand['activation_bytes'] / activation_capacity,
                            (demand['psum_bytes'] if layer.weight_shape else demand['output_bytes']) / output_capacity,
                            smaller.shape[1] * 8 / spec.assumptions.quantization_parameter_bytes if layer.weight_shape else 0)
                options.append((score, -extent, axis, proposal))
        if not options:
            raise ValueError(f"{layer.id}: one output element exceeds a physical L1 pool; sequential C-panel implementation required")
        dimensions = min(options)[-1]


def compile_single_array(workload, plan, hardware):
    if workload.batch_size != 1 or plan.microbatch_size != 1:
        raise ValueError("v0.2 inference contract fixes Batch=1 and Microbatch=1")
    validate_plan(workload, plan, hardware.compute_slots)
    memories = tuple(f'memory:{index}' for index in range(hardware.io_count))
    if plan.memory_ids != memories:
        raise ValueError("mapping memory IDs differ from the physical IO controllers")
    if any(tensor.bits != 8 for tensor in workload.tensors) or any(
        layer.weight_shape and layer.weight_bits != 8 for layer in workload.layers
    ):
        raise ValueError("v0.2 supports INT8 activations/weights only")
    if any(layer.kind == 'BatchNorm2d' for layer in workload.layers):
        raise ValueError('standalone BatchNorm parameter service is unsupported; fold inference affine post-ops before v0.2 compilation')
    # First obtain generation-correct DF ownership, then subdivide its exact
    # regions. No scalar MAC is added/removed by subdivision.
    base = compile_mapping(workload, plan, None)
    fragments = {}
    for original in base.units:
        layer = workload.layer_map[original.layer_id]
        children = []
        pending = [original.output_region]
        regions = []
        while pending:
            owned = pending.pop()
            shape = _fit_full_channel_tile(workload, layer, owned, hardware)
            if shape != owned.shape:
                pending.extend(reversed(_tiles(owned, shape)))
            else:
                regions.append(owned)
        for index, region in enumerate(regions):
            req = tile_requirements(workload, layer, region, hardware.assumptions.psum_storage_bytes)
            weight = (TensorRegion((region.bounds[1], (0, layer.weight_shape[1]),
                                    (0, layer.kernel[0]), (0, layer.kernel[1]))) if layer.weight_shape else None)
            macs = region.elements * math.prod(layer.weight_shape[1:]) if weight else 0
            # Unique tile_index prevents cold weight reads being accidentally
            # deduplicated across different executable fragments.
            children.append(replace(original, id=f'{original.id}:p{index}', output_region=region,
                tile_index=original.tile_index * 1_000_000 + index, inputs=req['inputs'], weight_region=weight,
                weight_bytes=req['weight_bytes'], input_bytes=req['activation_bytes'], output_bytes=req['output_bytes'],
                macs=macs, vector_ops=region.elements * layer.vector_ops_per_element,
                buffer_bytes=req['activation_bytes'] + req['weight_bytes'] + req['output_bytes'] + req['psum_bytes'],
                channel_tile=max(r.region.shape[1] for r in req['inputs']), dependencies=()))
        fragments[original.id] = children
    result = []
    for original in base.units:
        for unit in fragments[original.id]:
            dependencies = tuple(dict.fromkeys(producer.id for dependency in original.dependencies
                for producer in fragments[dependency]
                if any(req.tensor_id == producer.output_tensor and req.region.intersection(producer.output_region)
                       is not None for req in unit.inputs)))
            result.append(replace(unit, dependencies=dependencies))
    if sum(unit.macs for unit in result) != sum(unit.macs for unit in base.units):
        raise ValueError("PE tile subdivision does not conserve executed MACs")
    stats = dict(base.execution_statistics or {})
    stats.update({"executed_macs": sum(u.macs for u in result), "units": len(result),
                  "cache_level": "capacity_checked_shared_L2",
                  "scope": "generation-correct DF; full-channel PE tiles; L1 per-pool capacity; L2 checked after scheduling"})
    for row in stats.get('stacks', ()):
        row['cache_level'] = 'capacity_checked_shared_L2'
    return CompiledMapping(workload, plan, tuple(result), stats)
