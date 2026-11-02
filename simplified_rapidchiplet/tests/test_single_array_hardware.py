"""Independent v0.2 conservation and routed-topology hand checks."""
from dataclasses import replace
import json
import unittest

from simple_rapidchiplet.hybrid.single_array_hardware import (
    ExperimentalAssumptions, PROFILE, SingleArrayHardware,
    build_single_array_noc, build_single_array_package, enumerate_single_array_hardware,
)


class SingleArrayHardwareTests(unittest.TestCase):
    def test_all_15_templates_conserve_resources(self):
        specs = enumerate_single_array_hardware()
        self.assertEqual(len(specs), 15)
        self.assertEqual({spec.compute_count for spec in specs}, {1, 2, 4, 8, 16})
        for spec in specs:
            self.assertEqual(len(spec.compute_slots), 16 * spec.compute_count)
            self.assertEqual(len(set(spec.compute_slots)), len(spec.compute_slots))
            self.assertTrue(all('/pe:' in name and '/core:' not in name for name in spec.compute_slots))
            totals = spec.resource_totals
            self.assertEqual(totals['physical_cores'], 0)
            self.assertEqual(totals['l1_bytes'], spec.compute_count * 2_883_584)
            self.assertEqual(totals['l2_bytes'], spec.compute_count * 1_048_576)
            self.assertEqual(totals['main_data_sram_bytes'], spec.compute_count * 3_932_160)
            self.assertEqual(totals['additional_ub_bytes'], 0)
            self.assertEqual(totals['vector_units'], spec.compute_count)
            self.assertEqual(spec.macs_per_cycle, 4096)

    def test_independent_bandwidth_and_IO_ledger(self):
        for rows, cols, ios, bandwidth in ((1, 1, 2, 16.384e9), (1, 2, 2, 16.384e9),
                                          (2, 2, 4, 32.768e9), (2, 4, 4, 32.768e9),
                                          (4, 4, 8, 65.536e9)):
            spec = SingleArrayHardware(rows, cols)
            self.assertEqual(spec.io_count, ios)
            self.assertEqual(spec.resource_totals['dram_bandwidth_Bps'], bandwidth)
            self.assertEqual(spec.resource_totals['dram_capacity_bytes'], ios * 512 * 1024**2)
        horizontal, vertical = SingleArrayHardware(1, 4), SingleArrayHardware(4, 1)
        self.assertEqual(horizontal.area_estimate['compute_per_die_mm2'], vertical.area_estimate['compute_per_die_mm2'])
        self.assertEqual(vertical.area_estimate['io_total_mm2'], 4 * horizontal.area_estimate['io_total_mm2'])
        self.assertEqual(horizontal.l2_bandwidth_Bps, 64e9)
        self.assertEqual(horizontal.dma_bandwidth_Bps, 16e9)

    def test_two_by_two_has_ten_single_full_duplex_links(self):
        spec = SingleArrayHardware(2, 2)
        graph = build_single_array_package(spec)
        d2d = [link for link in graph.links if link.kind == 'd2d_single_full_duplex']
        self.assertEqual(len(d2d), 10)
        self.assertTrue(all(link.bandwidth_Bps == 12.5e9 for link in d2d))
        ports = [(link.source, link.source_port) for link in d2d] + [(link.destination, link.destination_port) for link in d2d]
        self.assertEqual(len(set(ports)), 20)
        self.assertEqual(spec.resource_totals['reserved_d2d_ports'], 32)
        self.assertEqual(dict(graph.memory_owners), {f'memory:{i}': f'io:{i}' for i in range(4)})
        path = graph.route('memory:0', 'compute:3')
        self.assertEqual(path[:2], ('memory:0', 'io:0'))
        self.assertEqual(path[-1], 'compute:3')

    def test_every_package_endpoint_reachable_with_optional_io_links(self):
        for include in (True, False):
            spec = SingleArrayHardware(4, 4, ExperimentalAssumptions(io_vertical_links=include))
            graph = build_single_array_package(spec)
            for source, _ in graph.coordinates:
                for destination, _ in graph.coordinates:
                    path = graph.route(source, destination)
                    self.assertEqual((path[0], path[-1]), (source, destination))
        with self.assertRaisesRegex(ValueError, 'physical network node'):
            graph.route('compute:0/core:0', 'memory:0')

    def test_noc_routes_pes_through_finite_gateways(self):
        spec = SingleArrayHardware(1, 1)
        graph = build_single_array_noc(spec)
        self.assertEqual(len([link for link in graph.links if link.kind == 'pe_mesh']), 24)
        gateways = [link for link in graph.links if link.kind == 'l2_gateway']
        self.assertEqual(len(gateways), 4)
        self.assertEqual(sum(link.bandwidth_Bps for link in gateways), spec.l2_bandwidth_Bps)
        self.assertEqual(len(graph.route('compute:0/pe:0', 'compute:0/pe:15')) - 1, 6)
        one_gateway = replace(spec, assumptions=replace(spec.assumptions, l2_gateway_pes=(0,)))
        self.assertEqual(sum(link.bandwidth_Bps for link in build_single_array_noc(one_gateway).links if link.kind == 'l2_gateway'), 16e9)

    def test_assumptions_and_costs_cannot_be_mistaken_for_old_profile(self):
        spec = SingleArrayHardware()
        data = spec.to_dict()
        self.assertEqual(data['profile_id'], PROFILE)
        self.assertEqual(data['physical_resources']['physical_cores_per_die'], 0)
        self.assertEqual(data['experimental_assumptions']['classification'], 'M')
        self.assertEqual(data['experimental_assumptions']['psum_storage_bytes'], 3)
        self.assertEqual(data['experimental_assumptions']['rounding'], 'nearest_ties_to_even')
        self.assertEqual(spec.assumptions.fifo_bytes_per_router, 1280)
        for name in ('l1_sram', 'l2_sram', 'vector_unit', 'dma', 'control', 'router_fifos',
                     'dma_descriptors', 'control_storage', 'pe_working_registers', 'reserved_d2d_phys'):
            self.assertGreater(data['area_estimate']['compute_per_die_mm2'][name], 0)
        self.assertNotIn('core_global_buffers', data['area_estimate']['compute_per_die_mm2'])
        self.assertNotIn('dram_controller_phy', data['area_estimate']['compute_per_die_mm2'])
        self.assertGreater(data['area_estimate']['io_per_die_mm2']['dram_controller_phy'], 0)
        self.assertEqual(spec.fingerprint, SingleArrayHardware().fingerprint)
        self.assertNotEqual(spec.fingerprint, replace(spec, compute_clock_hz=.5e9).fingerprint)
        self.assertEqual(spec.area_estimate, replace(spec, compute_clock_hz=.5e9).area_estimate)
        json.dumps(data, allow_nan=False)

    def test_packet_headers_and_partial_flits_are_paid(self):
        a = ExperimentalAssumptions()
        self.assertEqual(a.wire_bytes(0), 0)
        self.assertEqual(a.wire_bytes(1), 32)
        self.assertEqual(a.wire_bytes(256), 272)
        self.assertEqual(a.wire_bytes(257), 304)
        with self.assertRaises(ValueError):
            a.wire_bytes(-1)

    def test_profile_roundtrip_validates_fixed_resources_and_cost_version(self):
        spec = SingleArrayHardware(2, 4)
        data = json.loads(json.dumps(spec.to_dict()))
        self.assertEqual(SingleArrayHardware.from_dict(data), spec)
        data['physical_resources']['pe_count'] = 64
        with self.assertRaisesRegex(ValueError, 'versioned contract'):
            SingleArrayHardware.from_dict(data)

    def test_invalid_physical_contract_is_rejected(self):
        for rows, cols in ((0, 1), (1, 3), (True, 1), (2, 2.0)):
            with self.assertRaises(ValueError):
                SingleArrayHardware(rows, cols)
        with self.assertRaises(ValueError):
            ExperimentalAssumptions(on_die_topology='ring')
        with self.assertRaises(ValueError):
            ExperimentalAssumptions(l2_gateway_pes=(0, 0))
        with self.assertRaisesRegex(ValueError, 'spare boundary'):
            ExperimentalAssumptions(l2_gateway_pes=(5,))
        with self.assertRaises(ValueError):
            ExperimentalAssumptions(psum_storage_bytes=2)
        with self.assertRaises(ValueError):
            build_single_array_noc(SingleArrayHardware(1, 1), die=1)


if __name__ == '__main__':
    unittest.main()
