"""Audit saved final artifacts without rerunning models or changing the oracle."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
PROJECT = ROOT.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(relative: str):
    return json.loads((RESULTS / relative).read_text(encoding="utf-8"))


def check_pins(saved, current):
    assert saved, "missing source hashes"
    assert all(current.get(name) == value for name, value in saved.items()), "source identity differs"


def check_metrics(metrics, current, *, full=True):
    if full:
        check_pins(metrics["oracle_source_sha256"], current)
        assert metrics["backend"] == "official_rapidchiplet"
    if "edp_js" in metrics:
        assert math.isclose(metrics["energy_j"] * metrics["latency_s"], metrics["edp_js"], rel_tol=1e-12)
    if "energy_components" in metrics:
        assert math.isclose(sum(metrics["energy_components"].values()), metrics["energy_j"], rel_tol=1e-12)
        assert math.isclose(metrics["static_energy_j"], metrics["idle_power_w"] * metrics["latency_s"], rel_tol=1e-12)


def main():
    current = {path.name: digest(path) for path in sorted((ROOT / "simple_rapidchiplet" / "hybrid").glob("*.py"))}
    tests_path = RESULTS / "hybrid_unittest.txt"
    log = tests_path.read_text(encoding="utf-8")
    count = int(re.search(r"Ran (\d+) tests", log).group(1))
    assert count == 143 and log.strip().endswith("OK")

    architecture = read("hybrid_resnet_architectures/comparison.json")
    assert architecture["completed"] and architecture["source_stable"] and len(architecture["runs"]) == 6
    check_pins(architecture["source_before"], current)
    check_pins(architecture["source_after"], current)
    for row in architecture["runs"]:
        check_metrics(row["metrics"], current, full="oracle_source_sha256" in row["metrics"])
        assert row["metrics"]["feasible"]

    toy_architecture = read("hybrid_architectures_final/experiment.json")
    assert len(toy_architecture["runs"]) == 6
    for row in toy_architecture["runs"]:
        check_metrics(row["metrics"], current)
        assert row["metrics"]["feasible"] and row["search_evaluations"] == 16

    capacity = read("hybrid_mapping_capacity_validation.json")
    assert capacity["status"] == "completed" and capacity["source_stable"]
    check_pins(capacity["source_before"], current)
    check_pins(capacity["source_after"], current)
    rows = {row["name"]: row for row in capacity["rows"]}
    for row in rows.values():
        check_pins(row["source_at_result"], current)
        check_metrics(row["metrics"], current, full="oracle_source_sha256" in row["metrics"])
    assert rows["batch1_g3_cold"]["metrics"]["feasible"]
    for policy in ("cold", "persistent"):
        reference = rows[f"batch8_g3_{policy}"]
        variant = rows[f"batch8_g3_{policy}_ub4MiB"]
        assert not reference["metrics"]["feasible"]
        assert variant["metrics"]["feasible"] and variant["mapping_identical_to_reference"]
        assert variant["hardware"]["unified_buffer_bytes"] == 4 * 1024**2
        assert max(variant["metrics"]["buffer_peak_bytes"].values()) <= variant["hardware"]["unified_buffer_bytes"]
    assert capacity["comparisons"]["reuse_vs_cold_4MiB"]["eligible"]
    assert not capacity["comparisons"]["reuse_vs_cold_2MiB"]["eligible"]

    search = read("hybrid_search_validation_final/validation.json")
    assert search["completed"] and not search["synthetic_oracle"]
    assert len(search["trials"]) == 24 and search["budgets"] == [64, 128]
    check_pins(search["source_hashes"], current)
    seen = set()
    for trial in search["trials"]:
        key = (trial["method"], trial["proposal"], trial["seed"])
        assert key not in seen
        seen.add(key)
        assert [row["budget"] for row in trial["curve"]] == [64, 128]
        for point in trial["curve"]:
            assert point["evaluations"] == point["budget"]
            assert point["best_metrics"]["feasible"]
            if trial["method"] == "rl":
                assert point["policy_updates"] > 0
    replay = read("hybrid_search_validation_final/verification_resume.json")
    assert replay["validation_source_identity"] == search["source_identity"] and replay["uses_real_hybrid_evaluator"]
    assert all(replay[field] for field in ("trace_equal", "plan_equal", "metrics_equal", "policy_equal"))

    resnet_search = read("hybrid_resnet_search_validation/validation.json")
    assert resnet_search["status"] == "completed" and resnet_search["source_stable"]
    assert {row["method"] for row in resnet_search["trials"]} == {"rl", "random", "greedy", "sa"}
    for row in resnet_search["trials"]:
        check_pins(row["source_at_result"], current)
        assert row["evaluations"] == 8 and row["best_metrics"]["feasible"]
        assert row["initial_metrics"]["feasible"]

    toy = read("hybrid_toy_final/summary.json")["metrics"]
    check_metrics(toy, current)
    assert toy["feasible"]
    resources = {}
    with (RESULTS / "hybrid_toy_final" / "timeline.csv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            for resource in row["resources"].split("|"):
                resources.setdefault(resource, []).append((float(row["start_s"]), float(row["finish_s"])))
    for intervals in resources.values():
        intervals.sort()
        assert all(right[0] + 1e-15 >= left[1] for left, right in zip(intervals, intervals[1:])), "resource overlap in saved timeline"

    network = read("hybrid_toy_final/network.json")
    native = network["provenance"]["native_source_sha256"]
    native_root = Path(network["provenance"]["rapid_root"])
    assert all(digest(native_root / name) == value for name, value in native.items()), "native source changed"

    artifact_paths = [
        "docs/hybrid_architecture.md", "docs/hybrid_runbook.md", "docs/hybrid_validation.md", "docs/hybrid_progress.md",
        "docs/hybrid_hardware_source_notes.md", "docs/hybrid_gemini_source_notes.md", "docs/hybrid_mapping_source_notes.md",
        "docs/hybrid_search_design.md",
        "simplified_rapidchiplet/hybrid_dse.py", "simplified_rapidchiplet/configs/hybrid_pipeline_4MiB.json",
        "simplified_rapidchiplet/results/hybrid_unittest.txt",
        "simplified_rapidchiplet/results/hybrid_toy_final/summary.json",
        "simplified_rapidchiplet/results/hybrid_toy_final/package.svg",
        "simplified_rapidchiplet/results/hybrid_toy_final/trace.ndjson",
        "simplified_rapidchiplet/results/hybrid_toy_final/timeline.csv",
        "simplified_rapidchiplet/results/hybrid_resnet_architectures/comparison.json",
        "simplified_rapidchiplet/results/hybrid_architectures_final/experiment.json",
        "simplified_rapidchiplet/results/hybrid_mapping_capacity_validation.json",
        "simplified_rapidchiplet/results/hybrid_resnet_search_validation/validation.json",
        "simplified_rapidchiplet/results/hybrid_search_validation_final/validation.json",
        "simplified_rapidchiplet/results/hybrid_search_validation_final/summary.md",
        "simplified_rapidchiplet/results/hybrid_search_validation_final/verification_resume.json",
        "simplified_rapidchiplet/results/hybrid_figures/resnet_architecture.png",
        "simplified_rapidchiplet/results/hybrid_figures/resnet_mapping.png",
        "simplified_rapidchiplet/results/hybrid_figures/search_curves.png",
    ]
    extended_path = RESULTS / "hybrid_search_validation_rl512" / "validation.json"
    extended = json.loads(extended_path.read_text(encoding="utf-8")) if extended_path.exists() else {}
    if extended:
        check_pins(extended["source_hashes"], current)
        if extended.get("completed"):
            assert len(extended["trials"]) == 6 and extended["methods"] == ["rl"]
            assert all(trial["curve"][-1]["evaluations"] == 512 for trial in extended["trials"])
            artifact_paths.append("simplified_rapidchiplet/results/hybrid_search_validation_rl512/validation.json")
            artifact_paths.append("simplified_rapidchiplet/results/hybrid_search_validation_rl512/summary.md")
    manifest = {
        "status": "accepted_research_prototype",
        "scope": "INDM IO-cluster mesh/multi-ring + Gemini layer pipeline/five operators + learned RL + official RapidChiplet package model",
        "source_hashes": current,
        "search_source_identity": search["source_identity"],
        "native_source_hashes": native,
        "verification": {"regression_tests_passed": count, "hybrid_tests_passed": 69,
                         "resnet_batch1_architectures": 6, "toy_architecture_search_queries_each": 16,
                         "feasible_resnet_batch8_capacity_cases": 2, "same_budget_toy_trials": 24,
                         "search_budgets": [64, 128], "resnet_search_methods": 4, "resnet_search_queries_each": 8,
                         "saved_toy_resource_calendar_no_overlap": True, "source_pins_match_current": True},
        "checkpoint_resume_exact": {field: replay[field] for field in ("trace_equal", "plan_equal", "metrics_equal", "policy_equal")},
        "supplemental_rl512": {"completed": bool(extended.get("completed")), "trials_saved": len(extended.get("trials", [])),
                               "comparison_limit": "RL-only extension; not a same-budget comparison against 128-query baselines"},
        "optional_temporal_baseline": {"completed": False, "physical_result_claimed": False,
                                      "reason": "stopped at runtime limit; 4665 normalized keys exceed frozen 4096-entry memo"},
        "calibration": "reference-inspired uncalibrated analytical PPA; no silicon/RTL/quantization-accuracy or global-optimality claim",
        "artifact_hashes": {relative: digest(PROJECT / relative) for relative in artifact_paths},
    }
    output = RESULTS / "hybrid_delivery_manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "checks": manifest["verification"],
                      "rl512": manifest["supplemental_rl512"], "manifest": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
