# Gemini 2×2 Core / RL DSE progress

Date: 2026-10-31 (Asia/Taipei). User authorizes full implementation on existing V2.

## Delivery status: complete within declared supported backend

The production CLI and GUI now execute Gemini fixed 2×2-core templates → source-traced Tangram-style DP/beam seed → transactional joint architecture/mapping actor-critic → strict best-feasible archive and visual results. A11 imports as A9; C1–C9 use explicit edits. Original Tangram/BSD/ALLO, C10, vertical-only cache, arbitrary routing/floorplan, peak power and automatic spill remain explicitly unsupported/disabled, as recorded in the capability matrix.

Verified: 231 complete regression tests passed; 18 source-stable, equal-query ablations passed independent accounting/reward/PPA audit; true ResNet-18 224×224/batch1 Tangram+RL smoke passed. Browser GUI positive and impossible-limit cases passed with no JS errors, 4 DAG nodes / 4 edges including both residual inputs, and explicit core routes. Final evidence: `output/rl_dse_20261031/validation.json`; documentation: `docs/rl_dse_runbook.md`, `rl_dse_validation.md`, `rl_dse_action_contract.md`, `gemini_hardware_contract.md`.

GUI server remains available at http://127.0.0.1:8766/ using `output/rl_dse_20261031/gui_final`. Final feasible GUI job: `ceb4fde92781`; impossible-limit test: `ed5bace87143`. Source files/historical experiments/user changes are preserved. The hourly continuation automation is stopped after delivery; no remaining implementation is queued.

## Completed work allocation

- Preserve all existing uncommitted V2 work and historical experiment folders.
- Hardware agent: new Gemini-like fixed 2×2-core compute chiplet, explicit core mesh / D2D lanes / side IO / DRAM, evaluator diagnostics and tests. Existing fixed_mesh profile stays available for replay.
- RL agent: new `hybrid/rl_schema.py`, `rl_actions.py`, `rl_search.py`, transactional A1–A10, A11 alias A9, candidate policy learning, archive/checkpoint and tests.
- Tangram agent: `hybrid/tangram_seed.py`, source-traced DP/beam adapter and DAG tests. Must state differences from original Tangram.
- Root: production CLI/GUI integration, PPA power/area/latency preferences, result visuals, integration/ablation verification and documentation.

## Contracts

- New architecture factory: `gemini_hardware` / `enumerate_gemini_architectures` (hardware agent to finalize).
- RL public entry: `run_joint_search(workload, initial_state, architecture_candidates, evaluator_factory, *, objective, config, checkpoint_path, resume, evaluator_identity)`.
- `DesignState(architecture_candidate_id, mapping, model_hash, hardware_template_version='gemini-2x2-v1')`.
- Tangram entry: `build_tangram_seed(workload, compute_ids, memory_ids, hardware, evaluator=..., score_fn=...)`; result `.plan`, `.to_dict()`.
- New production CLI planned at `simplified_rapidchiplet/rl_dse.py`; existing default CLI/GUI will route to it. Explicit legacy replay retained.
- Final archive must satisfy strict PPA constraints. Executable over-limit states may be explored. Report closest candidate separately.

## Verification record

Completed new acceptance tests and full existing regressions, toy end-to-end joint search, residual real model smoke, deterministic checkpoint resume, multi-seed equal-budget ablations, browser GUI and resulting layout inspection. See the delivery status and linked evidence above. Toy results do not show RL superiority; no global optimality claim is made. Presentation-only changes after ablations are explicitly audited separately from the unchanged physical/RL sources.

## Resume

Hourly heartbeat `gemini-2-2-core-rl-dse` was used to continue after quota reset and is stopped following completed delivery. Inspect this document and actual processes before any future run. Source spec is `C:/Users/user/Downloads/RL_Chiplet_DSE_Codex_Spec.md`.
