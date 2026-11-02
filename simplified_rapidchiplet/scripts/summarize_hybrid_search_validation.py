"""Write descriptive, source-pinned statistics for physical search curves."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean, stdev


def describe(values):
    return {"mean": mean(values), "sample_std": stdev(values) if len(values) > 1 else 0.0,
            "minimum": min(values), "maximum": max(values)}


def summarize(folder):
    metadata = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for trial in metadata["trials"]:
        for row in trial["curve"]:
            groups[(trial["proposal"], trial["method"], row["budget"])].append((trial["seed"], row))
    rows = []
    for (proposal, method, budget), items in sorted(groups.items()):
        stats = {"proposal": proposal, "method": method, "budget": budget,
                 "n": len(items), "seeds": [seed for seed, _ in items],
                 "edp_ratio": describe([item["best_cost_relative_to_initial"] for _, item in items]),
                 "latency_us": describe([item["best_metrics"]["latency_s"] * 1e6 for _, item in items]),
                 "energy_uJ": describe([item["best_metrics"]["energy_j"] * 1e6 for _, item in items]),
                 "edp_js": describe([item["best_metrics"]["latency_s"] * item["best_metrics"]["energy_j"] for _, item in items]),
                 "elapsed_s": describe([item["elapsed_s"] for _, item in items]),
                 "evaluations": [item["evaluations"] for _, item in items],
                 "statuses": [item["status"] for _, item in items]}
        rows.append(stats)
    report = {"source_identity": metadata["source_identity"], "input_identity": metadata["input_identity"],
              "completed": metadata.get("completed", False), "experiment": metadata["experiment"],
              "calibration_status": metadata["calibration_status"], "synthetic_oracle": metadata["synthetic_oracle"],
              "initial_mapping": metadata["initial_mapping"], "weight_policy": metadata["weight_policy"],
              "curve_definition": metadata["curve_definition"], "statistics": "arithmetic mean and sample standard deviation across seeds",
              "execution_parallelism": metadata.get("execution_parallelism", 1),
              "wall_time_notes": metadata.get("wall_time_notes", "serial execution"),
              "rows": rows}
    (folder / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    with (folder / "learning_curves.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("proposal", "method", "seed", "physical_evaluations", "best_edp_relative_to_initial"))
        for trial in metadata["trials"]:
            row = max(trial["curve"], key=lambda item: item["budget"])
            writer.writerow((trial["proposal"], trial["method"], trial["seed"], 1, 1.0))
            for point in row["learning_curve"]:
                writer.writerow((trial["proposal"], trial["method"], trial["seed"], point["evaluations"], point["best_cost"]))
    with (folder / "milestones.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("proposal", "method", "seed", "budget", "edp_ratio", "latency_s", "energy_j",
                         "nop_hop_bytes", "noc_hop_bytes", "logical_transfer_bytes", "dram_read_bytes"))
        for trial in metadata["trials"]:
            for row in trial["curve"]:
                metrics = row["best_metrics"]
                writer.writerow((trial["proposal"], trial["method"], trial["seed"], row["budget"],
                                 row["best_cost_relative_to_initial"], *(metrics.get(key) for key in
                                 ("latency_s", "energy_j", "nop_hop_bytes", "noc_hop_bytes", "logical_transfer_bytes", "dram_read_bytes"))))
    with (folder / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("proposal", "method", "budget", "n", "edp_ratio_mean", "edp_ratio_sample_std",
                         "latency_us_mean", "energy_uJ_mean", "edp_js_mean", "elapsed_s_mean"))
        for row in rows:
            writer.writerow((row["proposal"], row["method"], row["budget"], row["n"],
                             row["edp_ratio"]["mean"], row["edp_ratio"]["sample_std"], row["latency_us"]["mean"],
                             row["energy_uJ"]["mean"], row["edp_js"]["mean"], row["elapsed_s"]["mean"]))
    lines = ["# Hybrid mapping search validation", "",
             "Real HybridEvaluator on the hand-checkable residual workload; reference-inspired, uncalibrated analytic PPA/energy. "
             "These results validate the implemented search/evaluator integration and compare search behavior on this workload. "
             "They do not establish silicon accuracy or generalization to ResNet-50.", "",
             f"Source identity: `{metadata['source_identity']}`. Initializer: `{metadata['initial_mapping']}`; weights: `{metadata['weight_policy']}`. "
             f"Experiment completed: `{metadata.get('completed', False)}`.", "",
             "Each number below summarizes independent seed trials with identical initial mapping, hardware, physical-evaluation budget and objective. "
             "EDP is relative to the fixed initial physical EDP; lower is better. Curves use checkpoint continuation. "
             "Standard deviations are across the listed seeds, with no significance claim.", "",
             "| Proposal | Search | Queries | Seeds | EDP ratio mean ± std | Latency mean (µs) | Energy mean (µJ) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        ratio = row["edp_ratio"]
        lines.append(f"| {row['proposal']} | {row['method']} | {row['budget']} | {row['n']} | "
                     f"{ratio['mean']:.5f} ± {ratio['sample_std']:.5f} | {row['latency_us']['mean']:.3f} | {row['energy_uJ']['mean']:.3f} |")
    lines.extend(["", "All methods share Gemini OP1–OP5 and the explicitly labelled hybrid idle-pool/nearest-legal-resize extensions. "
                  "Cluster-guided proposals are a separate locality/demand heuristic ablation. "
                  "The RL actor/value weights are learned and checkpointed; performance advantage is determined by the measured table.", ""])
    if metadata.get("execution_parallelism", 1) > 1:
        lines.extend([metadata["wall_time_notes"] + ".", ""])
    if len(metadata["methods"]) == 1:
        lines.extend(["This is a single-method continuation curve. No comparison with another method at this experiment's final query budget was run.", ""])
    for proposal in sorted({row["proposal"] for row in rows}):
        final_budget = max(row["budget"] for row in rows if row["proposal"] == proposal)
        at_budget = [row for row in rows if row["proposal"] == proposal and row["budget"] == final_budget]
        winner = min(at_budget, key=lambda row: row["edp_ratio"]["mean"])
        if len(at_budget) > 1:
            lines.append(f"At the {final_budget}-query ceiling, `{winner['method']}` has the lowest measured mean EDP for `{proposal}` "
                         f"({winner['edp_ratio']['mean']:.5f} of the initial EDP across {winner['n']} seeds).")
        else:
            lines.append(f"At the {final_budget}-query ceiling, `{winner['method']}` reached mean EDP {winner['edp_ratio']['mean']:.5f} "
                         f"for `{proposal}` across {winner['n']} seeds; same-budget baseline methods were not measured.")
    incomplete = [row for row in rows if any(status != "evaluation_budget_exhausted" for status in row["statuses"])]
    if incomplete:
        lines.extend(["", "Some runs ended before their query ceiling; inspect `summary.json` statuses and actual evaluation counts before interpreting those comparisons."])
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    report = summarize(args.folder.resolve())
    print(f"Wrote summary.json/csv/md and learning_curves.csv/milestones.csv for {len(report['rows'])} comparisons.")
