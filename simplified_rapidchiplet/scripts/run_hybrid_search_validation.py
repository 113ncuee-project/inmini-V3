"""Run real hybrid PPA/energy search curves, not a synthetic cost oracle.

Examples (from the repository root):
  .venv/Scripts/python.exe simplified_rapidchiplet/scripts/run_hybrid_search_validation.py --budgets 64,128,512
  .venv/Scripts/python.exe simplified_rapidchiplet/scripts/run_hybrid_search_validation.py --resume

Curves continue saved searches at increasing cumulative evaluation budgets.
Every method/seed/proposal trial owns an independent HybridEvaluator cache.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.mapping import initial_mapping
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.search import run_search
from simple_rapidchiplet.hybrid.workload import make_toy_workload


def source_identity():
    folder = PROJECT / "simple_rapidchiplet" / "hybrid"
    files = ("actions.py", "search.py", "workload.py", "mapping.py", "planner.py", "communication.py", "reuse.py",
             "hardware.py", "rapid_backend.py", "ondie.py", "evaluator.py", "scheduler.py")
    sources = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in files}
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(), sources


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def integer_list(text):
    result = tuple(int(item) for item in text.split(","))
    if not result or any(item < 1 for item in result):
        raise argparse.ArgumentTypeError("values must be positive comma-separated integers")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budgets", type=integer_list, default=(64, 128, 512))
    parser.add_argument("--seeds", type=integer_list, default=(7, 8, 9))
    parser.add_argument("--methods", default="rl,random,greedy,sa")
    parser.add_argument("--proposals", default="uniform,cluster_guided")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--spatial", type=int, default=8)
    parser.add_argument("--microbatch", type=int, default=1)
    parser.add_argument("--max-group-layers", type=int, default=3)
    parser.add_argument("--initial", choices=("balanced", "equal"), default="balanced")
    parser.add_argument("--max-per-operator", type=int, default=12)
    parser.add_argument("--horizon", type=int, default=16)
    parser.add_argument("--checkpoint-every", type=int, default=32)
    parser.add_argument("--pipeline-window", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out", type=Path, default=PROJECT / "results" / "hybrid_search_validation")
    args = parser.parse_args(argv)
    if tuple(sorted(set(args.budgets))) != args.budgets:
        parser.error("budgets must be strictly increasing")
    methods, proposals = tuple(args.methods.split(",")), tuple(args.proposals.split(","))
    if not set(methods) <= {"rl", "random", "greedy", "sa"}:
        parser.error("invalid method")
    if not set(proposals) <= {"uniform", "cluster_guided"}:
        parser.error("invalid proposal")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    workload = make_toy_workload(batch=args.batch, channels=args.channels, spatial=args.spatial)
    hardware = HardwareSpec()
    source_hash, sources = source_identity()
    input_identity = hashlib.sha256(json.dumps({"source": source_hash, "workload": workload.fingerprint,
                         "hardware": asdict(hardware), "microbatch": args.microbatch,
                         "group_layers": args.max_group_layers, "candidates": args.max_per_operator,
                         "horizon": args.horizon, "window": args.pipeline_window,
                         "initial": args.initial}, sort_keys=True).encode()).hexdigest()
    metadata = {
        "experiment": "real HybridEvaluator search budget curve on hand-checkable residual workload",
        "synthetic_oracle": False,
        "calibration_status": hardware.calibration_status,
        "budget_definition": "cumulative unique mapping calls; initial mapping consumes one; cache hits separate",
        "curve_definition": "checkpoint continuation at increasing budgets, not independent restarts",
        "initial_mapping": args.initial, "weight_policy": "cold",
        "checkpoint_every_steps": args.checkpoint_every,
        "action_space": "Gemini OP1-OP5 plus explicitly labelled OP4 idle-pool acquire/release and nearest-legal multi-core resize extensions",
        "fairness": "independent evaluator/search caches per method, seed and proposal; identical initial plan/resources",
        "input_identity": input_identity, "source_identity": source_hash, "source_hashes": sources,
        "workload": workload.to_dict(), "hardware": asdict(hardware),
        "budgets": args.budgets, "seeds": args.seeds, "methods": methods, "proposals": proposals,
        "created_at_unix_s": time.time(), "trials": [],
    }
    metadata_path = out / "validation.json"
    if args.resume and metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous["input_identity"] != input_identity:
            raise ValueError("validation source/workload/hardware/settings changed; use a new output directory")
    save_json(out / "inputs.json", {key: value for key, value in metadata.items() if key != "trials"})
    for proposal in proposals:
        for seed in args.seeds:
            for method in methods:
                current_hash, _ = source_identity()
                if current_hash != source_hash:
                    raise RuntimeError("hybrid implementation changed during validation; finished trials are preserved")
                evaluator = HybridEvaluator(workload, hardware, max_inflight_microbatches=args.pipeline_window, trace=False)
                package = evaluator.package
                cores, memories = package.mapping_core_ids, package.memory_ids
                initializer = balanced_mapping if args.initial == "balanced" else initial_mapping
                options = {"hardware": hardware, "weight_policy": "cold"} if args.initial == "balanced" else {}
                plan = initializer(workload, cores, memories, args.microbatch,
                                   args.max_group_layers, pipeline=True, **options)
                clusters = {core: package.node_cluster[core.split("/")[0]] for core in cores}
                positions = {core: package.positions[core.split("/")[0]] for core in cores}
                memory_positions = {memory: package.positions[memory] for memory in memories}
                checkpoint = out / "checkpoints" / f"{proposal}_{method}_seed{seed}.json"
                curve_path = out / "curves" / f"{proposal}_{method}_seed{seed}.json"
                curve = []
                if args.resume and curve_path.exists():
                    saved_curve = json.loads(curve_path.read_text(encoding="utf-8"))
                    if saved_curve["input_identity"] != input_identity:
                        raise ValueError("saved trial identity differs")
                    curve = saved_curve["curve"]
                for budget in args.budgets:
                    existing = next((item for item in curve if item["budget"] == budget), None)
                    if existing is not None:
                        continue
                    result = run_search(workload, plan, evaluator, cores, memories,
                                        method=method, seed=seed, budget=budget, horizon=args.horizon,
                                        max_per_operator=args.max_per_operator, checkpoint_path=checkpoint,
                                        checkpoint_every=args.checkpoint_every,
                                        resume=checkpoint.exists() and (args.resume or bool(curve)),
                                        evaluator_identity=evaluator.identity + ":" + source_hash,
                                        proposal=proposal, core_clusters=clusters, core_positions=positions,
                                        memory_positions=memory_positions)
                    row = {"budget": budget, "evaluations": result.evaluations, "requests": result.requests,
                           "cache_hits": result.requests - result.evaluations,
                           "best_cost_relative_to_initial": result.best_cost,
                           "best_metrics": result.best_metrics, "initial_metrics": result.initial_metrics,
                           "best_plan": result.best_plan.to_dict(), "policy_updates": result.policy_updates,
                           "status": result.status, "elapsed_s": result.elapsed_s,
                           "learning_curve": [{"evaluations": item["evaluations"], "best_cost": item["best_cost"]}
                                              for item in result.trace],
                           "checkpoint": str(checkpoint)}
                    curve.append(row)
                    save_json(curve_path, {"input_identity": input_identity, "method": method,
                                            "seed": seed, "proposal": proposal, "curve": curve})
                    metrics = result.best_metrics
                    print(f"{proposal} {method} seed={seed} budget={budget} evals={result.evaluations} "
                          f"cost={result.best_cost:.6f} latency_us={metrics['latency_s']*1e6:.3f} "
                          f"energy_uJ={metrics['energy_j']*1e6:.3f}", flush=True)
                metadata["trials"].append({"method": method, "seed": seed, "proposal": proposal,
                                             "curve_path": str(curve_path), "curve": curve})
                save_json(metadata_path, metadata)
    metadata["completed"] = True
    metadata["completed_at_unix_s"] = time.time()
    save_json(metadata_path, metadata)
    print(f"Completed real hybrid validation: {metadata_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
