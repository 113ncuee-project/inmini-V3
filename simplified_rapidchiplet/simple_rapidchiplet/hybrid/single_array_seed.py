"""v0.2 Tangram-style bounded segmentation proposals (staged for integration).

The original Tangram program is not executed. Proxy numbers only prune/rank
proposals; every executable seed and its final rank require the shared oracle.
This module never constructs historical hardware or a per-core GLB.
"""
from dataclasses import dataclass
import math
import time

from simple_rapidchiplet.hybrid.actions import partition_options
from simple_rapidchiplet.hybrid.mapping import LayerGroup, LayerMapping, MappingPlan, Partition, initial_mapping, validate_plan
from simple_rapidchiplet.hybrid.rl_schema import stable_hash


VERSION = 'single_array_tangram_style_adapter_v1'


@dataclass(frozen=True)
class SingleArraySeedProposal:
    plan: MappingPlan
    provenance: dict
    proxy: dict

    def to_dict(self):
        return {'mapping': self.plan.to_dict(), 'provenance': self.provenance, 'proxy': self.proxy}


def _quota(workload, layer_id, requested):
    count = min(requested, math.prod(workload.tensor_map[workload.layer_map[layer_id].output].shape))
    while count > 0:
        options = partition_options(workload, layer_id, count, 1)
        if options:
            return count, options
        count -= 1
    raise ValueError('no nonempty integer output partition')


def _segment(workload, hardware, layers, *, mode, direction, placement, memory_policy):
    ids = tuple(layer.id for layer in layers)
    slots = hardware.compute_slots
    # A second placement reverses die/PE order while keeping the exact quota.
    if placement:
        slots = tuple(reversed(slots))
    remaining, counts = len(slots), {}
    if mode == 'spatial':
        total = sum(max(layer.macs_per_sample, math.prod(workload.tensor_map[layer.output].shape)) for layer in layers)
        for index, layer in enumerate(layers):
            demand = max(layer.macs_per_sample, math.prod(workload.tensor_map[layer.output].shape))
            proposed = min(max(1, int(len(slots) * demand / total)), remaining - (len(layers) - index - 1))
            count, _ = _quota(workload, layer.id, proposed)
            counts[layer.id], remaining = count, remaining - count
        # Idle PE resources are legal and remain fully paid; do not force a
        # factorization that would create empty shards just to claim 100% use.
    else:
        counts = {layer.id: _quota(workload, layer.id, len(slots))[0] for layer in layers}
    mappings, cursor, compute_s, local_bytes = [], 0, 0., 0
    memories = tuple(f'memory:{i}' for i in range(hardware.io_count))
    for layer in layers:
        count, options = _quota(workload, layer.id, counts[layer.id])
        preferred = [p for p in options if (p[1] > 1 and p[2] * p[3] == 1)] if direction == 'K' else [p for p in options if p[1] == 1]
        choices = preferred or list(options)
        part = min(choices, key=lambda p: (p[2] * p[3], -p[1], p))
        selected = slots[cursor:cursor + count] if mode == 'spatial' else slots[:count]
        cursor += count if mode == 'spatial' else 0
        die = int(selected[0].split('/')[0].split(':')[1])
        row, col = divmod(die, hardware.cols)
        nearest = f'memory:{2 * row + int(col >= hardware.cols / 2)}'
        memory = 'interleave' if memory_policy == 'interleave' else nearest
        mappings.append(LayerMapping(layer.id, selected, Partition(*part), memory, memory, memory))
        output = workload.tensor_map[layer.output]
        compute_s += layer.macs_per_sample / (count * 256 * hardware.compute_clock_hz)
        compute_s += output.elements * layer.vector_ops_per_element / (hardware.vector_lanes * hardware.compute_clock_hz)
        local_bytes += layer.weight_bytes * part[2] * part[3]
        local_bytes += sum(workload.tensor_map[tensor].bytes for tensor in layer.inputs) * part[1]
        local_bytes += output.bytes
    members = set(ids)
    external_inputs = {tensor for layer in layers for tensor in layer.inputs
                       if workload.tensor_map[tensor].producer not in members}
    boundary_outputs = {layer.output for layer in layers if layer.output in workload.output_ids or
                        any(user not in members for user in workload.consumers[layer.output])}
    dram_bytes = sum(workload.tensor_map[tensor].bytes for tensor in external_inputs | boundary_outputs)
    dram_bytes += sum(layer.weight_bytes for layer in layers)
    proxy_s = compute_s + dram_bytes / (hardware.io_count * hardware.dram_bandwidth_Bps)
    proxy_s += local_bytes / (hardware.compute_count * hardware.l2_bandwidth_Bps)
    return LayerGroup('seed_' + '_'.join(ids), ids, mode), tuple(mappings), proxy_s, dram_bytes


def generate_single_array_seeds(workload, hardware, *, max_candidates=4, max_group_layers=4,
                                beam_width=4, timeout_s=3.):
    if workload.batch_size != 1:
        raise ValueError('single-array seeds require Batch1')
    if min(max_candidates, max_group_layers, beam_width) < 1 or timeout_s <= 0:
        raise ValueError('positive seed bounds required')
    started = time.monotonic()
    memories = tuple(f'memory:{i}' for i in range(hardware.io_count))
    baseline = initial_mapping(workload, hardware.compute_slots, memories, max_group_layers=1)
    common = {'implementation': VERSION, 'original_tangram_executed': False,
              'globally_exact': False, 'physical_validity': 'global oracle pending',
              'hardware_profile': hardware.profile_id,
              'bounds': {'beam_width': beam_width, 'max_group_layers': max_group_layers,
                         'max_candidates': max_candidates, 'timeout_s': timeout_s}}
    proposals = [SingleArraySeedProposal(baseline, {**common, 'source': 'preserved_original_integer_stripes'},
                                        {'status': 'not_scored', 'formal_PPA': False})]
    n = len(workload.layers)
    # Each prefix retains complete, topological mappings only. At time expiry,
    # a partial prefix is never mislabeled an executable whole-model seed.
    beams = {0: [(0., 0, (), ())]}
    explored, timed_out = 0, False
    for end in range(1, n + 1):
        rows = []
        for depth in range(1, min(max_group_layers, end) + 1):
            start = end - depth
            if start not in beams:
                continue
            layers = workload.layers[start:end]
            for mode in ('spatial', 'temporal'):
                if mode == 'spatial' and len(layers) > len(hardware.compute_slots):
                    continue
                for direction in ('K', 'P'):
                    if time.monotonic() - started >= timeout_s:
                        timed_out = True
                        break
                    group, mapping, delay, traffic = _segment(workload, hardware, layers, mode=mode,
                        direction=direction, placement=int(direction == 'P'), memory_policy='interleave')
                    for old_delay, old_traffic, groups, mappings in beams[start]:
                        explored += 1
                        rows.append((old_delay + delay, old_traffic + traffic, (*groups, group), (*mappings, *mapping)))
                if timed_out:
                    break
            if timed_out:
                break
        if timed_out:
            break
        seen, kept = set(), []
        for row in sorted(rows, key=lambda row: (row[0], row[1])):
            key = stable_hash({'groups': [(g.layer_ids, g.mode) for g in row[2]],
                               'parts': [(m.layer_id, m.chiplets, m.partition.as_tuple()) for m in row[3]]})
            if key not in seen:
                seen.add(key)
                kept.append(row)
            if len(kept) >= beam_width:
                break
        beams[end] = kept
    seen = {stable_hash(baseline.to_dict())}
    for delay, traffic, groups, mappings in beams.get(n, ()):
        plan = MappingPlan(groups, mappings, 1, 'multicast', memories)
        validate_plan(workload, plan, hardware.compute_slots)
        key = stable_hash(plan.to_dict())
        if key in seen:
            continue
        seen.add(key)
        proposals.append(SingleArraySeedProposal(plan, {**common, 'source': 'bounded_segmentation_DP_beam',
            'explored_transitions': explored, 'timed_out': timed_out, 'elapsed_s': time.monotonic() - started},
            {'latency_proxy_s': delay, 'dram_proxy_bytes': traffic, 'formal_PPA': False,
             'limits': 'no path queue/halo/capacity proof; never used as evaluator PPA or reward'}))
        if len(proposals) >= max_candidates:
            break
    return tuple(proposals)
