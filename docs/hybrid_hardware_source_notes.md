> 更新：使用者最新的16nm成本基準與strict/soft限制修正，請先看 [hybrid_cost16_sources.md](hybrid_cost16_sources.md) 與 [hybrid_cost16_progress.md](hybrid_cost16_progress.md)。本檔下方數值屬歷史版本；舊混合製程／MAC乘8推導已撤回，不可當成新成本。

# Hybrid INDM / Gemini hardware source notes

Date: 2026-10-05. These notes separate published values from the executable model's assumptions. They accompany a new, independent hybrid implementation; they do not claim a reproduction of either paper's fabricated hardware.

## Hierarchical package and compute die

INDM, printed pp. 1109-1111, Fig. 3 and Sections III-A/B/C: each cluster connects at most four compute dies and one DRAM to an actual I/O die. I/O dies contain a crossbar, DDR PHY/controller and GRS interfaces. I/O dies form a mesh with deterministic XY routing. Compute and DRAM endpoints are leaves; I/O dies relay. On-die PEs and WL2/AL2/OL2 use unidirectional rings; packets cannot jump between rings. This is separate from the package mesh.

For a 4x4 cluster grid, an interior I/O die needs four compute ports, four mesh ports and a DRAM interface. The paper's prose mentions seven GRS TX/RX pairs, but this does not cover arbitrary grid interior degrees. The implementation allocates and charges actual ports from the graph, records the required radix, and never silently shares a PHY. DDR is represented as its own controller service and a package endpoint connection; it is not an identical GRS interface.

INDM Table II: vector size=16, lanes=16; PEs/die in {4,8,16,32,64,128,256}; compute dies in {1,2,4,8,16,32,64}; L1base in {5,10,20,40,80,160} KiB; W/A/O ratios [8,2,1], [2,8,1], [5,5,1], [9,1.5,0.5], [1.5,9,0.5]; L2/L1 ratios {1,2,4}.

INDM Table V, area-constrained cloud design: 16 compute dies, 16 PEs/die, L1base=8 KiB, L1 W/A/O ratio=8/2/1, L2/L1 ratio=1, reported core area=2.83 mm². Therefore the executable reference has per-PE WL1/AL1/OL1=64/16/8 KiB and shared per-die WL2/AL2/OL2=64/16/8 KiB (Eq. 2 does not multiply these capacities by PE count). This does not mean the hybrid die will also occupy 2.83 mm².

INDM Table IV and p. 1115: INT8 weights/activations, 24-bit partial sums, 1 GHz; cloud=16 dies, 65536 MACs, nominal 128 TOPS, DRAM bandwidth 600 Gb/s, NoP 100 Gb/s, NoC 68 Gb/s. The model reports decimal physical bandwidths and TOPS, avoiding the source implementation's implicit binary arithmetic. Compute, NoP, NoC and DRAM rates have explicit units. Frequency and architecture resources come from the same HardwareSpec used to generate native inputs.

## Gemini implementation evidence

Local source root: `C:/Users/user/Downloads/GEMINI-HPCA2024-master/GEMINI-HPCA2024-master`.

- `src/core.cpp:10-15` defines MACs/core as bus.aLen * bus.oLen * laneNum * vecSize, and distinct buffers with read/write capacities, costs and bandwidth.
- `src/main.cpp:855-889` exposes core microarchitecture, core grid, batch, chiplet x/y cuts, NoP/NoC/DRAM bandwidth, vector dimension and unified-buffer capacity. Chiplet cuts must divide the core grid.
- `src/main.cpp:1012-1021,1215-1224` instantiates AL1/WL1/OL1, OL2 and a unified UL3 buffer; AL2/WL2 capacities are set to zero in this version. This differs from simply copying all INDM buffers.
- `src/main.cpp:1106-1148` derives SRAM, MAC, NoC, D2D, DDR/PCIe and total die areas from resource counts and densities, then applies layout/control/DFT assumptions. It never treats extra MACs or buffer capacity as free.
- `src/noc.cpp:78-128` accounts for DRAM reads/writeback and unicast/multicast according to data-layout overlap; `betweenLayout` evaluates intersection volumes. Logical tensor demand must therefore remain separate from the actual routed traffic plan.

The hybrid adds a shared unified activation/residency buffer to INDM's W/A/O hierarchy to support Gemini-style layer pipelines and residual lifetimes. That additional SRAM is an explicit fusion extension and is charged in silicon/leakage costs. Capacity does not imply bandwidth: all buffer and I/O service rates are explicit.

## Energy and area calibration status

INDM Table III provides DRAM=8.75, SRAM=0.81 and GRS=1.17 pJ/bit. The table also lists 8-bit MAC=0.024 under the same energy-per-bit heading; the paper does not resolve this dimensional ambiguity. The executable model must state its MAC convention explicitly rather than presenting an ambiguous value as calibrated pJ/MAC. On-die hop, crossbar, leakage and controller coefficients are exploratory parameters unless separately validated.

INDM p. 1111 provides a GRS macro area=387590 µm², interdie router=42000 µm², RISC-V CPU=109000 µm²; DDR4 PHY/controller is described as over 10 mm² at 16 nm (p. 1109). These anchors are useful, but neither the 2.83 mm² compute area nor the I/O area can be imposed as a constant while PE/SRAM/ports change. SRAM density and INT8 MAC density copied from Gemini's source belong to its stated process and layout assumptions, not automatically INDM's node. Default coefficients are source-inspired, uncalibrated estimates and are exported with that status.

Dynamic energy is counted once from operations/buffer accesses/physical link bits. Native `power` values represent the resource-dependent idle/leakage component in this adapter, not workload-dependent TDP. Average inference power is idle plus dynamic energy divided by elapsed time. NoP dynamic traffic is charged per physical hop, and DDR energy is charged at the controller without duplicating it as GRS energy.

## RapidChiplet backend contract

Local source: `C:/Users/user/Downloads/rapidchiplet-main (2)/rapidchiplet-main`.

- `rapidchiplet.py:79-108`: bandwidth is bump-derived, undirected links are expanded into two directed capacities, and the per-direction value is half the bump wire budget. This is a physical ceiling, not a GRS/DDR signaling-rate guarantee. The hybrid exposes native bump ceilings and caps usable capacity by the explicit PHY/DDR rate.
- `rapidchiplet.py:110-180`: silicon area is derived from chiplet dimensions and footprint from placement bounds; native power sums supplied die powers. The installed version computes link power locally but omits it from its returned total; the hybrid uses its explicitly defined idle-link budget instead of guessing that the native total includes it.
- `rapidchiplet.py:292-382`: the native path-latency formula uses PHY latency, packaging wire latency, relay-chiplet internal latency and end-node latency. The hybrid retains that path calculation and supplies a legal deterministic cluster routing table.
- Local validators print errors rather than raising; placement validation has a known incomplete AABB test. The hybrid therefore rejects overlap, duplicate port use, invalid degree/capacity and illegal routing before calling native metrics.

RapidChiplet predicts package network properties. PE buffers, DRAM controller service, tile/pipeline resource contention and multi-ring multicast are separate models combined by one evaluator. Its analytical path calculation and a passed software test suite do not establish cycle-accurate silicon prediction.

## Executable public API

The new modules live in `simplified_rapidchiplet/simple_rapidchiplet/hybrid/`:

```python
from simple_rapidchiplet.hybrid.hardware import HardwareSpec, build_package
from simple_rapidchiplet.hybrid.rapid_backend import evaluate_package

spec = HardwareSpec()
package = build_package(spec)
network = evaluate_package(spec, package)
network.route("compute:0/core:0", "compute:15/core:3")
network.latency_ns("compute:0", "compute:15")
```

`HardwareSpec` is frozen and defines independent compute/NoC/NoP clocks, physical signaling rates, buffer capacities/service rates, energy per MAC or bit and component area/leakage coefficients. `PackageGraph` uses string physical endpoints (`compute:0`, `io:0`, `memory:0`). Its 64 `mapping_core_ids` (`compute:0/core:0`, etc.) divide the 16 compute dies' PE resources into four cores per die. This is a Gemini-style scheduling abstraction, not 64 physical chiplets. WL2/AL2/OL2 and unified buffer remain shared by all four cores of a die. The evaluator must share capacity and bandwidth or explicitly partition conservative quotas.

`NativeNetworkContext` provides `routes`, `link_bandwidth_Bps`, `path_latency_ns`, `native_link_bandwidth_Bps`, `link_length_mm`, `link_energy_pj_per_bit`, `area_breakdown`, `node_idle_power_w`, `idle_power_w`, native summaries and provenance. Default evaluation computes every physical-node pair. `route`/`latency_ns` canonicalize scheduling core IDs to physical dies. Same-die paths have zero NoP latency; the separate on-die model accounts for those transfers.

The default profile contains 16 compute dies, four I/O dies, four memory dies and 24 physical links. It provides 65536 INT8 MACs, i.e. **131.072 decimal TOPS** at 1 GHz (INDM's table labels this approximately 128 TOPS). Each compute die has 4096 MAC/cycle, divided into four cores at 1024 MAC/cycle each. All buffer, PHY and controller costs are charged in native dimensions and idle power. It is not a 2.83 mm² die reproduction: the extra unified SRAM, mixed-source area coefficients and modeled network resources produce a larger die.

Meaningful tests in `tests/test_hybrid_hardware.py` verify added PE/SRAM/ring costs, nine-port interior I/O allocation, overlap and port-reuse rejection, mismatched HardwareSpec/package rejection, excessive bump allocation rejection, typed XY/DRAM routes, actual native silicon area, explicit GRS/DDR bandwidth ceilings and native path-clock conversion. They passed against the installed native engine on 2026-10-05. The DDR connection currently uses the generic native PHY latency placeholder as well as separate controller service; it is not a calibrated DDR timing model.

## Capacity-backed internal microkernels (2026-10-06)

`ondie.core_service` partitions each mapping core's output into nonoverlapping PE regions, then bounded B/K/H/W output microtiles and C chunks. Footprint fitting checks **AL1, WL1, OL1, AL2, WL2 and OL2 separately**; an oversized activation bank cannot borrow unused weight/unified capacity. PEs accumulate C locally. Each microtile's INT24 accumulators fit OL1 and stay resident until all C chunks finish, so there is no uncharged partial-sum spill; the evidence reports zero spills together with the capacity proof.

Activation receptive fields are derived using the same stride/padding/dilation/group rules as the compiler. Each phase atomizes overlapping PE requirements and routes the multicast packet over the union of real directed edges. Both mesh and multi-ring receive the same logical requirements and implement multicast; there is no predetermined mesh replication penalty. Multi-ring injection is duplicated only when destinations really reside on separate rings. Inter-ring packets cannot bypass L2.

Each AL/WL bank has its own byte-bounded, whole-region-containment LRU cache. Hits are credited only when the requested region is actually resident. A miss produces L1 refill traffic and, on a shared L2 miss, a reread of the **full received macroregion's unified-buffer backing**. Root evaluator retention holds that backing until the work unit finishes. No additional DRAM read is invented for internal misses, and no free SRAM cache is presumed: UB reads, L2 reads/writes, L1 reads/writes, directed-link bits, integer vector tails and final output bytes are counted. Whole-region LRU is conservative about partial halo reuse; it is not an optimal dataflow solver.

Detailed evidence includes microtile dimensions, C chunks, PE/macro MAC cycles, independent bank capacities and peaks, UB/L2/L1 refill bytes, physical directed link loads, injected/delivered/hop bytes and partial-sum policy. Packet examples are bounded to 128 records per direction while aggregate counts and loads stay complete. A 4096-entry immutable-input LRU service cache accelerates RL reevaluation of unchanged units; the underlying physical formulas do not change.

For batch-eight DSE, the cache normalizes schedule IDs, batch origin and physical die while preserving physical core slot, layer/precision, K/H/W coordinates, weight K/C/R/S coordinates, all bytes/MAC counts and HardwareSpec. Identical microbatches therefore reuse physical microkernel calculations rather than evicting one another from the bounded cache. Returned evidence explicitly marks activation/output B as **unit-relative**, reports the real `batch_origin`, `actual_output_bounds` and `physical_die`, and restores real die ring-resource IDs. Tests compare every numerical cost/traffic field against the uncached physical calculation across two microbatches and dies, and ensure changed core slots or energy coefficients miss the cache.

L1 service uses the **maximum independent PE port load**, including each PE's actual weight reads, activation broadcasts, INT24 accumulator read/write, refill writes and output reads. It does not divide aggregate accesses by all PEs. The hand-derived five-output-position/four-PE test checks the two-position PE against the 1.25-position average: it produces a 1.6-times larger L1 bound, and can be memory-bound even when aggregate compute is fast.

The internal streaming cost is projected into macro read/compute/write service for scalable DSE, with no fine-grained internal streaming-overlap credit. This is an explicit analytical approximation rather than literal preloading of an entire macroregion into tiny L1. It is not an RTL/cycle/VC simulator. On a batch-one ResNet-50 initial plan (1706 work units), sampled stem, large layer3 projection and FC units required 16-32 internal channel rounds and 0.012-0.028 seconds per uncached unit on the current machine. Future studies should calibrate the macro resource overlap against a trace-based simulator.
