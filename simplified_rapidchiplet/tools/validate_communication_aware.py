"""Reproduce exact-flow checks, nontrivial toy gap, and baseline invariants."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from simple_rapidchiplet.config import load_config
from simple_rapidchiplet.model_parser import extract_reference_graph
from simple_rapidchiplet.physical_dse import PhysicalOracle, exhaustive_physical, physical_profile, q_learning_physical, score
from simple_rapidchiplet.physical_evaluator import evaluate_physical
from simple_rapidchiplet.physical_report import summary_row, write_csv, write_json, write_physical_outputs
from simple_rapidchiplet.rapidchiplet_engine import _load_rapidchiplet_module
from simple_rapidchiplet.toy_model import make_toy_graph


def verify_invariants(graph, evaluation):
    tensors, ops = graph.tensor_map, graph.operation_map
    primary = {row["tensor_id"]:row["owners"] for row in evaluation.derived.ownership_trace}
    requirements = {row["operator_id"]:row["input_requirements"] for row in evaluation.derived.operator_workloads}
    previous_finish = 0
    for row in evaluation.operator_timings:
        assert row["start_ns"] >= previous_finish
        assert row["compute_start_ns"] >= row["start_ns"]
        assert sum(shard["macs"] for shard in row["shards"]) == row["macs"]
        previous_finish = row["finish_ns"]
    m = evaluation.metrics
    assert abs(previous_finish-m["total_latency_ns"]) < 1e-6
    assert abs(m["total_latency_ns"]-sum(m[name] for name in ("compute_latency_ns","network_latency_ns","transition_latency_ns"))) < 1e-5
    covered = [i for event in evaluation.communication_events for i in event["flow_indices"]]
    assert sorted(covered) == list(range(len(evaluation.derived.workload.flows)))
    transferred = {}
    for flow in evaluation.derived.workload.flows:
        tensor = tensors[flow.tensor_id]
        assert tensor.source != "EXTERNAL" and flow.src != flow.dst
        assert flow.bytes == (flow.channel_end-flow.channel_start)*tensor.elements_per_channel*tensor.bytes_per_element
        assert any(owner["chiplet"] == flow.src and owner["start"] <= flow.channel_start < flow.channel_end <= owner["end"]
                   for owner in primary[flow.tensor_id])
        assert any(req["tensor_id"] == flow.tensor_id and req["destination"] == flow.dst and
                   any(start <= flow.channel_start < flow.channel_end <= end for start,end in req["required_ranges"])
                   for req in requirements[flow.consumer_operator])
        key = flow.tensor_id,flow.dst
        for start,end in transferred.get(key,()):
            assert min(end,flow.channel_end) <= max(start,flow.channel_start), "duplicate resident version/slice transfer"
        transferred.setdefault(key,[]).append((flow.channel_start,flow.channel_end))
    assert sum(row["load_bytes"] for row in m["per_link_statistics"]) == m["hop_weighted_traffic_bytes"]
    return dict(flow_count=m["flow_count"],all_flows_necessary=True,no_duplicate_slice_transfers=True,
                mac_conservation=True,serial_timeline=True,all_flows_counted_once=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",default=str(ROOT/"results/communication_aware_validation"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    cfg = load_config(ROOT/"configs/defaults.json")
    graph = extract_reference_graph(cfg.reference_model)
    rc = _load_rapidchiplet_module(cfg.rapidchiplet.root)
    original, injected = rc.rapidchiplet, []
    def capture(inputs,*arguments,**keywords):
        injected.append(dict(inputs["traffic_by_chiplet"]))
        return original(inputs,*arguments,**keywords)
    rows, checks = [], []
    for n in (1,2,4,16):
        with patch.object(rc,"rapidchiplet",side_effect=capture):
            evaluation = evaluate_physical(graph,n,(tuple(range(n)),)*len(graph.blocks),cfg)
        assert injected[-1] == evaluation.derived.workload.traffic_bits_per_inference
        assert sum(injected[-1].values()) == evaluation.metrics["total_traffic_bytes"]*8
        assert evaluation.metrics["backend"] == "official_rapidchiplet"
        checks.append(dict(N_total=n,official_injection_matches=True,**verify_invariants(graph,evaluation)))
        rows.append(evaluation.metrics)
    write_csv(out/"uniform_mesh_baselines.csv",[{key:value for key,value in row.items() if key not in ("connection_graph","per_link_statistics")} for row in rows])
    write_json(out/"real_graph_invariants.json",checks)
    toy, toy_cfg = make_toy_graph(channels=32),replace(cfg,max_chiplets=4)
    profile = physical_profile(toy,toy_cfg,"latency")
    exact = exhaustive_physical(PhysicalOracle(toy,toy_cfg,profile))
    comparisons = []
    for seed in (7,8,9):
        run = q_learning_physical(PhysicalOracle(toy,toy_cfg,profile),budget=64,seed=seed)
        optimum, found = score(exact.best,profile),score(run.best,profile)
        comparison = dict(seed=seed,scope="identical bounded ordered action space",exhaustive_complete=exact.complete,
                    exhaustive_evaluations=exact.unique_evaluations,rl_evaluations=run.unique_evaluations,
                    exhaustive_best=summary_row(exact.best,profile),rl_best=summary_row(run.best,profile),
                    cost_gap_percent=100*(found["weighted_cost"]-optimum["weighted_cost"])/optimum["weighted_cost"])
        assert comparison["cost_gap_percent"] >= -1e-8
        write_physical_outputs(out/f"nontrivial_toy_seed{seed}",run,toy,toy_cfg,comparison=comparison)
        comparisons.append(comparison)
    write_json(out/"multi_seed_toy_comparison.json",comparisons)
    write_csv(out/"multi_seed_toy_comparison.csv",comparisons)
    print(json.dumps(dict(real_graph_checks=checks,toy_exact_evaluations=exact.unique_evaluations,
                         toy_seed_gaps=[(row["seed"],row["cost_gap_percent"]) for row in comparisons])))


if __name__ == "__main__":
    main()
