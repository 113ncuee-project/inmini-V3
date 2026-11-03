# 本機 RL 工具交付與小型驗收

日期：2026-11-02，Asia/Taipei。

本輪只實作本機工具、跑小型驗收。沒有啟動 ResNet18／ResNet50／MobileNetV2 的 P1～P6 正式實驗，沒有恢復暫停排程。舊 `formal_v4` 的失敗與 frozen snapshot 保留原樣，不自動重啟。

規格原件保存在 `docs/specs/INMIN_v03_RL_Local_Diagnostic_Test_Spec.md`，原附件 SHA256：`d4869eb05f98d130ad5d0611bb954ccbf2b5e499b6544d1a115e97882c4ac921`。

## 檔案與功能

|檔案（相對專案根目錄）|功能|
|---|---|
|simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py|doctor／list／dry-run／run／status／stop／resume／summarize／audit／export／replay；順序執行、不可變快照、鎖、所屬 PID 與明確預算|
|simplified_rapidchiplet/scripts/analyze_local_rl_diagnostics.py|不啟動 oracle 的 Markdown／CSV 重建、查詢／時間曲線、行為漏斗、物理差分、失敗規則與審計|
|simplified_rapidchiplet/scripts/check_local_rl_diagnostics.py|獨立審計入口|
|simplified_rapidchiplet/scripts/local_rl_feature_schema.py|24 維 state、283 維 candidate、12 維 target 的逐欄名稱、順序、正規化與來源|
|simplified_rapidchiplet/scripts/run_local_action_pairs.py|最多 5 組代表性 chosen actions，固定各自 before state 的雙 oracle 配對；最多 10 次額外完成 PPA|
|simplified_rapidchiplet/scripts/test_local_rl_workflow.py|Toy 四方法、受控中斷／續跑、完整 PPA 不重算、唯讀分析、export CRC 驗收|
|simplified_rapidchiplet/tests/test_local_rl_diagnostics.py|19 項新測試，涵蓋遮罩、消融、不同起點、metadata 鎖、缺損／零可行資料、durable recovery 等|
|scripts/run_inmin_rl_experiments.ps1|已實測的 PowerShell 捷徑，沿用本機 `.venv`|
|simplified_rapidchiplet/simple_rapidchiplet/hybrid/search_space.py|完整交易的 Mapping-only／Mapping+Fusion／Joint 邊界檢查|
|simplified_rapidchiplet/simple_rapidchiplet/hybrid/rl_actions.py、single_array_proposals.py|候選階段遮罩、Generic/Guided 分開、合法性與 family 帳本；Fusion Off 的 C9 不再要求 Fusion On 必須合法|
|simplified_rapidchiplet/simple_rapidchiplet/hybrid/rl_search.py|執行前再次檢查交易、每個 query context、決策前 actor/state/shortlist、恢復已完成物理結果|
|simplified_rapidchiplet/simple_rapidchiplet/hybrid/single_array_runtime.py|完成 oracle response 的 durable 保存與中斷後回收；不虛構 policy 更新|
|simplified_rapidchiplet/simple_rapidchiplet/hybrid/single_array_evaluator.py|只增加 host wall 階段計時，沒有更改 PPA 計算公式|
|simplified_rapidchiplet/single_array_dse.py|明確固定架構／搜尋空間、共同 Seed、seed-only、起點 rank、停止請求、完整查詢事件與時間分帳|
|simplified_rapidchiplet/scripts/run_single_array_counterfactual.py|重用既有 Fusion 配對，支援固定架構來源一致性檢查|

## 最終驗收證據

|檢查|實際結果|本機證據|
|---|---|---|
|原有回歸＋新測試|132 tests，0 failures，0 errors，source_stable=true；61.735 秒|output/local_rl_tools_20261102/acceptance_verified/result.json、tests.log|
|完整本機操作流程|通過；74.515 秒；來源在測試期間不變|output/local_rl_tools_20261102/workflow_verified/result.json|
|受控中斷與續跑|中斷時完成 3 search PPA，續跑到 9；動作序列與不中斷執行完全一致，最佳 Mapping 決策 hash 一致|workflow_verified/resumed 與 full 的 checkpoint、ledger、trace|
|已完成 PPA 不重算|完成 response 的 durable keys 無重複；共同 Seed 實際只做一次|各 worker/accounting.json|
|唯讀操作|status、summarize、audit、replay、完成後 resume 沒有改動 checkpoint／oracle 帳本|workflow_verified/commands.log、result.json|
|壓縮匯出|ZIP CRC 通過|workflow_verified/resumed_evidence_*.zip|
|缺損／0 feasible／timeout／單一搜尋 arm|可產生報告；未知保持未知，不啟動 oracle|新 unit tests；workflow_verified/resumed/reports|
|Toy 固定 Mapping Fusion 配對|兩邊可行，2 次額外 PPA，On 重播與原已完成 PPA 一致|output/local_rl_tools_20261102/toy_fusion_pair/summary.json|
|5 個 Toy chosen-action 配對|完成；8 次新 Full PPA，另外 2 次為 cache reuse|output/local_rl_tools_20261102/toy_action_pairs_verified/summary.json|

完整流程使用的 immutable snapshot identity 為 `0b528543cc98d24bf843089046ae3ada9e71fd1b04ca4836b17580c5de9f00cf`。交付前另補了「沒有可行 Seed 時先做容量／timeout 診斷，不啟動 P2」的報告分支及相應 unit assertion；最終 132 項驗收涵蓋這個版本。沒有為了修改報告而重跑既有實驗 PPA。

受控中斷測的是停止請求與 checkpoint；未宣稱做過真實斷電。另以 unit test 模擬 parent 尚未記帳但 durable response 已完成的恢復邊界。重啟後沒有完成回應的 request 保留 interrupted/unknown。

## Toy 結果範例（只驗工具）

Toy，Batch=1，固定 `single_array_c2_2x1`（2 Compute／4 IO），Fusion Off，RNG 7，balanced objective，共同最佳 Seed cost = 0.8851239364。

|方法|共同 Seed PPA|搜尋 PPA|最佳 cost|相對最佳 Seed 改善|Policy 更新|
|---|---:|---:|---:|---:|---:|
|Seed-only|3|0|0.8851239364|0%|0|
|Random|3|9|0.7827067830|11.570939%|0|
|Greedy|3|9|0.7348164404|16.981520%|0|
|Atomic RL|3|9|0.8851239364|0%|9|
|Bottleneck RL|3|9|0.7827067830|11.570939%|9|

實際 unique 完成 PPA = 3 + 4×9 = 39。四方法都向自身計費 3 次共同 Seed；沒有把共同初始化重複宣稱為實際 CPU 執行。

在這個 Toy／固定硬體／單一 RNG／12 次含 Seed PPA 的小型驗收，Bottleneck RL 與 Random 相同，未超過 Greedy。不能把它寫成已證明 RL 優勢，更不能取代大型 DNN 的正式結果。

額外的一個固定 Mapping Fusion 配對：

|量|Fusion Off|Fusion On|
|---|---:|---:|
|Latency（μs）|8.150678|15.360483|
|Energy（μJ）|5.399545|10.261359|
|DRAM read（B）|1065|3715|
|NoC hop-bytes|3680|8832|
|NoP hop-bytes|7488|17328|
|Executed MAC|12250|12250|
|Recompute MAC|0|0|

這個負面例子顯示流量增加不一定伴隨重算 MAC 增加。它只定位到本次 Mapping／stack／分析路徑的資源差，尚不能判斷是 Fusion compiler、buffer/scheduler 模型或硬體本身的根因。原始 before/after 與診斷全部保留。

## 輸出與限制

事件／曲線／報告保留完整查詢上限、實際完成數、cache、timeout、compiler reject、export、來源與 state hash。Greedy 所有 lookahead 都計入。best depth 從最佳狀態計算，max evaluated depth 另外列，不能互換。

P3 的 chosen-action 選樣可缺少 timeout、重算增加等類型；缺少類型會在 selection.json 列出，本次 Toy 沒有刻意製造硬體失敗。共享 pool、whole-flow reservation 的瓶頸效果僅為 partial attribution。

這是未校準的 Python 分析式 PPA，不是 silicon 測量。沒有完整 C-panel/spill、SRAM macro、packet/VC 與 bank-address 校準；沒有宣稱全域最佳或一般性的 RL 優勢。實驗不需要 Codex 連線、不使用 LLM API/token。正式 P1～P6 要由使用者自己在 Terminal 選 profile／phase 啟動。
