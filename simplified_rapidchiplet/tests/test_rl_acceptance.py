"""Hand-checkable counterexamples required by the RL DSE acceptance spec."""
from types import SimpleNamespace
import unittest

from simple_rapidchiplet.hybrid.communication import Transfer
from simple_rapidchiplet.hybrid.diagnostics import _schedule_slack
from simple_rapidchiplet.hybrid.evaluator import HybridEvaluator, _transfer_service
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.mapping import (
    LayerGroup, LayerMapping, MappingPlan, Partition, TensorRegion, compile_mapping,
    initial_mapping,
)
from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures
from simple_rapidchiplet.hybrid.rl_actions import apply_transaction, resized_mapping
from simple_rapidchiplet.hybrid.rl_schema import DesignState, make_action_plan
from simple_rapidchiplet.hybrid.rl_search import JointObjective, compute_reward, executable
from simple_rapidchiplet.hybrid.scheduler import Job, peak_interval_bytes, schedule_jobs
from simple_rapidchiplet.hybrid.workload import make_toy_workload


class RLPhysicalAcceptanceTests(unittest.TestCase):
    def test_improving_noncritical_branch_keeps_e2e_latency(self):
        def schedule(short_branch):
            return schedule_jobs((
                Job("critical", (), ("core:0",), 10.0, energy_j=10.0),
                Job("slack", (), ("core:1",), short_branch, energy_j=short_branch),
                Job("Add", ("critical", "slack"), ("core:2",), 1.0),
            ))
        old, new = schedule(4.0), schedule(1.0)
        self.assertEqual(old.makespan_s, 11.0)
        self.assertEqual(new.makespan_s, 11.0)
        self.assertEqual(_schedule_slack(old)["critical"], 0.0)
        self.assertEqual(_schedule_slack(old)["slack"], 6.0)
        self.assertEqual(_schedule_slack(new)["slack"], 9.0)
        self.assertLess(sum(e.job.energy_j for e in new.events), sum(e.job.energy_j for e in old.events))

    def test_fewer_hops_can_increase_congestion_and_e2e(self):
        hardware = HardwareSpec()
        region = TensorRegion.full((1, 1, 1, 1))
        # Three simultaneous 1 B flows on three separate 2-hop paths each take
        # max(1 B / 1 B/s) = 1 s. Moving them to the same 1-hop bottleneck uses
        # half the hop-bytes but serializes them into [0,1], [1,2], [2,3].
        def run(shared):
            endpoints = [("shared_a", "shared_b") if shared else ("s" + str(i), "d" + str(i))
                         for i in range(3)]
            paths = {endpoints[i]: (("shared_a", "shared_b") if shared else
                     ("s" + str(i), "m" + str(i), "d" + str(i))) for i in range(3)}
            links = {pair: 1.0 for path in paths.values() for pair in zip(path, path[1:])}
            context = SimpleNamespace(route=lambda src, dst: paths[(src, dst)],
                                      latency_ns=lambda src, dst: 0.0,
                                      link_bandwidth_Bps=links,
                                      link_energy_pj_per_bit={pair: 1.0 for pair in links})
            jobs, hop_bytes = [], 0
            for i in range(3):
                source, destination = endpoints[i]
                flow = Transfer(str(i), source, (destination,), 1, (), (),
                                "activation", "x", region, 0)
                duration, resources, stats = _transfer_service(flow, hardware, context)
                self.assertEqual(duration, 1.0)
                hop_bytes += stats["nop_hop_bytes"]
                jobs.append(Job(flow.id, (), resources, duration, kind="transfer"))
            schedule = schedule_jobs(jobs)
            return schedule, hop_bytes
        long_routes, old_hops = run(False)
        short_routes, new_hops = run(True)
        self.assertEqual((old_hops, new_hops), (6, 3))
        self.assertEqual(long_routes.makespan_s, 1.0)
        self.assertEqual(short_routes.makespan_s, 3.0)
        self.assertEqual(sum(event.start_s for event in short_routes.events), 3.0)

    def test_tail_tiles_and_halo_match_exact_conv_regions(self):
        workload = make_toy_workload(batch=1, channels=5, spatial=5)
        cores = tuple(f"compute:0/core:{i}" for i in range(4))
        plan = MappingPlan((LayerGroup("g", tuple(layer.id for layer in workload.layers), "temporal"),),
            tuple(LayerMapping(layer.id, cores, Partition(h=2, w=2), tile_shape=(1, 0, 2, 2))
                  for layer in workload.layers))
        compiled = compile_mapping(workload, plan)
        for layer in workload.layers:
            units = [unit for unit in compiled.units if unit.layer_id == layer.id]
            self.assertEqual(len(units), 9)
            self.assertEqual(sum(unit.output_region.elements for unit in units), 125)
            for i, unit in enumerate(units):
                self.assertTrue(all(unit.output_region.intersection(other.output_region) is None
                                    for other in units[i + 1:]))
        conv = [unit for unit in compiled.units if unit.layer_id == "conv0"]
        first = next(unit for unit in conv if unit.output_region.bounds[2:] == ((0, 2), (0, 2)))
        tail = next(unit for unit in conv if unit.output_region.bounds[2:] == ((4, 5), (4, 5)))
        self.assertEqual(first.inputs[0].region.shape, (1, 5, 3, 3))
        self.assertEqual(tail.inputs[0].region.bounds, ((0, 1), (0, 5), (3, 5), (3, 5)))
        self.assertEqual(tail.macs, 5 * 5 * 3 * 3)
        self.assertEqual(sum(unit.macs for unit in compiled.units), workload.total_macs)

    def test_unfit_minimum_tile_is_rejected_instead_of_free_spill(self):
        workload = make_toy_workload(batch=1, channels=5, spatial=5)
        plan = MappingPlan((LayerGroup("g", tuple(layer.id for layer in workload.layers), "temporal"),),
                           tuple(LayerMapping(layer.id, ("compute:0/core:0",)) for layer in workload.layers))
        tiny = HardwareSpec(l1_weight_bytes=1, l1_activation_bytes=1, l1_output_bytes=1,
                            l2_weight_bytes=1, l2_activation_bytes=1, l2_output_bytes=1)
        with self.assertRaisesRegex(ValueError, "one output element"):
            compile_mapping(workload, plan, tiny)

    def test_live_shortcut_cache_psum_and_weights_all_pay_capacity(self):
        intervals = [(0, 10, 100),  # long-lived shortcut
                     (1, 5, 80), (5, 9, 80),  # activation buffer reuse
                     (2, 4, 30), (3, 7, 20), (0, 10, 50)]  # cache, psum, weights
        self.assertEqual(peak_interval_bytes(intervals), 280)
        self.assertEqual(peak_interval_bytes([(0, 5, 80), (5, 10, 80)]), 80)
        self.assertGreater(peak_interval_bytes(intervals), 256)

    def test_native_gemini_a9_expands_and_evacuates_without_dangling_work(self):
        candidates = enumerate_gemini_architectures(compute_counts=(1, 2), include_shapes=False)
        small, large = candidates
        for residual in (False, True):
            workload = make_toy_workload(batch=1, channels=5, spatial=5, residual=residual)
            mapping = initial_mapping(workload, small.package.mapping_core_ids, small.package.memory_ids,
                                      microbatch_size=1, max_group_layers=3, pipeline=False)
            state = DesignState(small.id, mapping, workload.fingerprint)
            base_eval = HybridEvaluator(workload, small.hardware, trace=False).evaluate(mapping)
            target_mapping = resized_mapping(workload, state, large)
            grow = make_action_plan(state, "C2", [("A9", {"architecture_candidate_id": large.id,
                                                       "mapping": target_mapping.to_dict()})])
            expanded = apply_transaction(workload, state, grow, candidates)
            large_eval = HybridEvaluator(workload, large.hardware, trace=False).evaluate(expanded.mapping)
            self.assertTrue(base_eval.metrics["feasible"])
            self.assertTrue(large_eval.metrics["feasible"])
            self.assertGreater(large_eval.metrics["area_mm2"], base_eval.metrics["area_mm2"])
            self.assertEqual(large_eval.metrics["compute_chiplets"], 2)
            self.assertEqual(large_eval.metrics["executed_macs"], workload.total_macs)
            # A9 explicitly includes the full evacuated mapping. Restoration is
            # a new independent full evaluation, not a reuse of the old cache.
            shrink = make_action_plan(expanded, "C3", [("A9", {"architecture_candidate_id": small.id,
                                                             "mapping": mapping.to_dict()})])
            restored = apply_transaction(workload, expanded, shrink, candidates)
            replay = HybridEvaluator(workload, small.hardware, trace=False).evaluate(restored.mapping)
            self.assertTrue(replay.metrics["feasible"])
            self.assertEqual(restored.fingerprint, state.fingerprint)
            self.assertTrue(all(set(item.chiplets) <= set(small.package.mapping_core_ids)
                                for item in restored.mapping.layer_mappings))
            self.assertEqual(tuple(restored.mapping.memory_ids), tuple(small.package.memory_ids))
            for metric in ("latency_s", "area_mm2", "power_w", "energy_j"):
                self.assertAlmostEqual(replay.metrics[metric], base_eval.metrics[metric], places=12)

    def test_native_gemini_dma_and_pe_glb_access_share_single_port(self):
        candidate = enumerate_gemini_architectures(compute_counts=(1,), include_shapes=False)[0]
        workload = make_toy_workload(batch=1, channels=5, spatial=5)
        mapping = initial_mapping(workload, candidate.package.mapping_core_ids, candidate.package.memory_ids,
                                  microbatch_size=1, max_group_layers=3, pipeline=False)
        evaluation = HybridEvaluator(workload, candidate.hardware).evaluate(mapping)
        self.assertTrue(evaluation.metrics["feasible"])
        calendars = {}
        for transfer in evaluation.communication.transfers:
            event = evaluation.schedule.event_map[transfer.id]
            endpoints = {endpoint for endpoint in (transfer.src, *transfer.dsts) if endpoint.startswith("compute:")}
            self.assertTrue(endpoints)
            self.assertTrue(all(f"{endpoint}:glb_port" in event.job.resources for endpoint in endpoints))
        for unit in evaluation.compiled.units:
            resource = f"{unit.chiplet}:glb_port"
            self.assertIn(resource, evaluation.schedule.event_map[f"read:{unit.id}"].job.resources)
            self.assertIn(resource, evaluation.schedule.event_map[unit.id].job.resources)
        for event in evaluation.schedule.events:
            for resource in event.job.resources:
                if resource.endswith(":glb_port") and event.finish_s > event.start_s:
                    calendars.setdefault(resource, []).append(event)
        self.assertEqual(len(calendars), 4)
        for events in calendars.values():
            events.sort(key=lambda event: event.start_s)
            self.assertTrue(any(event.job.kind == "core_read" for event in events))
            self.assertTrue(any(event.job.kind == "core_write" for event in events))
            self.assertTrue(any(event.job.kind not in {"core_read", "core_write"} for event in events))
            self.assertTrue(all(a.finish_s <= b.start_s + 1e-15 for a, b in zip(events, events[1:])))


class RLRewardAcceptanceTests(unittest.TestCase):
    @staticmethod
    def metrics(latency=10.0, area=10.0, power=2.0):
        return {"feasible": True, "latency_s": latency, "area_mm2": area,
                "power_w": power, "energy_j": power * latency}

    def test_fixed_gamma_one_improvement_telescopes_with_violation(self):
        objective = JointObjective(latency_weight=1, area_weight=1, power_weight=1,
                                   max_latency_s=8.0, violation_penalty=4)
        states = [self.metrics(latency=10), self.metrics(latency=8), self.metrics(latency=6)]
        reference = states[0]
        rewards = [compute_reward(old, new, reference, objective) for old, new in zip(states, states[1:])]
        self.assertAlmostEqual(objective.penalized_cost(states[0], reference), 2.0)
        self.assertAlmostEqual(rewards[0], 16 / 15)
        self.assertAlmostEqual(rewards[1], 1 / 15)
        self.assertAlmostEqual(sum(rewards), objective.penalized_cost(states[0], reference)
                               - objective.penalized_cost(states[-1], reference))
        self.assertFalse(objective.strict_feasible(states[0]))
        self.assertTrue(objective.strict_feasible(states[1]))

    def test_reward_has_no_chiplet_or_hop_bonus_and_worse_cost_is_negative(self):
        objective = JointObjective()
        old = self.metrics()
        changed = {**old, "compute_chiplets": 16, "nop_hop_bytes": 0}
        self.assertEqual(compute_reward(old, changed, old, objective), 0.0)
        self.assertLess(compute_reward(old, self.metrics(latency=12), old, objective), 0.0)
        self.assertFalse(executable({**old, "energy_j": float("nan")}))


if __name__ == "__main__":
    unittest.main()
