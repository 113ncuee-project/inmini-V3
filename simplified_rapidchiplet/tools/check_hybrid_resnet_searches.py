"""Seed-matched real ResNet search smoke, eight charged designs per method."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.search import plan_fingerprint, run_search
from simple_rapidchiplet.hybrid.workload import extract_resnet50


def source_pins():
    root = Path(__file__).resolve().parents[1] / "simple_rapidchiplet" / "hybrid"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.glob("*.py"))}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def main():
    output = Path(__file__).resolve().parents[1] / "results" / "hybrid_resnet_search_validation"
    source = source_pins()
    workload = extract_resnet50(batch_size=1)
    hardware = HardwareSpec()
    record = {"status": "in_progress", "source_before": source,
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "workload_fingerprint": workload.fingerprint, "hardware": asdict(hardware),
              "seed": 7, "budget": 8, "horizon": 16, "max_per_operator": 12,
              "weight_policy": "persistent", "group_layers": 3, "microbatch_size": 1,
              "pipeline_window": 2, "proposal": "uniform", "objective": "normalized EDP",
              "budget_definition": "each method charges its initial mapping and unique design evaluations; cache hits do not consume charged designs",
              "fairness": "same initial mapping/resources/seed/objective; independent full evaluator and search caches; shared pure on-die memo affects runtime only",
              "limits": "one seed and eight designs is an integration smoke, not a convergence or superiority claim; runtime is not a cold-cache speed comparison",
              "trials": []}
    reference = None
    fingerprint = None
    for method in ("rl", "random", "greedy", "sa"):
        if source_pins() != source:
            raise RuntimeError("hybrid source changed; completed trials are preserved")
        started = time.perf_counter()
        print(f"Starting {method} seed7 budget8", flush=True)
        evaluator = HybridEvaluator(workload, hardware, trace=False, max_inflight_microbatches=2)
        package = evaluator.package
        plan = balanced_mapping(workload, package.mapping_core_ids, package.memory_ids,
                                hardware=hardware, microbatch_size=1, max_group_layers=3,
                                weight_policy="persistent")
        current_fingerprint = plan_fingerprint(plan)
        if fingerprint is None:
            fingerprint = current_fingerprint
            record["initial_plan_fingerprint"] = fingerprint
            record["initial_plan"] = plan.to_dict()
        elif fingerprint != current_fingerprint:
            raise RuntimeError("method initial mappings differ")
        checkpoint = output / "checkpoints" / f"{method}_seed7_budget8.json"
        result = run_search(workload, plan, evaluator, package.mapping_core_ids, package.memory_ids,
                            method=method, seed=7, budget=8, horizon=16, max_per_operator=12,
                            checkpoint_path=checkpoint, checkpoint_every=1, evaluator_identity=evaluator.identity,
                            proposal="uniform",
                            core_clusters={core: package.node_cluster[core.split("/")[0]] for core in package.mapping_core_ids},
                            core_positions={core: package.positions[core.split("/")[0]] for core in package.mapping_core_ids},
                            memory_positions={memory: package.positions[memory] for memory in package.memory_ids})
        comparable = {key: result.initial_metrics[key] for key in ("latency_s", "energy_j", "area_mm2", "power_w", "feasible")}
        if reference is None:
            reference = comparable
            record["initial_reference_metrics"] = reference
        elif reference != comparable:
            raise RuntimeError("method initial physical metrics differ")
        row = result.to_dict()
        row.update(wall_elapsed_s=time.perf_counter() - started,
                   full_backend_evaluations=evaluator.evaluations, full_backend_cache_hits=evaluator.cache_hits,
                   source_at_result=source_pins())
        record["trials"].append(row)
        save(output / "validation.json", record)
        print(json.dumps({"method": method, "evaluations": result.evaluations, "cost": result.best_cost,
                          "latency_s": result.best_metrics["latency_s"], "energy_j": result.best_metrics["energy_j"],
                          "policy_updates": result.policy_updates, "wall_elapsed_s": row["wall_elapsed_s"]}), flush=True)
    record.update(status="completed", source_after=source_pins(), source_stable=source_pins() == source)
    save(output / "validation.json", record)
    print(f"Saved {output / 'validation.json'}", flush=True)


if __name__ == "__main__":
    main()
