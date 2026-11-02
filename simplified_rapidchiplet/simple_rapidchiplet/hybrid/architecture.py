"""Architecture partitioning with conserved compute/storage resources."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .hardware import HardwareSpec, build_package, fixed_mesh_hardware, validate_fixed_chiplet, CHIPLET_COUNTS, FIXED_CHIPLET_PROFILE, gemini_hardware, validate_gemini_chiplet, GEMINI_CHIPLET_PROFILE


def resource_totals(spec):
    count = spec.compute_count
    gemini = spec.package_topology == 'gemini_mesh'
    io_count = 2*spec.cluster_rows if gemini else (0 if spec.package_topology == 'compute_mesh' else spec.cluster_count)
    memory_count = io_count if gemini else spec.cluster_count
    return {
        "compute_dies": count,
        "io_dies": io_count,
        "memory_dies": memory_count,
        "total_chiplets": count+io_count,
        "total_dies": count+io_count+memory_count,
        "mapping_cores": spec.core_count,
        "pes": count * spec.pe_count,
        "macs_per_second": count * spec.macs_per_second,
        "l1_bytes": count * spec.pe_count * spec.l1_bytes_per_pe,
        "l2_weight_bytes": 0 if gemini else count * spec.l2_weight_bytes,
        "l2_activation_bytes": 0 if gemini else count * spec.l2_activation_bytes,
        "l2_output_bytes": 0 if gemini else count * spec.l2_output_bytes,
        "unified_bytes": count * spec.unified_buffer_bytes,
        "allocated_scratch_bytes": count * spec.prefetch_slots * (spec.pe_count * spec.l1_bytes_per_pe + (0 if gemini else spec.l2_bytes_per_die)),
        "dram_bandwidth_Bps": memory_count * spec.dram_bandwidth_Bps,
        "dram_capacity_bytes": memory_count * spec.dram_capacity_bytes,
    }


@dataclass(frozen=True)
class ArchitectureCandidate:
    id: str
    hardware: HardwareSpec
    conserved_resources: tuple[str, ...]

    @property
    def name(self):
        return self.id

    @property
    def spec(self):
        return self.hardware

    @property
    def package(self):
        return build_package(self.hardware)

    def to_dict(self):
        return {"id": self.id, "hardware": self.hardware.to_dict(),
                "resource_totals": resource_totals(self.hardware),
                "conserved_resources": self.conserved_resources,
                "chiplet_profile": GEMINI_CHIPLET_PROFILE if self.hardware.package_topology == 'gemini_mesh' else FIXED_CHIPLET_PROFILE if self.hardware.package_topology == 'compute_mesh' else 'legacy_indm_partition',
                "varying_costs": "chiplet count scales compute, SRAM, controllers, memory, silicon and leakage; every die retains identical hardware" if self.hardware.package_topology == 'compute_mesh' else "compute/control/PHY replication, IO/DDR/controller/crossbar, die yields and package network"}


def enumerate_architectures(reference=None, compute_counts=CHIPLET_COUNTS,
                            noc_topologies=("mesh",)):
    """Choose how many identical fixed chiplets to deploy on a direct mesh."""
    reference = reference or fixed_mesh_hardware()
    validate_fixed_chiplet(reference)
    if tuple(noc_topologies) != ('mesh',):
        raise ValueError('production architecture supports mesh only')
    candidates = []
    fixed = tuple(name for name in reference.__dataclass_fields__ if name not in ('cluster_rows','cluster_cols'))
    for count in compute_counts:
        spec = fixed_mesh_hardware(count)
        build_package(spec)
        candidates.append(ArchitectureCandidate(f'dies{count}_mesh', spec, fixed))
    if not candidates:
        raise ValueError('at least one chiplet count candidate is required')
    return tuple(candidates)


def enumerate_gemini_architectures(reference=None, compute_counts=CHIPLET_COUNTS, *, include_shapes=True):
    """Legal rectangular meshes of identical 2x2-core dies and row-side IO.

    Shape is explicit because it changes link contention and IO/DRAM population.
    No arbitrary floorplan, torus, or routing freedom is silently introduced.
    """
    reference = reference or gemini_hardware()
    validate_gemini_chiplet(reference)
    fixed = tuple(n for n in reference.__dataclass_fields__ if n not in ('cluster_rows','cluster_cols'))
    candidates=[]
    for count in compute_counts:
        baseline=gemini_hardware(count)
        shapes = [(r,count//r) for r in range(1,count+1) if count%r==0] if include_shapes else [(baseline.cluster_rows,baseline.cluster_cols)]
        for rows,cols in shapes:
            spec=gemini_hardware(count,mesh_shape=(rows,cols))
            build_package(spec)
            candidates.append(ArchitectureCandidate(f'gemini_c{count}_{rows}x{cols}',spec,fixed))
    if not candidates: raise ValueError('at least one Gemini architecture candidate is required')
    return tuple(candidates)


def enumerate_legacy_architectures(reference=None, compute_counts=(4, 8, 16),
                                   noc_topologies=("multi_ring", "mesh")):
    """Partition one resource budget into legal four-compute I/O clusters.

    The default conserves 256 PEs, 64 mapping cores, 32MiB unified memory,
    distributed L1/L2 capacity, and 75GB/s aggregate DRAM bandwidth. It does
    not give extra dies free PHYs, controllers, or aggregate NoP bandwidth.
    Those change the physical hardware and its resource-derived cost.
    """
    reference = reference or HardwareSpec()
    totals = resource_totals(reference)
    conserved = tuple(key for key in totals if key not in {"compute_dies", "io_dies", "memory_dies", "total_chiplets", "total_dies"})
    result = []
    for count in compute_counts:
        if count < 4 or count % 4:
            raise ValueError("architecture candidates require complete four-compute clusters")
        clusters = count // 4
        if totals["pes"] % count or totals["mapping_cores"] % count:
            raise ValueError("PE/core resource budget cannot be divided into candidate dies")
        rows = max(divisor for divisor in range(1, math.isqrt(clusters) + 1) if clusters % divisor == 0)
        cols = clusters // rows
        per_die = {}
        for field in ("l2_weight_bytes", "l2_activation_bytes", "l2_output_bytes", "unified_buffer_bytes"):
            total_key = "unified_bytes" if field == "unified_buffer_bytes" else field
            if totals[total_key] % count:
                raise ValueError(f"resource {field} cannot be divided into candidate dies")
            per_die[field] = totals[total_key] // count
        if totals["dram_capacity_bytes"] % clusters:
            raise ValueError("DRAM capacity cannot be divided into candidate clusters")
        for topology in noc_topologies:
            cores = totals["mapping_cores"] // count
            spec = replace(reference, cluster_rows=rows, cluster_cols=cols, compute_per_cluster=4,
                           cores_per_die=cores, pe_count=totals["pes"] // count,
                           ring_count=cores, dram_bandwidth_Bps=totals["dram_bandwidth_Bps"] / clusters,
                           dram_capacity_bytes=totals["dram_capacity_bytes"] // clusters,
                           noc_topology=topology, **per_die)
            observed = resource_totals(spec)
            for key in conserved:
                if not math.isclose(observed[key], totals[key], rel_tol=1e-12, abs_tol=0):
                    raise ValueError(f"resource conservation failed: {key}")
            build_package(spec)  # Includes port/geometry/connectivity checks.
            result.append(ArchitectureCandidate(f"dies{count}_{topology}", spec, conserved))
    return tuple(result)
