> **2026-11-02 最新交付：本機 RL 診斷工具。** 使用者最新授權只實作工具並跑小型驗收，P1～P6 由使用者自行啟動；不得恢復 PAUSED 排程或自行啟動正式長跑。舊 formal_v4 已 failed，保留全部來源／資料，不自動重啟。詳見 docs/LOCAL_RL_EXPERIMENTS_README.md 與 docs/LOCAL_RL_TOOLS_VALIDATION.md。132 項測試通過；Toy 受控停止／續跑與帳本、唯讀分析、ZIP 驗證通過。以下舊時序紀錄保留，不代表目前仍在背景執行。

> **2026-11-03 授權更新：** 使用者已要求實作更有效的 RL 並驗證改善，本輪代表實驗正在執行。見 `docs/inmin_v04_progress.md`；新本機入口是 `run_inmin_v04_overnight.ps1`。上方「只跑小型驗收」是上一輪的歷史授權，本次已被新請求取代；每小時自動續作排程仍暫停。

# INMIN v0.3 工作紀錄

更新：2026-11-02 16:10 Asia/Taipei。這是使用者最新 Word 問題清單與 nn_dataflow 附件所要求的新一輪修改，尚待最終驗收及正式比較。

## 最新授權

Compute開放1～16所有整數，保留旋轉後的50種矩形。每個布局依N_IO=2R重新付IO/DRAM/NoP/面積/功耗；A9可單步跳任一合法架構。Actor要看目標layer的具體瓶頸、memory pressure要驅動C7/C8、加入有真實成本的獨立dataflow動作。改進seed篩選、延長seed與oracle時間，保留完整RL觀察→候選→選擇→交易→PPA→更新循環。報告仍只用文字數字，不產圖，不用重置券或付費API。

Word所述48queries/480秒是較舊版本；v0.2後來已改128/1800，仍不足以讓大模型充分學習。v0.3目前standard為seed最多7200秒+獨立search最多7200秒、每oracle1800秒；common seed實際成本仍向每個方法計費，沒有免費初始化。深度模式各14400秒/單oracle3600秒。均是上限，不宣稱全域搜尋已窮盡。

原分享連結 https://chatgpt.com/share/6ae8418b-5d8c-83e8-a458-fa1c2546a1ba 嘗試讀取失敗（Cache miss）；沒有假裝讀到。Word完整文字已由user提供，不需要再操控Word。

## 參考來源與版本

- nn_dataflow-master.zip SHA256 `8fae65512bb780894d8cba5a0f9c6c66f40a9845178e468d435738bde028a57b`，110檔，已安全解壓至third_party/nn_dataflow_reference，保留BSD-3-Clause LICENSE及來源說明。
- 實際讀取README.rst、nn_dataflow/core/nn_dataflow.py、inter_layer_pipeline.py。參考逐層schedule cache、segment枚舉、按ending layer保留top-N/beam；未把上游Eyeriss row-stationary物理成本當INMIN成本，也未宣稱執行原Tangram完整DSE。
- v0.2正式來源output/inmin_v02_20261101/formal_v8/source_snapshot及所有舊結果不可改。新profile `chiplet_single_pe_array_v0_3` / DesignState schema3 / GUI schema4，各有獨立identity；舊schema1/2與GUI1/2/3保留。

## 已實作（live程式）

- SingleArrayHardwareV3與50架構enumerator；繼承相同16PE/L1/L2/IO實體成本，舊SingleArrayHardware仍只接受1/2/4/8/16。硬體roundtrip及50個A9交易測試通過。
- 新single_array_seed_v3.py：容量篩選的segment beam，真實可容納PE fragment篩選、group output保守上界、逐layer/dataflow/partition快取。候選涵蓋Spatial/Temporal、K/P、三種dataflow；完整INMIN oracle才決定可行及seed排名。不是global optimum。
- schema3候選feature 283維（state仍24維）：加入每個候選目標layer的criticality、MAC/L1/VPU服務、queue/resource waits、memory pressure、slack、work fraction等及與動作家族交互項；global相同而target不同時Actor可以區分。
- target_bottleneck.py：壓力≥90%的實際共享pool針對相交stack提出C7縮tile+清cache；低壓<65%且有recompute/overlap提出C8增tile/cache。共享pool歸因仍partial，不能宣稱唯一causal layer。
- A12獨立切換output_stationary/weight_reuse/activation_reuse。沿用已有有價kernel流量模型；W/A重讀及INT24 partial-sum RW重新核算，MAC守恆；不是免費改label。僅schema3可用。
- 每步trace新增24維observation、283維selected features、12維target evidence、完整candidate probabilities及normalized entropy，連同已有ordered edits/PPA/reward/update可核對是否近似均勻抽樣。
- CLI預設v03，seed/search分開保留時間；舊直接caller未指定engine仍維持v02。GUI schema4預設7200+7200，50架構；JS與文字報告路徑已接新profile。
- 精確PPA加速：通訊Cartesian cells使用axis coverage索引、依賴owner精確索引、同PE需求索引；NoC/NoP route cache；不可變TensorRegion intersection bounded cache。新profile的persist只存compact evidence，避免幾百MB JSON超過15秒；full oracle依舊完整跑。尚未校準silicon，不宣稱硬體準確度提升。

## 已跑證據

- acceptance_stage1：103個舊/新v0.2回歸通過（26.558秒unittest）；期間仍有編輯，不當最終鎖版驗收。
- acceptance_stage2：111 tests通過（66.108秒）；涵蓋50布局/IO成本、50單步A9、A12真實traffic差、target severity差、C7/C8、可行非baseline seed、實際RL更新、GUI4/GUI3共存。最終source-stable full acceptance仍待跑。
- frozen v0.2 vs live優化的R18 baseline profiling：62.411→46.607秒evaluate（cProfile環境、有其他測試並行，非嚴格吞吐benchmark）；latency/energy/power/area/MAC/DRAM/NoC/NoP/units全相同。見tmp/inmin_v03/baseline*、optimized*。後來又加intersection cache，尚待新的穩定benchmark。
- R18新seed development probe：DP提案4個含baseline，0.656秒完成、timed_out=false。baseline可行22.66107075ms/26.12308559mJ；3個DP proposal均可行20.55766574ms/17.39651436mJ。不能把seed收益算成RL收益。結果output/inmin_v03_20261102/resnet18_seed_probe.json；session75907已輸出4個結果。
- 新CLI Toy E2E：output/inmin_v03_20261102/toy_e2e_stage1已完成，source_stable=true，66.140秒；四方法各12完整PPA，trace保存283維feature。此為流程測試，不作大模型效益結論。

## 待完成

1. 補schema3 feature盲測開關供同candidate-generator消融，最終穩定驗收、resume/超時/worker/GUI4實際E2E檢查；驗證新compact export完整PPA不重算。
2. 更新技術文件及effectiveness報告、凍結v03來源，從Toy再跑代表性R18 fair arms，確保足夠觀察/動作/更新；必要時接R50/MobileNet。不可混用v02 PPA或改snapshot。
3. 保存完整有效設定、seed/learning分帳、來源hash、coverage/negative results。狀態正常時heartbeat靜默；額度重置後接續，未完成不關排程。
4. 舊v02三模型已完成：bottleneck composite沒有優於最佳對照；不能用其負面結果當新v03結論。v02固定mapping pairs現已產生，待最後整併；新工作優先。

GitHub原發布版已成功推送113ncuee-project/inmini-V3 main commit19402044；本輪v03改動尚未同步上傳。不要動output/github_publish的舊提交或原root git歷史。

## 最終程式驗收與新長跑（2026-11-02 16:25）

- 使用者已明確選擇「維持排程暫停」。automation inmin-v0-2-rl 的prompt/name已更新v0.3，status仍PAUSED；不可自行恢復。一般背景批次實驗仍按授權運行。
- 最新穩定驗收：acceptance_final_v4，112 tests/0 failures/0 errors/source_stable=true，48.406秒（unittest47.508秒）。新測例包括GUI4完成後resume不增加oracle、推薦仍存在；早期snapshot_v2只在報告重建遇到search_ceiling未初始化，已修正，保留DEVELOPMENT_ONLY。
- 新seed DP每prefix保存最後4個prefix的beam checkpoint；source/config/workload/hardware identity檢查；baseline provenance記prefix_completed/DP_complete，超時半成品不冒充整個model seed。重啟可繼續。
- 已加 --bottleneck-features off 控制Actor/Critic的動態瓶頸特徵，candidate generator仍相同；預設on。此消融開關已測feature遮蔽，尚未完成正式因果比較。
- 正式最新版只使用 formal_v3/source_snapshot：132檔，identity 629a7064dca2a490889e478bb026cc732a0c9106c298533df92463833cafc73c。前面的formal_v1/v2是開發煙霧/負面歷史，不要啟動其長跑。
- 背景batch session96504，workflow owner PID22640；formal_v3/workflow_control/workflow_status.json + run.lock 是主狀態。先做R18 preflight（12總PPA、4seed、seed/search各1200秒、oracle600秒、僅bottleneck RL），成功後自動進3模型公平比較、各模型Fusion Off、固定mapping DF pairs、最後audit。這是一次有限批次，不是恢復heartbeat排程。
- 正式comparison：各方法128完整PPA上限、共同seed最多16、seed7200秒+獨立search7200秒、單oracle1800秒。Toy64PPA/search600/seed120秒。最壞需要一天以上，不承諾時間內窮舉或必定改善；所有budget/partial/timeout留證。
- 不要重複啟動。中斷後同命令執行 source_snapshot/scripts/run_v03_research_workflow.py --snapshot (此snapshot絕對路徑) --out (formal_v3絕對路徑)，會按phase及CLI checkpoint接續。
- code已具備真正的target observation/候選選擇/交易/完整PPA/reward/policy更新；尚不宣稱新版policy優於對照，需看formal_v3新結果。舊v02結論不可挪用。

## 2026-11-02 16:40 最新可接續版本：formal_v4

實際R18 preflight的target transfer-wait=sum/latency在多個layer飽和8，已保留formal_v3全部資料並停止該次自啟動程序樹22640（已確認taskkill成功）。未覆寫物理PPA，也不把該次policy結果當正式結論。修正為max transfer/job wait / latency，MAC/L1忙碌依目標PE數、VPU依die數正規化；A9觀察整個模型的target evidence。受控0.8/0.2 queue及並行service正規化測試通過。

最終驗收acceptance_final_v6：113 tests、0 failures/errors、source_stable=true、76.281秒。GUI4完成後resume不重算PPA且推薦存在。先前111/112項為較早階段，不能用其來源代替本版。

最新凍結formal_v4/source_snapshot：132檔，identity b8ded693c224b29ef3dd3c19e0a01410d76af37b8f79eccfe21055d76420dd28。workflow session41240，owner PID33136；主狀態formal_v4/workflow_control/workflow_status.json與OS lock。preflight→3模型公平比較/Fusion Off→fixed-mapping pairs→audit。正常運作勿重複啟動；中斷時同參數resume此版本。formal_v1/v2/v3皆保留開發/負面歷史，不再啟動。

使用者要求維持heartbeat排程PAUSED，已遵守；有限背景batch仍按授權執行。若app/主機停止，之後需由使用者手動接續，不會自行恢復排程。

已公開同步程式到GitHub inmini-V3，稍後本次normalization修正再同步。新seed的可行PPA與113項正確性驗證不等於新版RL優勢；最終改善數據須以formal_v4結果為準。

## 本機工具交付（2026-11-02）

- 新 CLI：simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py，doctor/list/dry-run/run/status/stop/resume/summarize/audit/export/replay。明確的 smoke/diagnostic/research，順序執行；research 需使用者 --confirm-research。
- M/F 固定完整架構，M 固定 Fusion Off；候選與執行前雙重遮罩，整筆拒絕內含 A9 或越界 Fusion 的交易。Generic generator 與 features mask 分開；P2 為 2×2。
- 共用已完成 Seed、reference 與起點；P5 RNG 7/17/37 搭配 rank 0/1/2 的不同可行 Seed，不足就停止；相對收益永遠以全 archive 最佳 Seed 計算。
- seed、搜尋、Greedy lookahead、cache、timeout、reject 與 export 分帳；durable completed responses 防止中斷後重算已完成 PPA。不偽造遺失的 policy update。
- 最終 acceptance_verified：132 tests/0 failures/0 errors/source_stable=true/61.735s。workflow_verified：Toy 四方法、受控 stop/resume 同序列／最佳 mapping、唯讀分析不改 checkpoint/ledger、ZIP CRC，74.515s/source_stable=true。
- 新 Toy M 四方法各3 seed+9 search PPA；BA 與 Random 同為11.570939%改善，Greedy16.981520%，Atomic0%；僅小型工具驗收，沒有大型模型效益結論。
- Toy 固定 Mapping Fusion pair：2 PPA，On重播相符；另5 chosen-action pairs共8新PPA+2cache，不捏造缺少的timeout/recompute類型。
- 沒有啟動新的 ResNet 正式研究，也沒有恢復排程。長時間研究從使用者自己的 Terminal 啟動，無需 LLM/API/token，保留 Terminal 與電源即可。

- 本機交付壓縮包：output/uploads/INMIN_v03_Local_RL_Tools_20261102.zip，178檔／633046 bytes，CRC與逐檔SHA256均通過；SHA256 0b3be718b35c56075fa74a9a2dc287f717b883f8a221cd2d7922ed1b0200fb43。解壓至獨立驗證目錄後再跑Toy（6總PPA上限）完成，9.469秒、audit無錯誤。交付來源identity 30aa49973af5b948260d5bbd1b96f28bfdbc060390056873d6bef367c19939f9。
