"""Auditable Tangram-style initial mapping for the chiplet RL environment.

Tangram, section 4.2, searches pipeline segments in DAG topological order with
dynamic programming and beam search.  The supplied Gemini implementation uses
``DP_search``/``search_best_batch`` in ``spatial_mapping/segmentation.cpp`` before
its spatial-mapping SA.  This module adapts that *initialization strategy* to the
existing operator DAG, mapper and cost model; it does not execute either original
implementation or claim its BSD/ALLO dataflow semantics.

The bounded planner's delay/energy estimates only propose candidates.  When an
evaluator is supplied, every query (including failures) is recorded and the
complete evaluator chooses the RL seed.  No estimated PPA is substituted for an
unexecutable candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from time import perf_counter
from typing import Callable

from .hardware import HardwareSpec
from .mapping import MappingPlan, validate_plan
from .planner import propose_plans


SEED_IMPLEMENTATION_VERSION = "tangram_style_adapter_v1"

# Locations and digest were checked against the user's supplied archive.  They
# identify evidence, not executable dependencies on the user's Downloads folder.
SOURCE_EVIDENCE = (
    {"source": "Tangram (ASPLOS 2019)", "location": "section 3.3 and section 4.2, pp. 814-815",
     "url": "https://doi.org/10.1145/3297858.3304014",
     "mechanism": "DAG-aware pipeline segments; dynamic programming plus beam search"},
    {"source": "Gemini supplied GEMINI-HPCA2024-master.zip",
     "location": "src/spatial_mapping/segmentation.cpp:914,991,1093",
     "url": "https://github.com/SET-Scheduling-Project/GEMINI-HPCA2024",
     "member_sha256": "1634abd4f3af8a1912a87249950c7351890bd1970d6782f66586978108a1ded8",
     "mechanism": "search_best_batch -> contiguous-segment DP_search -> SA_search_SPM"},
)


def dag_snapshot(workload):
    """JSON-ready lossless scheduling DAG with explicit residual inputs.

    Post-op fusion already performed by the model parser remains explicit in
    ``post_ops``; this adapter never removes an Add or one of its incoming edges.
    """
    workload.validate()
    return {
        "name": workload.name, "model_hash": workload.fingerprint,
        "batch_size": workload.batch_size, "source": workload.source,
        "input_ids": list(workload.input_ids), "output_ids": list(workload.output_ids),
        "shape_axes": ["B", "K", "H", "W"],
        "nodes": [
            {"id": layer.id, "operator": layer.kind, "inputs": list(layer.inputs),
             "output": layer.output, "output_shape": list(workload.tensor_map[layer.output].shape),
             "kernel": list(layer.kernel), "stride": list(layer.stride),
             "padding": list(layer.padding), "dilation": list(layer.dilation),
             "groups": layer.groups, "weight_shape": list(layer.weight_shape),
             "weight_bits": layer.weight_bits, "macs_per_sample": layer.macs_per_sample,
             "vector_ops_per_element": layer.vector_ops_per_element,
             "semantic_block": layer.semantic_block, "post_ops": list(layer.post_ops)}
            for layer in workload.layers
        ],
        "tensors": [
            {"id": tensor.id, "shape": list(tensor.shape), "bits": tensor.bits,
             "bytes": tensor.bytes, "producer": tensor.producer or None,
             "consumers": list(workload.consumers[tensor.id]),
             "is_model_input": tensor.id in workload.input_ids,
             "is_model_output": tensor.id in workload.output_ids}
            for tensor in workload.tensors
        ],
        "edges": [
            {"tensor_id": tensor_id,
             "producer": workload.tensor_map[tensor_id].producer or None,
             "consumer": layer.id, "input_index": index,
             "shape": list(workload.tensor_map[tensor_id].shape),
             "bits": workload.tensor_map[tensor_id].bits}
            for layer in workload.layers for index, tensor_id in enumerate(layer.inputs)
        ],
    }


def _connected_segment(workload, group):
    """Tangram proposal heuristic: share a dependency or an input with the prefix.

    This is proposal pruning only.  It is not a hardware validity requirement,
    and it never modifies the DAG or the legality rules of the RL environment.
    """
    selected, inputs = set(), set()
    for layer_id in group.layer_ids:
        layer = workload.layer_map[layer_id]
        if selected and not (inputs.intersection(layer.inputs) or
                             any(workload.tensor_map[name].producer in selected for name in layer.inputs)):
            return False
        selected.add(layer_id)
        inputs.update(layer.inputs)
    return True


@dataclass(frozen=True)
class TangramSeedCandidate:
    plan: MappingPlan
    estimated_delay_s: float
    estimated_energy_j: float
    boundary_bytes: int
    origin: str = "bounded DAG-segment DP/beam adapter"

    def to_dict(self):
        return {"plan": self.plan.to_dict(), "estimated_delay_s": self.estimated_delay_s,
                "estimated_energy_j": self.estimated_energy_j, "boundary_bytes": self.boundary_bytes,
                "origin": self.origin, "estimate_is_final_evaluation": False}


def _candidate(candidate, origin=None):
    return TangramSeedCandidate(candidate.plan, candidate.estimated_delay_s,
                                candidate.estimated_energy_j, candidate.boundary_bytes,
                                origin or "bounded DAG-segment DP/beam adapter")


def generate_tangram_seeds(workload, compute_ids, memory_ids=("memory:0",), hardware=None, *,
                           objective="edp", microbatch_sizes=(1, 2, 4), max_group_layers=4,
                           beam_width=4, max_candidates=8, weight_policy="cold"):
    """Return valid mapping proposals, without claiming estimated physical PPA.

    The mapper currently has one microbatch size per plan.  Unlike Gemini's
    per-segment batch array, this adapter enumerates homogeneous sizes.  The
    group limit and beam width are explicit approximation bounds.
    """
    workload.validate()
    if not workload.layers:
        raise ValueError("Tangram initialization requires at least one operator")
    compute_ids, memory_ids = tuple(map(str, compute_ids)), tuple(map(str, memory_ids))
    microbatch_sizes = tuple(sorted(set(microbatch_sizes)))
    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    hardware = hardware or HardwareSpec()
    proposed = propose_plans(workload, compute_ids, memory_ids, hardware,
                             microbatch_sizes=microbatch_sizes, max_group_layers=max_group_layers,
                             beam_width=beam_width, max_candidates=max_candidates,
                             objective=objective, weight_policy=weight_policy)
    selected, seen = [], set()
    for proposal in proposed:
        if not all(_connected_segment(workload, group) for group in proposal.plan.groups):
            continue
        key = repr(proposal.plan)
        if key not in seen:
            selected.append(_candidate(proposal))
            seen.add(key)
    # A temporal singleton baseline makes an executable conservative alternative
    # visible to the full evaluator when the proposal budget permits one.  It is
    # not assigned fake latency/energy; the estimate comes from the same planner.
    baseline = propose_plans(workload, compute_ids, memory_ids, hardware,
                             microbatch_sizes=microbatch_sizes, max_group_layers=1,
                             beam_width=1, max_candidates=1, objective=objective,
                             weight_policy=weight_policy)[0]
    if repr(baseline.plan) not in seen:
        value = _candidate(baseline, "single-layer sequential baseline")
        if len(selected) < max_candidates:
            selected.append(value)
        elif max_candidates > 1:
            selected[-1] = value
    if not selected:
        selected.append(_candidate(baseline, "single-layer sequential baseline"))
    for candidate in selected:
        validate_plan(workload, candidate.plan, compute_ids)
    return tuple(selected[:max_candidates])


def diverse_tangram_seeds(workload,compute_ids,memory_ids,hardware,*,max_candidates=4,max_group_layers=3):
    """v2-only balanced P/K coverage and explicit capacity-sized alternatives.

    Every variant remains a Tangram graph-segment proposal and requires full
    evaluation. The original generate/build functions and v1 order are intact.
    """
    from dataclasses import replace
    from .mapping import enumerate_partitions
    from .planner import _estimate_group
    original=generate_tangram_seeds(workload,compute_ids,memory_ids,hardware,
        microbatch_sizes=(1,),max_candidates=max(2,max_candidates),max_group_layers=max_group_layers)
    base=original[-1].plan
    rows=list(original[:1]);variants=[]
    for name in ('weight_shared_P','activation_shared_K','capacity_sized_temporal_tiles'):
        mappings=[]
        for item in base.layer_mappings:
            choices=enumerate_partitions(workload,item.layer_id,len(item.chiplets),1)
            matching=[p for p in choices if (p.k==1 and p.h*p.w>1) if name=='weight_shared_P'] if name=='weight_shared_P' else [p for p in choices if p.h*p.w==1]
            part=matching[0] if matching else item.partition
            changed=replace(item,partition=part)
            if name=='capacity_sized_temporal_tiles':changed=replace(item,tile_shape=(1,64,16,16),channel_tile=128)
            mappings.append(changed)
        plan=replace(base,layer_mappings=tuple(mappings))
        validate_plan(workload,plan,compute_ids)
        estimates=[_estimate_group(workload,g,[(l,plan.mapping_map[l].chiplets,plan.mapping_map[l].partition) for l in g.layer_ids],1,hardware) for g in plan.groups]
        variants.append(TangramSeedCandidate(plan,sum(v[0] for v in estimates),sum(v[1] for v in estimates),sum(v[2] for v in estimates),name+'; bounded proposal, not final PPA'))
    # Alternating P and K is coverage, not an assumed winning preference.
    rows.extend(variants[:2]);rows.extend(original[1:]);rows.append(variants[2])
    unique=[];seen=set()
    for row in rows:
        key=repr(row.plan)
        if key not in seen:seen.add(key);unique.append(row)
    return tuple(unique)


def _finite_positive(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _proxy_score(candidate, objective):
    if objective == "latency":
        return candidate.estimated_delay_s
    if objective == "energy":
        return candidate.estimated_energy_j
    if objective == "edp":
        return candidate.estimated_delay_s * candidate.estimated_energy_j
    raise ValueError("seed objective must be latency, energy or edp")


def _metrics_score(metrics, objective):
    latency, energy = metrics["latency_s"], metrics["energy_j"]
    return latency if objective == "latency" else energy if objective == "energy" else latency * energy


def _safe_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_json(item) for item in value]
    return value


@dataclass(frozen=True)
class TangramSeedResult:
    candidates: tuple[TangramSeedCandidate, ...]
    selected_index: int | None
    selected_metrics: dict | None
    evaluation_records: tuple[dict, ...]
    proposal_elapsed_s: float
    evaluation_elapsed_s: float
    provenance: dict
    status: str

    @property
    def plan(self):
        return None if self.selected_index is None else self.candidates[self.selected_index].plan

    @property
    def metrics(self):
        return self.selected_metrics

    @property
    def evaluator_queries(self):
        return len(self.evaluation_records)

    @property
    def full_evaluations(self):
        values = [row.get("full_evaluations") for row in self.evaluation_records]
        return None if any(value is None for value in values) else sum(values)

    @property
    def cache_hits(self):
        values = [row.get("cache_hits") for row in self.evaluation_records]
        return None if any(value is None for value in values) else sum(values)

    def to_dict(self):
        return _safe_json({"status": self.status, "selected_index": self.selected_index,
                           "plan": None if self.plan is None else self.plan.to_dict(),
                           "selected_metrics": self.selected_metrics,
                           "proposal_count": len(self.candidates), "evaluator_queries": self.evaluator_queries,
                           "full_evaluations": self.full_evaluations, "cache_hits": self.cache_hits,
                           "proposal_elapsed_s": self.proposal_elapsed_s,
                           "evaluation_elapsed_s": self.evaluation_elapsed_s,
                           "evaluation_records": self.evaluation_records,
                           "candidates": [candidate.to_dict() for candidate in self.candidates],
                           "provenance": self.provenance})


def build_tangram_seed(workload, compute_ids, memory_ids=("memory:0",), hardware=None, *,
                       evaluator=None, objective="edp", microbatch_sizes=(1, 2, 4),
                       max_group_layers=4, beam_width=4, max_candidates=8,
                       max_evaluations=None, weight_policy="cold",
                       score_fn: Callable[[dict], float] | None = None):
    """Build an auditable RL initial state using the shared full evaluator.

    ``score_fn(metrics)`` may implement the episode's fixed PPA preference and
    constraint-violation ranking.  A physically executable candidate whose PPA
    exceeds the user's design limits is still an eligible initial state.  An
    evaluator report with ``feasible=False`` denotes an invalid memory/execution
    plan and is never selected.  With no evaluator, status is explicitly
    ``proposal_only``; if all evaluated candidates fail, ``plan`` is ``None``.
    """
    started = perf_counter()
    compute_ids, memory_ids = tuple(map(str, compute_ids)), tuple(map(str, memory_ids))
    microbatch_sizes = tuple(microbatch_sizes)
    if objective not in {"latency", "energy", "edp"}:
        raise ValueError("seed objective must be latency, energy or edp")
    if max_evaluations is not None and (not isinstance(max_evaluations, int) or
                                      isinstance(max_evaluations, bool) or max_evaluations < 0):
        raise ValueError("max_evaluations must be a nonnegative integer or None")
    candidates = generate_tangram_seeds(workload, compute_ids, memory_ids, hardware,
                                        objective=objective, microbatch_sizes=microbatch_sizes,
                                        max_group_layers=max_group_layers, beam_width=beam_width,
                                        max_candidates=max_candidates, weight_policy=weight_policy)
    proposal_elapsed = perf_counter() - started
    provenance = {
        "implementation": SEED_IMPLEMENTATION_VERSION,
        "method": "Tangram-style bounded DAG segmentation DP/beam, followed by shared evaluator ranking",
        "original_tangram_executed": False, "original_gemini_executed": False,
        "globally_exact": False, "sources": list(SOURCE_EVIDENCE),
        "dag_hash": workload.fingerprint,
        "bounds": {"microbatch_sizes": list(microbatch_sizes), "max_group_layers": max_group_layers,
                   "beam_width": beam_width, "max_candidates": max_candidates,
                   "max_evaluations": max_evaluations},
        "approximation_limits": [
            "bounded graph-cut beam with proxy delay/energy; not exact original DP state/cost",
            "one homogeneous microbatch size per plan; no per-segment batch sizes",
            "balanced integer core allocation instead of exhaustive original intra-layer mapper",
            "original Tangram BSD rotations and ALLO timing are unsupported",
            "Gemini original C++ static-network mapper and SA are not invoked",
            "DAG dependencies, tensor shapes, precision and residual Add semantics are preserved",
        ],
        "proposal_only_ppa_is_estimate": True,
        "ranking_objective": "caller score_fn" if score_fn is not None else objective,
        "weight_policy": weight_policy,
    }
    if evaluator is None:
        index = min(range(len(candidates)), key=lambda item: (_proxy_score(candidates[item], objective), item))
        return TangramSeedResult(candidates, index, None, (), proposal_elapsed, 0.0, provenance, "proposal_only")
    limit = len(candidates) if max_evaluations is None else min(max_evaluations, len(candidates))
    records, eligible = [], []
    evaluation_started = perf_counter()
    for index, candidate in enumerate(candidates[:limit]):
        query_started = perf_counter()
        full_before = getattr(evaluator, "evaluations", None)
        hits_before = getattr(evaluator, "cache_hits", None)
        row = {"candidate_index": index, "valid": False, "score": None,
               "metrics": None, "rejection_reason": None}
        try:
            result = evaluator(candidate.plan) if callable(evaluator) else evaluator.evaluate(candidate.plan)
            metrics = result.metrics if hasattr(result, "metrics") else result
            if not isinstance(metrics, dict):
                raise TypeError("seed evaluator must return a metrics dict or an object with .metrics")
            row["metrics"] = metrics
            if metrics.get("feasible", True) is not True:
                row["rejection_reason"] = "physical evaluator rejected execution/memory plan"
            elif not all(_finite_positive(metrics.get(key)) for key in ("latency_s", "energy_j")):
                row["rejection_reason"] = "physical evaluator did not return finite positive latency and energy"
            else:
                score = score_fn(metrics) if score_fn is not None else _metrics_score(metrics, objective)
                if not isinstance(score, Real) or isinstance(score, bool) or not math.isfinite(score):
                    row["rejection_reason"] = "ranking score is not finite"
                else:
                    row.update(valid=True, score=float(score))
                    eligible.append((float(score), index, metrics))
        except Exception as exc:
            row["rejection_reason"] = f"{type(exc).__name__}: {exc}"
        full_after = getattr(evaluator, "evaluations", None)
        hits_after = getattr(evaluator, "cache_hits", None)
        row["full_evaluations"] = (full_after - full_before if isinstance(full_before, int)
                                   and isinstance(full_after, int) else None)
        row["cache_hits"] = (hits_after - hits_before if isinstance(hits_before, int)
                             and isinstance(hits_after, int) else None)
        row["elapsed_s"] = perf_counter() - query_started
        records.append(row)
    elapsed = perf_counter() - evaluation_started
    if not eligible:
        return TangramSeedResult(candidates, None, None, tuple(records), proposal_elapsed, elapsed,
                                 provenance, "no_evaluated_executable_seed")
    _, index, metrics = min(eligible, key=lambda item: (item[0], item[1]))
    return TangramSeedResult(candidates, index, metrics, tuple(records), proposal_elapsed, elapsed,
                             provenance, "evaluated_seed")
