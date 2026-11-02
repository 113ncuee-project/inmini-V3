# GUI04 v2 request and bounded search contract

Updated 2026-11-01 Asia/Taipei. This is implemented in the real frontend at
`simplified_rapidchiplet/gui/`, served by `hybrid_gui.py`; the Downloads HTML
is a design reference, not the deployed interface.

## Request versions

`normalize_gui_request(raw) -> (effective_engine_config, ui_provenance)` is a
pure function. Without `ui_schema_version`, it invokes the unchanged v1 numeric
validator. In particular, v1 defaults remain batch=1, budget=8, seed=7,
fusion=dp, fusion_depth=4, fusion_budget=6. Old CLI/report experiment runners
do not enter the Auto resolver. New algorithms have a new source identity;
historical checkpoints with different sources are rejected, never relabeled.

New UI submissions use:

```json
{
  "ui_schema_version": 2,
  "models": ["resnet18"],
  "preference": "balanced",
  "search_mode": "standard",
  "workload_mode": "single",
  "batch": 1,
  "seed": 7,
  "budget_mode": "auto",
  "fusion_mode": "auto",
  "microbatch_mode": "auto",
  "architecture_mode": "auto"
}
```

PPA limit/strict fields are merged without changing their values. `manual`
budget accepts an integer 1–512, uses that exact query ceiling, and still obeys
the selected profile's CPU time ceiling. Contradictory batch/mode, fake Auto
Batch, unknown fields and strings in numeric engine fields are rejected.

## Bounded profiles

| Profile | RL exact-query ceiling/model | CPU wall ceiling/model | Total seed-query quota/model | Executable architecture target | Per-evaluation timeout | Export reserve |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast | 12 | 90 s | 3 | 2 | 45 s | 12 s |
| standard r2 | 48 | 480 s | 8 | 3 | 400 s | 45 s |
| deep | 128 | 1200 s | 16 | 5 | 360 s | 90 s |

These are bounded engineering profiles, not promises that a deeper search
always finds better PPA. The experiment report distinguishes actual full-query
use, seed coverage, startup/export overhead and timeouts. Fast/standard are
calibrated on Toy, ResNet18-224 and MobileNetV2-224; the deep manual smoke does
not prove quality at the full 128-query ceiling. Per-model deadlines include
DAG preparation; process/module startup and final suite indexing add overhead,
shown in measured whole-case wall time. Multi-model jobs have the sum of their
per-model envelopes, not a claim of simultaneous inference execution.

The first calibration used a 270 s standard per-evaluation cap, which could
interrupt a cold MobileNet evaluation under host load. Resolver r2 raises it
to 400 s within the same 480 s envelope. Existing saved effective settings
remain unchanged. A real profile-change resume probe preserves an old 270 s
job while new requests resolve to 400 s, with zero new full queries on that
completed resume. Earlier calibration/error records remain separate.

Within each count, a MAC-throughput plus weight/DRAM-bandwidth proposal bound
orders rectangular shapes; hard physical silicon area can reject seed
templates. This proxy is never a final PPA. The initial scan continues across
different architectures and retains multiple completed executable seeds. The
remaining seed quota tests P, K and capacity-sized alternatives. An earlier
executable seed does not end architecture coverage by itself. Time/query
ceilings may prevent the coverage target; the actual coverage is reported.

Completed seed states enter the exact RL cache and feasible archive as paid
bootstrap evidence. They do not become fake new RL full queries. Fixed-horizon
episodes rotate through those independent starts, retaining learned policy
and the global archive. A median of measured evaluator costs predicts the
remaining query allocation and can end a run before another likely overrun.
Manual query ceilings are never replaced by that prediction.

A persistent isolated subprocess executes the same `HybridEvaluator`, actual
network, SRAM, service/calendar and energy model. Parent-side deadlines can
kill an in-progress evaluation. No partial metric response is used. Improved
completed states export their retained exact traces before entering the
durable verified archive. Later reporting does not need to replay those full
evaluations; replay count is explicitly zero, export operations/time are
counted separately. A timeout is unknown feasibility, not a physical rejection.

On Windows, the owned process tree is stopped because a venv python.exe can
be a redirector with a real Python child. Atomic writes use unique temporary
names and bounded retries for temporary sharing/access failures. The final
experiment directory is isolated from prior calibration folders.

## Fusion and partition proposals

The original no-cross-layer-fusion state remains available. Existing atomic
and composite candidates are retained. A new bounded interval DP in
`fusion_planner.py` compiles short closed windows, estimates local MAC/region
cost, and proposes explicit A10 group changes plus A1 tile/cache stacks as a
C6 transaction. This is a proposal optimizer: no local proxy is substituted
for whole-model reward, SRAM lifetime, NoC/D2D traffic or global PPA.

The local DP has compile-unit, transition, beam and time bounds. These are
heuristic proposal pruning limits. Initial depth cap is 4; positive local
proxy opportunities can expand it by 2 up to 8, subject to legal closed
windows. Deeper windows are actually proposed when available, not just shown
as a label. Each stack's selected depth/tile/cache comes from the archive.
Depth coverage, rejected transactions and pruning reasons are saved.

Both weight-shared spatial-output P (H×W) and activation-shared K directions
receive balanced candidate coverage. Neither receives a reward bonus. Batch
is fixed at 1, so B partition and microbatch remain 1. P partition is distinct
from PE-local weight-stationary behavior: all physical copies, broadcasts,
halo, L1 refills and memory service remain charged.

C10 local communication-aware partition DP, arbitrary floorplan/routing,
cross-chiplet C reduction, peak power and unsupported cache directions remain
disabled. The existing A11-to-A9 alias is unchanged.

## Persisted evidence and resume

- `requested_ui.json`: original v2 Auto intent.
- `ui_provenance.json`: resolver version, effective numeric bounds, capability limits.
- `config.json`: effective suite settings, model shapes, seed and template set.
- `model/context.json`: source/config/workload identity for resume rejection.
- `model/rl_effective_config.json`: original numeric RL phase limits; restored on resume.
- `model/architecture_seed_proxy.json`: actual seed ordering and hard area screen.
- `model/seed_states.json`: completed bootstrap states and individual seed attempts.
- `model/verified_archive.json`: durably exported, fully evaluated per-template archive.
- `model/joint_search.json`, `checkpoint.json`: actual policy, probabilities, edits,
  RNG, exact cache, archive and stop state.
- `model/fusion_proposal_coverage.json`: adaptive cap, local DP/depth coverage and rejections.
- `model/adaptive_allocations.json`: measured-cost allocation predictions.
- `model/accounting.json`: this-process seed/RL/export counters, cumulative RL
  exact queries, cumulative wall time, timeouts and stop reason.
- `model/oracle_runtime/accounting.json`: most recent process that issued
  requests. A completed resume with no new requests leaves this prior low-level
  log intact; current-process counters are in the model accounting file.

Resume reads saved effective configuration instead of resolving Auto again.
Source/workload/config mismatches reject. A completed resume reuses saved
physical archive evidence and makes zero new full queries in the acceptance
probe. No historical October 31 result is rewritten.

## Validation

`output/gui04_20261101/full_regression_delivery.log`: 246 tests / OK on delivery source E.
`release_acceptance/v1_verified.json`: actual final-source numerical v1 Toy replay matches raw PPA,
action-family sequence and query count; this is not a universal bitwise claim.
`release_acceptance/resume_verified.json`: actual final-source full-evaluator resume probe.
The first sandbox-only regression log retains its localhost socket failure;
the passing log was run with access to localhost API.

The source optimization omits derived diagnostics before decision hashing and
transaction copying. Decision hashes remain identical to the old serialization;
physical coefficients, precision and reward are unchanged. Equivalent per-core
microkernels share exact cache entries across system rectangle geometry;
per-core resource identities and all physical payload coordinates are retained.


## Delivery cohorts and results

Final physical source E is `9624c00278d2fd57d5ec0d2f861820abf2332df62120c24605c9dbda8bef3d1b`. Completed source-stable D results are retained with their original identity `75c7bcc521440e0e8f83a6ddf3d216c8934b50a3731ddb9cc103db433fab09b6`. Only auto_runtime response-file read-lock retry / scratch cleanup changed from D to E; no evaluator, reward or proposal formulas changed. A source mismatch still correctly rejects checkpoint resume. `source_cohorts.json` and both snapshots disclose this; results are never relabeled.

15 cases completed: 9 Auto searches and 6 controlled pairs. MobileNetV2 fast and standard exhausted deadlines without a completed seed, so no PPA is reported. Uniform ResNet P-only controls, including matched temporal K=64, fail existing GLB/residency constraints; their raw metrics are diagnostic, not legal competitors. Actual joint search retains mixed P/K or K-only mappings. All freely selected best archives have DF depth1; real depth2/3/6 proposals and the same-mapping fusion control are separate acceptance evidence.
