"""Reproducible toy joint-DSE ablations, with honest total-cost accounting.

Run with the bundled Python runtime (numpy required).  Each trial starts a fresh
process and records source hashes before/after, so development-time changes are
visible.  Fixed-count controls are reported separately from variable hardware.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (("atomic", "rl"), ("guided_atomic", "rl"), ("composite", "rl"),
            ("composite", "random"), ("composite", "greedy"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def source_manifest():
    files = sorted((ROOT / "simple_rapidchiplet" / "hybrid").glob("*.py"))
    files += [ROOT / "rl_dse.py", Path(__file__).resolve(), ROOT / "tests" / "test_rl_acceptance.py"]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def worker(folder):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from rl_dse import run_suite
    folder = Path(folder)
    config = json.loads((folder / "experiment_config.json").read_text(encoding="utf-8"))
    before = source_manifest()
    started = time.perf_counter()
    meta = {"started_utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
            "python_version": sys.version, "source_before": before,
            "source_identity_before": manifest_digest(before), "config": config}
    write_json(folder / "experiment_manifest.json", meta)
    try:
        result = run_suite(config, folder / "run", update=lambda **kw: print(kw.get("message", ""), flush=True))
        search_folder = folder / "run" / "toy"
        search = json.loads((search_folder / "joint_search.json").read_text(encoding="utf-8"))
        accounting = json.loads((search_folder / "accounting.json").read_text(encoding="utf-8"))
        seed_records = json.loads((search_folder / "seed_attempts.json").read_text(encoding="utf-8"))
        best = search.get("best_metrics")
        families = {}
        for family, row in search.get("family_statistics", {}).items():
            selected, valid = row["selected"], row["valid"]
            families[family] = {**row, "selection_rate": selected / row["proposed"] if row["proposed"] else 0,
                                "improvement_rate_among_valid": row["improved"] / valid if valid else None,
                                "mean_selected_evaluation_s": row["evaluation_elapsed_s"] / selected if selected else None}
        summary = {"name": folder.name, "scope": "fixed4" if config["dies"] == [4] else "variable",
                   "seed": config["seed"], "proposal": config["proposal"], "method": config["method"],
                   "strict_feasible": search["strict_feasible"], "best_cost": search["best_cost"],
                   "status": search["status"], "recommendation_status": result["recommendation_status"],
                   "best_architecture": search["best_state"]["architecture_candidate_id"] if search["best_state"] else None,
                   "ppa": {key: best.get(key) if best else None for key in
                           ("latency_s", "area_mm2", "power_w", "energy_j", "compute_chiplets", "io_chiplets", "total_chiplets")},
                   "limits": {key: config.get(key) for key in ("max_area", "max_power", "max_latency_ms")},
                   "best_violation": 0.0 if search["strict_feasible"] else None,
                   "rl_evaluations": search["evaluations"], "rl_requests": search["requests"],
                   "rl_cache_hits": search["cache_hits"], "steps": len(search["trace"]),
                   "policy_updates": search["policy_updates"], "search_elapsed_s": search["elapsed_s"],
                   "rl_evaluation_elapsed_s": search["evaluation_elapsed_s"],
                   "proposal_elapsed_s": search["proposal_elapsed_s"], "accounting": accounting,
                   "seed_evaluator_queries": sum(row["evaluator_queries"] for row in seed_records),
                   "seed_full_evaluations": sum(row.get("full_evaluations") or 0 for row in seed_records),
                   "seed_elapsed_s": sum(row["proposal_elapsed_s"] + row["evaluation_elapsed_s"] for row in seed_records),
                   "family_statistics": families,
                   "family_overhead_scope": "selected transition query only; greedy lookahead remains fully charged in rl_evaluation_elapsed_s, but is not attributable by family in the current trace",
                   "search_json": str((search_folder / "joint_search.json").relative_to(folder)),
                   "same_full_query_budget": search["evaluations"] == config["budget"],
                   "initial_cost_reference": {key: search["initial_metrics"][key] for key in
                                              ("latency_s", "area_mm2", "power_w", "energy_j")}}
        meta["status"] = "complete"
        meta["summary"] = summary
        write_json(folder / "summary.json", summary)
    except Exception as error:
        meta.update(status="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        traceback.print_exc()
    meta["elapsed_s"] = time.perf_counter() - started
    after = source_manifest()
    meta.update(source_after=after, source_identity_after=manifest_digest(after), source_stable=before == after)
    write_json(folder / "experiment_manifest.json", meta)
    return 0 if meta["status"] == "complete" else 1


def summarize(output):
    output = Path(output)
    trials = []
    for path in sorted(output.glob("*/experiment_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("status") == "complete":
            summary = {**manifest["summary"], "source_stable": manifest["source_stable"],
                       "source_identity": manifest["source_identity_before"], "total_elapsed_s": manifest["elapsed_s"]}
            trials.append(summary)
    groups = {}
    for trial in trials:
        key = trial["scope"], trial["proposal"], trial["method"]
        groups.setdefault(key, []).append(trial)
    aggregates = []
    for (scope, proposal, method), rows in sorted(groups.items()):
        values = [row["best_cost"] for row in rows if row["best_cost"] is not None]
        aggregates.append({"scope": scope, "proposal": proposal, "method": method,
                           "seeds": [row["seed"] for row in rows], "runs": len(rows),
                           "feasible_rate": sum(row["strict_feasible"] for row in rows) / len(rows),
                           "best_cost_mean": statistics.mean(values) if values else None,
                           "best_cost_stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
                           "cost_min": min(values) if values else None, "cost_max": max(values) if values else None,
                           "mean_total_elapsed_s": statistics.mean(row["total_elapsed_s"] for row in rows),
                           "mean_rl_elapsed_s": statistics.mean(row["search_elapsed_s"] for row in rows),
                           "all_same_query_budget": all(row["same_full_query_budget"] for row in rows),
                           "same_episode_reference": all(row["initial_cost_reference"] == rows[0]["initial_cost_reference"] for row in rows),
                           "source_stable": all(row["source_stable"] for row in rows)})
    data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "trials": trials, "aggregates": aggregates,
            "interpretation": "small toy smoke ablation; no statistical evidence of RL superiority; fixed/variable search spaces differ",
            "fairness": "same RL unique full-query budget within each scope; seed/report costs are separate and explicitly recorded; wall time is measured, not fixed",
            "accounting_definitions": "RL evaluations counts misses in the RL design cache, including an initial design that the seed backend may already cache; total_full_evaluations_this_process is the actual HybridEvaluator counter including seed and report replay",
            "source_identity_count": len({row["source_identity"] for row in trials})}
    write_json(output / "summary.json", data)
    columns = ["scope", "proposal", "method", "seed", "strict_feasible", "best_cost", "best_architecture",
               "latency_s", "area_mm2", "power_w", "energy_j", "rl_evaluations", "rl_requests",
               "seed_evaluator_queries", "steps", "policy_updates", "total_elapsed_s", "proposal_elapsed_s", "source_stable", "source_identity"]
    with (output / "trials.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in trials:
            writer.writerow({key: {**row, **row["ppa"]}.get(key) for key in columns})
    macro_columns = ["scope", "proposal", "method", "seed", "family", "supported", "proposed", "selected",
                     "valid", "improved", "selection_rate", "improvement_rate_among_valid",
                     "selected_query_elapsed_s", "mean_selected_query_s", "source_identity"]
    macro_rows = []
    for trial in trials:
        for family in (f"C{i}" for i in range(1, 11)):
            stats = trial["family_statistics"].get(family, {})
            proposed, selected, valid, improved = [stats.get(key, 0) for key in ("proposed", "selected", "valid", "improved")]
            elapsed = stats.get("evaluation_elapsed_s", 0.0)
            macro_rows.append({"scope": trial["scope"], "proposal": trial["proposal"], "method": trial["method"],
                               "seed": trial["seed"], "family": family, "supported": family != "C10",
                               "proposed": proposed, "selected": selected, "valid": valid, "improved": improved,
                               "selection_rate": selected / proposed if proposed else 0.0,
                               "improvement_rate_among_valid": improved / valid if valid else None,
                               "selected_query_elapsed_s": elapsed, "mean_selected_query_s": elapsed / selected if selected else None,
                               "source_identity": trial["source_identity"]})
    write_json(output / "macro_statistics.json", {"rows": macro_rows,
               "scope": "raw proposals before hard validity/shortlisting; selected query overhead excludes greedy lookahead; zero means unobserved, C10 is unsupported"})
    with (output / "macro_statistics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=macro_columns)
        writer.writeheader()
        writer.writerows(macro_rows)
    lines = ["# RL DSE toy smoke ablations", "", data["fairness"], "", data["interpretation"], "",
             "|Scope|Proposal|Method|Runs|Feasible|Mean best cost|Stdev|Mean total seconds|Full query budget met|Source stable|",
             "|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for row in aggregates:
        mean_cost = "none" if row["best_cost_mean"] is None else f"{row['best_cost_mean']:.6f}"
        lines.append(f"|{row['scope']}|{row['proposal']}|{row['method']}|{row['runs']}|{row['feasible_rate']:.2f}|"
                     f"{mean_cost}|{row['best_cost_stdev']:.6f}|{row['mean_total_elapsed_s']:.2f}|"
                     f"{row['all_same_query_budget']}|{row['source_stable']}|")
    lines += ["", "Per-run summary.json includes PPA, limits, archive result, macro proposal/selection/improvement rates, timing and seed/report costs.",
              "macro_statistics.csv/.json explicitly include C1-C10 for every run, including unobserved zero-count families and unsupported C10.",
              "Full transitions, behavior probabilities, diagnostics, checkpoint, model DAG and HTML report remain in each run/toy directory.",
              f"Distinct source manifests: {data['source_identity_count']}. Trials with differing or changing source hashes must be rerun before a controlled comparison."]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT.parent / "output" / "rl_dse_20261031" / "ablations")
    parser.add_argument("--budget", type=int, default=16)
    parser.add_argument("--seeds", default="3,7,11")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.summarize_only:
        summarize(args.out)
        return 0
    base = {"models": ["toy"], "batch": 1, "budget": args.budget, "fusion": "dp", "fusion_depth": 4,
            "seed_budget": 2, "groups": 3, "max_steps": max(64, 4 * args.budget), "horizon": 16,
            "shortlist": 16, "random_quota": 4, "max_per_family": 4, "preference": "balanced",
            "toy_channels": 5, "toy_spatial": 7,
            "max_area": 250.0, "max_power": 3.0, "max_latency_ms": 0.02,
            "strict_area": True, "strict_power": True, "strict_latency": True}
    jobs = []
    for seed in map(int, args.seeds.split(",")):
        for proposal, method in VARIANTS:
            jobs.append((f"variable_{proposal}_{method}_seed{seed}",
                         {**base, "seed": seed, "proposal": proposal, "method": method, "dies": [1, 2, 4, 8, 16]}))
        jobs.append((f"fixed4_composite_rl_seed{seed}",
                     {**base, "seed": seed, "proposal": "composite", "method": "rl", "dies": [4]}))
    def run(job):
        name, config = job
        folder = args.out / name
        if (folder / "experiment_manifest.json").is_file():
            previous = json.loads((folder / "experiment_manifest.json").read_text(encoding="utf-8"))
            if (previous.get("status") == "complete" and previous["config"] == config
                    and previous.get("source_stable") and previous.get("source_after") == source_manifest()):
                return name, 0
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "experiment_config.json", config)
        with (folder / "run.log").open("w", encoding="utf-8") as log:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(folder)],
                                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        return name, process.returncode
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run, job) for job in jobs]):
            name, code = future.result()
            print(json.dumps({"run": name, "returncode": code}), flush=True)
            if code:
                failures.append(name)
            summarize(args.out)
    write_json(args.out / "run_status.json", {"expected_runs": len(jobs), "failed": failures})
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
