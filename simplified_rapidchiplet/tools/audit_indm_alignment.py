"""Read-only model probes for the INDM architecture review (not a calibration).

Run from the repository root with .venv/Scripts/python.exe -X utf8 <this file>.
Writes only docs/indm_review_evidence.json; never changes native input files.
"""
from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import importlib
import io
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simplified_rapidchiplet"))
from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.physical_evaluator import evaluate_physical
from simple_rapidchiplet.toy_model import make_toy_graph
from simple_rapidchiplet.topology import Edge, Topology, make_mesh
from simple_rapidchiplet import rapidchiplet_engine as engine


def run():
    cfg = load_config(ROOT / "simplified_rapidchiplet/configs/defaults.json")
    graph = make_toy_graph(channels=32)
    assignments = ((0, 1, 2, 3),) * len(graph.blocks)
    variants = {
        "baseline": cfg,
        "PE_rows_8_to_16": replace(cfg, chiplet=replace(cfg.chiplet, pe_rows=16)),
        "SRAM_MiB_16_to_32": replace(cfg, chiplet=replace(cfg.chiplet, sram_mb=32)),
        "local_native_power_field_20p5_to_1": replace(cfg, rapidchiplet=replace(cfg.rapidchiplet, chiplet_power_w=1)),
        "proxy_BW_256_to_1": replace(cfg, network=replace(cfg.network, link_bandwidth_bits_per_cycle=1)),
        "local_internal_cycles_3_to_300": replace(cfg, chiplet=replace(cfg.chiplet, internal_latency_cycles=300)),
        "local_width_8p798_to_4": replace(cfg, chiplet=replace(cfg.chiplet, width_mm=4)),
    }
    samples = {}
    for name, candidate in variants.items():
        value = evaluate_physical(graph, 4, assignments, candidate)
        samples[name] = {
            key: value.metrics[key] for key in (
                "backend", "compute_latency_ns", "total_latency_ns", "total_area_mm2",
                "total_power_w", "total_chiplet_power_w", "total_link_power_w",
                "architecture_feasible", "max_link_utilization", "congested_link_count")
        }
        samples[name]["directed_BW_bits_per_cycle"] = sorted(set(value.network_context.link_bandwidths_bits_per_cycle.values()))
        samples[name]["path_cycles"] = sorted(set(value.network_context.path_latencies_cycles.values()))

    rc = engine._load_rapidchiplet_module(cfg.rapidchiplet.root)
    val = importlib.import_module("validation")
    def native_inputs(topology, config=cfg):
        return {
            "design": {"design_name": "indm_review_in_memory"},
            "verbose": False, "validate": True,
            "chiplets": engine._build_chiplets(config),
            "placement": engine._build_placement(topology, config),
            "topology": engine._build_topology(topology),
            "packaging": engine._read_rapidchiplet_json(config.rapidchiplet.root, config.rapidchiplet.packaging_file),
            "technologies": engine._read_rapidchiplet_json(config.rapidchiplet.root, config.rapidchiplet.technology_file),
            "routing_table": engine._build_splif_routing_table(topology.node_count, engine._build_topology(topology)),
            "traffic_by_chiplet": {},
        }

    def validation_messages(inputs, names):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            for name in names:
                val.validation_functions[name](inputs)
        return stream.getvalue()

    narrowed = variants["local_width_8p798_to_4"]
    overlapping = native_inputs(make_mesh(4, narrowed.chiplet.width_mm, narrowed.chiplet.spacing_mm), narrowed)
    invalid_layout = validation_messages(overlapping, ("placement",))
    overlap_pairs = []
    for index, left in enumerate(overlapping["placement"]["chiplets"]):
        dim_left = overlapping["chiplets"][left["name"]]["dimensions"]
        for other, right in enumerate(overlapping["placement"]["chiplets"][index+1:], index+1):
            dim_right = overlapping["chiplets"][right["name"]]["dimensions"]
            if all(max(left["position"][axis], right["position"][axis]) <
                   min(left["position"][axis]+dim_left[axis], right["position"][axis]+dim_right[axis]) for axis in ("x", "y")):
                overlap_pairs.append([index, other])
    mesh = make_mesh(4, cfg.chiplet.width_mm, cfg.chiplet.spacing_mm)
    extra = Edge(0, 3, 2 * (cfg.chiplet.width_mm + cfg.chiplet.spacing_mm))
    with_diagonal = replace(mesh, kind="mesh_plus_diagonal", edges=mesh.edges+(extra,))
    invalid_phy = validation_messages(native_inputs(with_diagonal), ("topology",))

    # A small heterogeneous package, using explicit placeholder die models.
    # This proves API support only; it does not reproduce INDM area or timing.
    pitch = cfg.chiplet.width_mm + cfg.chiplet.spacing_mm
    positions = {0: (0, 0), 1: (pitch, 0), 2: (pitch, pitch), 3: (2*pitch, 0)}
    star = Topology("io_relay_probe", 4, positions, tuple(Edge(a, b, pitch) for a, b in ((0, 1), (1, 2), (1, 3))))
    heterogeneous = native_inputs(star)
    template = heterogeneous["chiplets"][cfg.rapidchiplet.chiplet_name]
    heterogeneous["chiplets"] = {name: copy.deepcopy(template) for name in ("compute", "io", "memory")}
    for name, desc in heterogeneous["chiplets"].items():
        desc["type"] = name
        desc["relay"] = name == "io"
    for desc, name in zip(heterogeneous["placement"]["chiplets"], ("compute", "io", "compute", "memory")):
        desc["name"] = name
    heterogeneous["traffic_by_chiplet"] = {(0, 2): 32768, (3, 0): 32768}
    heterogeneous_validation = validation_messages(heterogeneous, ("chiplets", "packaging", "placement", "topology", "routing_table", "traffic_by_chiplet"))
    enabled = {metric: metric in ("area_summary", "power_summary", "link_summary", "latency", "throughput") for metric in rc.metrics}
    raw = rc.rapidchiplet(heterogeneous, {}, enabled, "indm_review_in_memory", verbose=False, validate=True)
    routes = engine._routes_for_traffic(heterogeneous["traffic_by_chiplet"], heterogeneous["routing_table"], 4)
    hetero_results = {
        "purpose": "API capability smoke test only, with copied generic die costs; not calibrated INDM hardware",
        "node_types": [row["name"] for row in heterogeneous["placement"]["chiplets"]],
        "routes": [{"pair": list(pair), "path": list(path)} for pair, path in routes.items()],
        "validation_output": heterogeneous_validation,
        "area_summary": raw["area_summary"], "latency_cycles": raw["latency"],
        "link_bandwidths": raw["link_summary"]["bandwidths"],
    }
    previous = json.loads((ROOT / "docs/communication_aware_validation.json").read_text(encoding="utf-8"))
    fractions = {}
    for name, row in previous["profiles"].items():
        fractions[name] = {
            "total_latency_ms": row["latency_ns"] / 1e6,
            "compute_latency_ms": row["compute_ns"] / 1e6,
            "communication_fraction_percent": 100 * (row["intra_comm_ns"] + row["cross_comm_ns"]) / row["latency_ns"],
            "N_total": row["N_total"],
        }
    search_results = {}
    for name in ("resnet50_balanced", "resnet50_latency"):
        with (ROOT / "simplified_rapidchiplet/results/communication_aware_validation" / name / "search_history.csv").open(newline="", encoding="utf-8-sig") as stream:
            history = list(csv.DictReader(stream))
        feasible = [row for row in history if row["feasible"] == "True"]
        winner = min(feasible, key=lambda row: float(row["weighted_cost"]))
        search_results[name] = {"first_best_episode": int(winner["episode"]),
                                "winner_in_initial_uniform_warm_starts": int(winner["episode"]) <= cfg.max_chiplets,
                                "best_weighted_cost": float(winner["weighted_cost"])}
    files = list((ROOT / "simplified_rapidchiplet/simple_rapidchiplet").glob("*.py"))
    files += [ROOT / "simplified_rapidchiplet/configs/defaults.json", Path(__file__)]
    files += [Path(cfg.rapidchiplet.root) / rel for rel in ("rapidchiplet.py", "validation.py", "helpers.py", cfg.rapidchiplet.chiplet_file, cfg.rapidchiplet.packaging_file, cfg.rapidchiplet.technology_file)]
    native_desc = engine._build_chiplets(cfg)[cfg.rapidchiplet.chiplet_name]
    evidence = {
        "date": "2026-10-04", "changes": "review artifacts only; no production or native input edits",
        "probe_workload": "two 1x1 Conv2d operators, each 32 channels, 2x2 spatial, FP32, all four compute chiplets active",
        "hardware_sensitivity": samples,
        "explicit_validation": {"narrowed_placement_upstream_output": invalid_layout,
                                "narrowed_placement_independent_AABB_overlaps": overlap_pairs,
                                "upstream_missed_real_overlap": bool(overlap_pairs) and not invalid_layout,
                                "mesh_plus_diagonal": invalid_phy,
                                "note": "Upstream validators print errors, not exceptions. In-memory inputs also bypass automatic read-time validation; a flag alone is insufficient."},
        "heterogeneous_native_smoke": hetero_results,
        "existing_results_communication_share": fractions,
        "existing_search_best_discovery": search_results,
        "existing_search_ablation": previous["ablation"],
        "effective_hardware": {"peak_TOPS_per_compute_die": cfg.chiplet.peak_tops,
                               "effective_TOPS_per_compute_die": cfg.chiplet.peak_tops * cfg.chiplet.utilization,
                               "native_chiplet": native_desc,
                               "native_packaging": heterogeneous["packaging"]},
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    }
    assert samples["baseline"]["backend"] == "official_rapidchiplet"
    assert samples["PE_rows_8_to_16"]["compute_latency_ns"] == samples["baseline"]["compute_latency_ns"] / 2
    assert all(samples[name]["total_power_w"] == samples["baseline"]["total_power_w"] for name in variants)
    assert len(overlap_pairs) == 6
    assert not invalid_layout  # Reproduces this local upstream version's incorrect vertical separation condition.
    assert "used multiple times" in invalid_phy
    assert not heterogeneous_validation
    assert routes[(0, 2)] == (0, 1, 2) and routes[(3, 0)] == (3, 1, 0)
    destination = ROOT / "docs/indm_review_evidence.json"
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"evidence": str(destination), "hardware_sensitivity": samples,
                      "independent_overlap_pairs": overlap_pairs,
                      "upstream_missed_real_overlap": True, "invalid_PHY_detected": True,
                      "native_IO_relay_smoke": "passed", "communication_share": fractions}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
