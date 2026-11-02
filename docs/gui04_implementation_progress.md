# GUI04 2026-11-01 implementation record

User request: implement GUI04 request and real Auto search, then experiment with
honest results. Weight-shared / P-parallel advantage for ResNet is a hypothesis,
not a cost-model coefficient or reward bonus.

Historical results are protected by output/gui04_20261101/historical_result_sha256.json.
Pre-change source is copied into output/gui04_20261101/baseline_source.

Work: versioned pure request normalization; real frontend; cancellable isolated
full evaluator and archive persistence; multi-architecture seed coverage;
measured-cost query allocation; bounded explicit local fusion DP proposals;
v1 defaults remain on original route; tests and new independent experiment batch.

New source identity is required. Do not rerun or overwrite the October 31 runner
or report builder in place. New artifacts belong in output/gui04_20261101.

## Current checkpoint

- v2 normalization, real section 04 UI, isolated deadlines, multi-template seed,
  explicit bounded fusion DP hook, seed/RL/archive accounting implemented.
- 243 tests pass in full_regression_post_performance.log (localhost allowed).
- Real v1 Toy replay matches physical PPA, action-family sequence and query count.
- Real v2 completed resume matches saved RL limits and archive PPA, 0 new queries.
- Derived-report copy/hash overhead fixed, exact decision hashes preserved.
- Source revision before performance fix reconstructed exactly at
  calibration_before_performance_source (id ffd5e77b5cb701655430da3f8d2eb376640f63161030b0b9d0553c807149e19f).
- Current experiments run in exec session 48481, two workers. Do not edit engine
  files while they run; every case records before/after source identity.
- Current formal Toy fast 11.75 s, Toy standard 114.23 s, ResNet18 fast 82.66 s,
  ResNet18 standard 450.12 s. Mobile fast ended with no completed seed under cap;
  Mobile standard has completed C1 seed (~250 s) and is trying C2. Other queued
  cases: Toy deep manual12, R18 low_power/low_latency manual16, R18/R34 P/K fixed
  controls, Toy DF/noDF control. Exact PPA must be read from artifacts, not notes.
- Final GUI server exec session42610 at http://127.0.0.1:8773, output gui_jobs_final.
  Browser cua handle gui04Live tab5; actual Auto fast Toy job3dac86505654 started.
  UI screenshots gui04_panel_final.png / gui04_default_final.png. Need final
  screenshot after CSS readability change and completion. CUA fs binding gui04Fs.
- Old servers8771/8772 and first calibration21187 were intentionally interrupted;
  old cases archived under superseded on rerun, not treated as final results.

## Pending important validation

Stress the adaptive local DP on a 6-layer closed chain. Current 36-transition
budget may be exhausted on prefix intervals before reaching a >3-layer window.
If reproduced, reserve baseline/deep full-window transitions (a real interval
edge 0->N), rather than merely increasing a displayed depth cap. Wait for the
current experiment batch to finish before changing engine source. Preserve
revision B evidence; rerun final standard Toy/R18/Mobile smoke after any such
fix, with the source revision made explicit. Do not claim depth6/8 works until
an actual legal deeper candidate test passes.

Need finish collect_gui04_results.py (can reuse deployment() helper from prior
collector without calling its main, to avoid modifying Oct31 files), acceptance
matrix, new report PDF/MD + offline index and evidence bundle, final historical
manifest check578files, actual P-vs-K results and WL1/AL1/DRAM/NoC ledgers.
Report numbers must come from real completed cases, no expected winner.

## Final source revision C (after deep-window repair)

The six-layer starvation was reproduced (0 complete proposals). Fixed by
reserving singleton baseline nodes and some real full-window 0->N DP edges
before prefix intervals consume the compile budget, canonicalizing clipped
sink tiles, and preserving cached edges after the budget/time gate. The new
13-test GUI04 contract suite passes, including an actual legal depth6 C6
transaction evaluated by HybridEvaluator with exact MAC conservation.

Final full regression: exec session42806 -> full_regression_final.log (expected244).
Final full experiment batch restarted all12 cases, session49543, source frozen.
Final GUI server: exec session27774, http://127.0.0.1:8774,
output gui_jobs_release. Earlier servers8772/8773 were stopped.
Revision B source snapshot is saved byte-for-byte in revision_B_source.
Previous completed/provisional cases move to superseded; do not mix with final.

Pending: final GUI screenshot/job through8774, final tests/cases completion;
collect_gui04_results.py already exists (imports old collector's pure deployment
helper only, does NOT call old main), but has hardcoded243 test label to update.
Need PDF/MD/offline index/bundle, actual controls findings, and historical hash
check. For a NEW PDF authoring operation, PDF skill marker must run once just
before first author command; not run yet in this turn. Prior turn marker was for
October31 report only. PDF builder should not overwrite old49-page report.

Watch for old timed-out cases: Mobile fast had no completed seed under45/90s;
Mobile standard revisionB completed C1 seed .9697ms but zero RL queries. Label
as fully evaluated seed best-so-far, NOT learned RL improvement. Final revisionC
may differ; use actual artifacts. ResNet standard revisionB stillselectedC1
1.74085ms despite3architecture seeds and27RLqueries. Do not force P-parallel.


## Final delivery 2026-11-01 (supersedes earlier provisional status)

Source D completed results retained intact; source E adds bounded response read-lock retry and safe scratch cleanup. Failed D runs are preserved under release_r2/superseded, then rerun on E. Final matrix is 15 cases / 9 Auto / 12 control variants. All case status files are complete and source-stable. 246 full regression tests pass in full_regression_delivery.log (141.055s); actual final-source legacy Toy numerical replay and completed v2 resume pass. 578 protected historical files remain SHA256-identical.

ResNet18 balanced: C1, 1.740850354888786 ms, 6.921301769091666 W, 77.7719968 mm2, Conv P/K/mixed=6/12/2. Low-power: C1, 2.103961519856857 ms, 6.177640389020833 W, all20 Conv K-only. Low-latency: C2 2x1, 0.9786754890059057 ms, 12.53500601134329 W, 155.5439936 mm2, Conv P/K/mixed=2/8/10. None selected cross-layer DF. MobileNet fast/standard had no completed seed and no PPA. Uniform P-only controls fail GLB/residency, even matched tileK64; no legal P/K winner is inferred.

Delivery GUI: http://127.0.0.1:8775, output gui_delivery, actual job ef8f26a003a7 (E). Form submission, completed result, analytic PPA/layout and no console errors verified; final screenshots saved. Current source snapshots, diff, contract, actual results, full flows/units/shards and report are packaged by tools/package_gui04_report.py. Original 8766 GUI and October31 report remain untouched.
