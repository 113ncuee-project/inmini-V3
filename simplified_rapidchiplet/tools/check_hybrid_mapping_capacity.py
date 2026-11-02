"""Append costed SRAM alternatives to the frozen ResNet mapping validation.

Completed rows are retained. Capacity alternatives keep the original assignment,
partition, grouping, batch and admission window so SRAM and weight reuse are the
only intended changes. Every new row uses a fresh native physical evaluator.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.search import plan_fingerprint, plan_from_dict
from simple_rapidchiplet.hybrid.workload import extract_resnet50


def source_pins():
    root = Path(__file__).resolve().parents[1] / "simple_rapidchiplet" / "hybrid"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.glob("*.py"))}


def save(path, data):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def comparison(candidate, reference, keys):
    eligible = candidate["feasible"] and reference["feasible"]
    return {"eligible": eligible,
            "fractional_reduction": {key: 1 - candidate[key] / reference[key] for key in keys} if eligible else None,
            "reason": "both mappings pass physical capacity checks" if eligible else "at least one mapping fails physical capacity; no gain is scored"}


def main():
    directory = Path(__file__).resolve().parents[1] / "results"
    base = directory / "hybrid_mapping_validation.json"
    output = directory / "hybrid_mapping_capacity_validation.json"
    record = json.loads(output.read_text(encoding="utf-8")) if output.exists() else json.loads(base.read_text(encoding="utf-8"))
    source = source_pins()
    if record.get("source_before") != source or any(row["source_at_result"] != source for row in record["rows"]):
        raise RuntimeError("completed reference rows must match the current frozen source")
    record.setdefault("base_validation", {"path": str(base), "status_at_read": record["status"],
                                         "runner_sha256": record["runner_sha256"],
                                         "note": "base runner may continue writing its own file; capacity output is independent"})
    hardware = HardwareSpec(**record["hardware"])
    window = record["max_inflight_microbatches"]
    record.setdefault("capacity_validation", {
        "source_before": source,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": "same 2 MiB reference plan; fresh evaluator and native placement for each 4 MiB row; no completed evaluations rerun; independent output avoids base-runner file races",
        "comparison_rule": "latency/energy/traffic reductions are reported only for two feasible mappings"})
    for row in record["rows"]:
        row.setdefault("hardware", record["hardware"])
        row.setdefault("max_inflight_microbatches", window)
        row.setdefault("plan_fingerprint", plan_fingerprint(plan_from_dict(row["plan"])))
    by_name = {row["name"]: row for row in record["rows"]}
    cold_plan = plan_from_dict(by_name["batch8_g3_cold"]["plan"])
    reuse_plan = plan_from_dict(by_name["batch8_g3_persistent"]["plan"])
    reuse_as_cold = replace(reuse_plan, layer_mappings=tuple(replace(layer, weight_policy="cold") for layer in reuse_plan.layer_mappings))
    if plan_fingerprint(cold_plan) != plan_fingerprint(reuse_as_cold):
        raise RuntimeError("reuse comparison changes mapping beyond weight residency policy")
    record["capacity_validation"]["reuse_mapping_identical_except_weight_policy"] = True
    base_metrics = {name: row["metrics"] for name, row in by_name.items()}
    keys = ("latency_s", "energy_j", "dram_read_bytes")
    temporal_comparison = comparison(base_metrics["batch8_g3_persistent"], base_metrics["batch8_g1_temporal_persistent"], keys + ("dram_write_bytes",)) if "batch8_g1_temporal_persistent" in base_metrics else {"eligible": False, "fractional_reduction": None, "reason": "optional temporal baseline is still running"}
    record["comparisons"] = {
        "reuse_vs_cold_2MiB": comparison(base_metrics["batch8_g3_persistent"], base_metrics["batch8_g3_cold"], keys),
        "grouped_vs_temporal_2MiB": temporal_comparison,
        "reuse_vs_cold_4MiB": {"eligible": False, "fractional_reduction": None, "reason": "capacity alternatives not yet completed"}}
    record["status"] = "capacity_in_progress"
    save(output, record)
    workload = extract_resnet50(batch_size=8)
    # Rebuild only the reference physical context; completed schedules are not
    # rerun. This pays native geometry and leakage for the capacity comparison.
    reference_context = HybridEvaluator(workload, hardware, trace=False, max_inflight_microbatches=window).context
    record["capacity_validation"]["reference_native_physical_context"] = reference_context.to_dict()
    variant = replace(hardware, unified_buffer_bytes=4 * 1024 * 1024)
    for policy in ("cold", "persistent"):
        name = f"batch8_g3_{policy}_ub4MiB"
        if name in by_name:
            continue
        if source_pins() != source:
            raise RuntimeError("frozen source changed; completed rows retained")
        baseline = by_name[f"batch8_g3_{policy}"]
        if baseline["workload_fingerprint"] != workload.fingerprint:
            raise RuntimeError("workload does not match the completed reference")
        plan = plan_from_dict(baseline["plan"])
        start = time.perf_counter()
        print(f"Starting {name} with unchanged mapping, window {window}", flush=True)
        evaluator = HybridEvaluator(workload, variant, trace=False, max_inflight_microbatches=window)
        result = evaluator.evaluate(plan)
        row = {"name": name, "elapsed_s": time.perf_counter() - start,
               "source_at_result": source_pins(), "hardware": asdict(variant),
               "max_inflight_microbatches": window, "weight_policy": policy, "pipeline": True,
               "plan": plan.to_dict(), "plan_fingerprint": plan_fingerprint(plan),
               "mapping_reference": baseline["name"], "mapping_identical_to_reference": plan_fingerprint(plan) == baseline["plan_fingerprint"],
               "workload_fingerprint": workload.fingerprint, "metrics": result.metrics,
               "native_physical_context": result.context.to_dict()}
        record["rows"].append(row)
        by_name[name] = row
        save(output, record)
        print(json.dumps({"name": name, "elapsed_s": row["elapsed_s"], "feasible": result.metrics["feasible"],
                          "latency_s": result.metrics["latency_s"], "area_mm2": result.metrics["area_mm2"],
                          "idle_power_w": result.metrics["idle_power_w"],
                          "peak_ub_bytes": max(result.metrics["buffer_peak_bytes"].values(), default=0),
                          "violations": result.metrics["violations"][:3]}), flush=True)
    # Merge any baseline that finished meanwhile without overwriting its file.
    latest_base = json.loads(base.read_text(encoding="utf-8"))
    if latest_base.get("source_before") != source or any(row["source_at_result"] != source for row in latest_base["rows"]):
        raise RuntimeError("base source changed while capacity validation ran")
    record["base_validation"]["status_at_finish"] = latest_base["status"]
    if "optional_temporal_baseline" in latest_base:
        record["optional_temporal_baseline"] = latest_base["optional_temporal_baseline"]
        temporal_comparison = {"eligible": False, "fractional_reduction": None,
                               "reason": "optional temporal baseline was stopped after its authorized wall limit; no physical result is available"}
    for row in latest_base["rows"]:
        if row["name"] in by_name:
            continue
        row.update(hardware=asdict(hardware), max_inflight_microbatches=window,
                   plan_fingerprint=plan_fingerprint(plan_from_dict(row["plan"])))
        record["rows"].insert(3, row)
        by_name[row["name"]] = row
    metrics = {name: row["metrics"] for name, row in by_name.items()}
    temporal_comparison = comparison(metrics["batch8_g3_persistent"], metrics["batch8_g1_temporal_persistent"], keys + ("dram_write_bytes",)) if "batch8_g1_temporal_persistent" in metrics else temporal_comparison
    record["comparisons"] = {
        "reuse_vs_cold_2MiB": comparison(metrics["batch8_g3_persistent"], metrics["batch8_g3_cold"], keys),
        "grouped_vs_temporal_2MiB": temporal_comparison,
        "reuse_vs_cold_4MiB": comparison(metrics["batch8_g3_persistent_ub4MiB"], metrics["batch8_g3_cold_ub4MiB"], keys),
        "interpretation": "positive fraction means reduction; grouping changes both pipeline stages and balanced allocation; no gain is scored for physically infeasible results"}
    record["capacity_cost"] = {policy: {
        "mapping_unchanged": by_name[f"batch8_g3_{policy}_ub4MiB"]["mapping_identical_to_reference"],
        "total_unified_buffer_bytes": variant.compute_count * variant.unified_buffer_bytes,
        "additional_unified_buffer_bytes": variant.compute_count * (variant.unified_buffer_bytes - hardware.unified_buffer_bytes),
        "silicon_area_increase_mm2": metrics[f"batch8_g3_{policy}_ub4MiB"]["area_mm2"] - metrics[f"batch8_g3_{policy}"]["area_mm2"],
        "package_area_increase_mm2": metrics[f"batch8_g3_{policy}_ub4MiB"]["package_area_mm2"] - metrics[f"batch8_g3_{policy}"]["package_area_mm2"],
        "idle_power_w": metrics[f"batch8_g3_{policy}_ub4MiB"]["idle_power_w"],
        "idle_power_increase_w": metrics[f"batch8_g3_{policy}_ub4MiB"]["idle_power_w"] - reference_context.idle_power_w}
        for policy in ("cold", "persistent")}
    after = source_pins()
    record["capacity_validation"].update(source_after=after, source_stable=after == source)
    record.update(status="completed", source_after=after, source_stable=after == record["source_before"])
    save(output, record)
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
