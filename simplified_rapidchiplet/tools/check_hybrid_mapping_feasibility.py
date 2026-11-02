"""Source-pinned ResNet reuse/pipeline validation; no calibrated accuracy claim."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator
from simple_rapidchiplet.hybrid.hardware import HardwareSpec, build_package
from simple_rapidchiplet.hybrid.mapping import LayerGroup
from simple_rapidchiplet.hybrid.planner import balanced_mapping
from simple_rapidchiplet.hybrid.workload import extract_resnet50


def source_pins():
    root = Path(__file__).resolve().parents[1] / "simple_rapidchiplet" / "hybrid"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.glob("*.py"))}


def main():
    output = Path(__file__).resolve().parents[1] / "results" / "hybrid_mapping_validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    before = source_pins()
    hardware = HardwareSpec()
    package = build_package(hardware)
    workloads, evaluators = {}, {}
    record = {"status": "in_progress", "purpose": "source-pinned correctness/feasibility and reuse/pipeline comparison; not calibrated silicon prediction",
              "source_before": before,
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "hardware": asdict(hardware), "max_inflight_microbatches": 2, "rows": []}
    for name, batch, length, pipeline, weight_policy in (
            ("batch1_g3_cold", 1, 3, True, "cold"),
            ("batch8_g3_cold", 8, 3, True, "cold"),
            ("batch8_g3_persistent", 8, 3, True, "persistent"),
            ("batch8_g1_temporal_persistent", 8, 1, False, "persistent")):
        start = time.perf_counter()
        print(f"Starting {name}", flush=True)
        if batch not in workloads:
            workloads[batch] = extract_resnet50(batch_size=batch)
            evaluators[batch] = HybridEvaluator(workloads[batch], hardware, trace=False, max_inflight_microbatches=2)
        workload, evaluator = workloads[batch], evaluators[batch]
        plan = balanced_mapping(workload, package.mapping_core_ids, package.memory_ids,
                                microbatch_size=1, max_group_layers=length, pipeline=pipeline,
                                hardware=hardware, weight_policy=weight_policy)
        result = evaluator.evaluate(plan)
        metrics = result.metrics
        row = {"name": name, "elapsed_s": time.perf_counter() - start,
               "source_at_result": source_pins(), "plan": plan.to_dict(),
               "workload_fingerprint": workload.fingerprint,
               "weight_policy": weight_policy, "pipeline": pipeline,
               "metrics": {key: metrics[key] for key in ("evaluator_identity", "feasible", "violations",
                      "latency_s", "first_result_latency_s", "throughput_samples_s", "energy_j", "power_w",
                      "area_mm2", "package_area_mm2", "total_macs", "microbatch_size", "microbatch_count",
                      "group_count", "unit_count", "transfer_count", "dram_read_bytes", "dram_write_bytes",
                      "buffer_peak_bytes", "calibration_status")}}
        record["rows"].append(row)
        output.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps({"name": name, "elapsed_s": row["elapsed_s"], "feasible": metrics["feasible"],
                          "latency_s": metrics["latency_s"],
                          "peak_ub_bytes": max(metrics["buffer_peak_bytes"].values(), default=0),
                          "violations": metrics["violations"][:3]}), flush=True)
    after = source_pins()
    record.update(status="completed", source_after=after, source_stable=before == after)
    by_name = {row["name"]: row["metrics"] for row in record["rows"]}
    cold, reuse = by_name["batch8_g3_cold"], by_name["batch8_g3_persistent"]
    temporal = by_name["batch8_g1_temporal_persistent"]
    record["comparisons"] = {
        "reuse_vs_cold": {key: 1 - reuse[key] / cold[key] for key in ("latency_s", "energy_j", "dram_read_bytes")},
        "grouped_pipeline_vs_temporal": {key: 1 - reuse[key] / temporal[key] for key in ("latency_s", "energy_j", "dram_read_bytes", "dram_write_bytes")},
        "interpretation": "positive fraction means reduction; grouped case changes layer grouping and balanced core allocation together, so its gain is not attributed to pipeline alone",
    }
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
