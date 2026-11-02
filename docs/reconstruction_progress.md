# Communication-aware 重構進度

使用者於 2026-10-03 授權直接繼續 Phase 2–10，不再逐階段等待確認。
既有 Phase 1 / 1.5 文件是歷史 checkpoint，不表示本次必須停在 1.5。
已連繫使用者指定的 GPT 原始對話作技術審查；其建議作為 review，不覆蓋使用者規格。

| Phase | 狀態 | 修改 / 公式 / assumptions | 已執行驗證 |
|---|---|---|---|
| 1 / 1.5 | 已完成 | audit + 三個 correctness repairs；FPS cleanup | 43 tests + official adapter / CLI smoke，見原報告 |
| 2 | 已完成 | default parallel actions 僅 K；刪 OC/IC/spatial efficiency 與多-chiplet效率扣減；scheduler 使用 actual routes/BW，刪 artificial hop_factor；legacy IC/spatial 僅 explicit historical calls | 原 43 tests 全通過 4.712s；2 個新增 default-action/global-rate tests 通過 |
| 3 | 已完成 | 新 tensor_metadata/model_parser，真正 TorchVision FX + ShapeProp；18 blocks，175 constituent ops；FP32 / EXTERNAL config；不修改人工 models.json | 6 個 phase2/3 tests 通過 6.842s，含 exact MAC/parameter counts、Add/shortcut、v1.5 stride |
| 4 | 已完成 | MappingPlan N_total / 每-block ordered active IDs；integer K ranges，per-channel MACs/weights | 9 phase2–4 tests 通過，含非整除 K / MAC / weight conservation |
| 5 | 已完成 | tensor_ownership / traffic_model，versioned resident slices、grouped/depthwise requirements、intra/cross traffic、Residual Add locality、last-use dedup / SRAM | 18 phase2–5 tests 通過 3.708s |
| 6 | 已完成 | physical_evaluator 共用 canonical Flow / 官方 NetworkContext；逐算子先通信後 compute，全局 serial；不再调用 legacy scheduler | 新 evaluator/search 10 tests 通過；真實 ResNet N=1/2/4/16 官方 injected bits 與 flows 完全一致 |
| 7 | 已完成 | network_diagnostics 對 directed links 含零 load 統計；hop-weighted bytes=sum link bytes，util basis=serial E2E；沒有 queue 模擬 | assignment 改 hops / latency、總 byte conservation、同 N_total fixed native power tests 通過 |
| 8 | 已完成 | assignment_generator reuse/compact/comm-aware ordered variants；first-op missing bytes×Manhattan hop boundary 下界，config topK=4 | bounded candidates / ordered permutation tests 通過；沒有 family score bonus |
| 9 | 已完成 | physical_dse Q-state 含 live slices/ordered history/actual prefix/profile/full identity；terminal LAP-only constraint-first reward；共享合法动作 toy exhaustive | 同 seed reproducible；17-design toy 與 394-design heavier toy；seed7/8/9 heavier toy 各64 unique，cost gap 0% |
| 10 | 已完成 | physical_report / physical_cli；CSV/JSON/HTML traces、config/assumptions/version/hash/seed；舊入口加 --legacy，demo切新模型；custom LAP weights | 最終74 tests全通過12.636s；ResNet balanced/latency各64 unique、area/power各16；multi-seed toy / ablation / custom / legacy CLI通過；所有final outputs source hashes一致 |

新依賴只安裝到 repository `.venv/`（ignored），版本 torch 2.7.0+cpu /
torchvision 0.22.0+cpu；既有 runtime packages 未升級。網路下載從 PyTorch 官方
CPU wheel index，驗證輸入 batch1 `[1,3,224,224]`、1000 classes、weights=None，
沒有下載 pretrained weights。這是 shape/MAC graph extraction，並非 accuracy evaluation。

每次 checkpoint 是修改後先測試再進入後續階段；以上依使用者修正版順序，
Phase3是graph extraction，Phase4是integer physical mapping，Phase5是operator ownership。
Phase6–9共同測試檔为 test_physical_search.py，所有檢查共享同一官方 adapter。
更完整 formulas / assumptions / CLI 見 simplified_rapidchiplet/COMMUNICATION_AWARE_DSE.md。

GPT 第一次審查已採用 grouped/depthwise、logical version、last-consumer residency、
disjoint serial latency、ordered state/cache、same legal action space 的 gates。
第二次詳細結果分享被 auto-review 拒絕，已請使用者明確同意分享摘要；
沒有重試或繞過拒絕，本地工作正常繼續。

最終報告：docs/communication_aware_reconstruction.md；machine-readable evidence：
docs/communication_aware_validation.json。實測 balanced N_total=2 / 213.356124ms /
156.119659mm² / 42W；latency preference N_total=9 / 49.808595ms / 712.525909mm² /
196.5W。沒有把 RL 與 baseline 相同的結果說成改善，也沒有將 toy optimum 泛化。

追加 correctness gates：多producer同consumer/kind只一個service event；
Torch built-in target 使用 qualified callable name，model fingerprint跨程序相同。
本地 file:// browser protocol 被阻止，沒有繞過；HTML做結構 / artifacts檢查，
沒有宣稱 screenshot或visual browser QA完成。
