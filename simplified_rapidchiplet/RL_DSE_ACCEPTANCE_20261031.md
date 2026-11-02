# RL chiplet DSE：獨立驗收與消融範圍

本文件區分可手算的正確性驗收、真 backend 整合驗收與有限預算實驗。它不把 toy 搜尋結果當成大型模型效能結論，也不宣稱分析 PPA 經過 RTL、timing 或 silicon 校準。

## 可重現執行

預設 shell 的 Python 3.14 未安裝 numpy；本次驗收使用 Codex bundled Python：

```powershell
$python = 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location 'C:\Users\user\Desktop\rapidchiplet\simplified_rapidchiplet'
& $python -m unittest discover -s tests -p test_rl_acceptance.py -v
& $python -m unittest discover -s tests -p test_joint_rl.py -v
& $python -m unittest discover -s tests -p test_tangram_seed.py -v
```

`tests/test_rl_acceptance.py` 是獨立新增的驗收檔，不以測試裡的簡化公式取代 production evaluator。

|驗收|手算 oracle／要求|實際範圍|
|---|---|---|
|非關鍵路徑|兩路 10 秒與 4 秒，join 1 秒；短路改成 1 秒，E2E 仍為 11 秒；slack 6→9 秒|production scheduler 與 diagnostics 的 schedule slack|
|網路反例|三條分離的 2-hop、1 B/s 路徑，各流 1 B，makespan 1 秒；搬到共用 1-hop 後 hop-bytes 6→3，但 makespan 3 秒|production transfer-service 與 resource calendar；小型顯式 network oracle，不增加系統的任意 routing 自由度|
|尾塊與 halo|B=1、K=5、H=W=5，2×2 空間分割與 2×2 tile：每層 9 個 tile，125 個輸出元素恰覆蓋且互不重疊；右下 1×1 conv tile 的 input 區域為 2×2|production mapping compiler；原始 residual Add 的兩路輸入保留|
|容量拒絕|即使單一輸出元素也放不下 scratch 時，compiler 拒絕，不回傳免費 spill 或虛構 PPA|production tile compiler|
|同時存活容量|shortcut 100 B、activation 80 B、cache 30 B、psum 20 B、weights 50 B 同時存活，峰值 280 B；相同時間先 release 再 allocate|production peak-interval 計算；各 component peak 不直接相加當作系統峰值|
|A9 真 backend 擴縮|Gemini 1→2→1 compute chiplets，chain 與 residual 各自完整評估；面積與資源變更、MAC 守恆、撤離後沒有失效 core/memory；恢復原完整 mapping 後由新 evaluator 重算，L/A/P/E 與原始一致|原生 RapidChiplet package backend＋HybridEvaluator；沒有測試用 PPA oracle|
|GLB 單 port|每一筆 DMA 傳輸與 PE-side read/write 都必須 reserve 對應 core 的同一 GLB port；每個 port 的所有 DMA／read／write 區間互不重疊|真 Gemini native backend 的完整事件表；避免 DMA 與 PE 的 GLB 存取免費併行|
|Reward|固定 reference、gamma=1；L=10→8→6、Lmax=8、penalty=4，reward 分別為 16/15、1/15，其和等於起終 penalized cost 差|production JointObjective 與 compute_reward|
|無隱藏 bonus|相同 PPA 下僅變 chiplet count／hop bytes，reward=0；cost 變差 reward<0；非有限 PPA 不可執行|production reward 與 executable contract|

`test_joint_rl.py` 另驗證 A11→A9 alias、transaction rollback、stale plan、cache identity、合法較差 state commit／最佳 archive 分離、macro 明確 edit 清單與最終 state dedup、未知診斷 generic fallback、policy behavior probability、resume 重現、精確 physical-invalid mask 等。`test_tangram_seed.py` 驗證 seed 的 DAG／precision 保留、來源邊界、完整 evaluator 排名與初始化成本記帳。

## 消融設定與解讀

正式實驗由 `scripts/run_rl_dse_ablations.py` 執行；每個 run 是獨立 Python process，保存執行前後所有相關 source hashes、配置、完整 transition、checkpoint、DAG、PPA、macro proposal／selection／improvement 計數及時間。

```powershell
& $python scripts/run_rl_dse_ablations.py --budget 16 --seeds 3,7,11 --workers 2 `
  --out '../output/rl_dse_20261031/ablations_final'
```

可變數量組比較 atomic RL、guided atomic RL、composite RL、composite random 與 composite greedy，各 3 seeds，共 15 runs；另有固定 compute count=4 的 composite RL 3 runs。固定數量仍可能探索合法矩形模板，IO 數量會隨模板列數改變並付費。兩組可行域與固定 reference 不同，因此分開彙總，不把擴充硬體的效果歸功於 RL mapping。

模型是可手算 toy residual（B=1、K=5、H=W=7）；每組預算 16 個 RL exact-cache miss queries。面積上限 250 mm²、平均功率上限 3 W、batch latency 上限 0.02 ms；所有限制與偏好在各 run 內固定。實際 backend full evaluations、seed、報告重算及 wall time另外保存。貪婪方法使用相同候選與 evaluator，所有 lookahead 查詢都計入；其 family 的 selected-transition query time 不包含可由全域 accounting 看見的 lookahead，不能當作完整 macro overhead。

報告以相同 query 預算比較；wall time 是量測結果，沒有聲稱同時滿足相同 wall-clock 預算。3 seeds、toy 與小預算只提供 smoke／記帳證據，不能證明 RL 相較 random 或 greedy 存在普遍優勢。沒有 strict-feasible archive 時 best cost／PPA 保留 null，不能以 closest 方案冒充推薦。

舊 `output/rl_dse_20261031/ablations` 在硬體 single-port GLB resource 問題發現後已停止，保存為來源修正前的參考，並有 `OLD_SOURCE_DO_NOT_COMPARE.json` 標記；不得與修正後正式結果混合。

## 2026-10-31 正式驗收結果

`output/rl_dse_20261031/acceptance_final/result.json` 保存凍結來源上的 39 個相關測試結果：獨立 acceptance 9、joint RL 19、production integration 4、Tangram seed 7，全部通過，測試前後 source hashes 相同。

`output/rl_dse_20261031/ablations_final` 的 18 個正式 runs 全部完成；每次用滿 16 個 RL 完整查詢、都有 strict-feasible archive，所有 run 的 `source_stable=True`，跨 run 只有一個 source manifest identity：`6653b01abe7c70e349d30e4828145b167d8171a8e3a2d95191fc775ce9750851`。

下表為各 3 seeds 的最佳可行方案平均；cost 是相同 scope 下固定 reference 的正規化 PPA 目標，越低越好。

|Scope|候選／選擇|Best cost mean ± sample stdev|Latency mean (µs)|Area mean (mm²)|Average power mean (W)|Energy mean (µJ)|
|---|---|---:|---:|---:|---:|---:|
|Variable|Atomic RL|0.953087 ± 0.041365|1.778411|77.771997|0.904818|1.604454|
|Variable|Guided atomic RL|0.953087 ± 0.041365|1.778411|77.771997|0.904818|1.604454|
|Variable|Composite RL|0.991697 ± 0.014382|2.110517|77.771997|0.873276|1.842114|
|Variable|Composite random|0.991697 ± 0.014382|2.110517|77.771997|0.873276|1.842114|
|Variable|Composite greedy|0.973160 ± 0.000000|1.959360|77.771997|0.885128|1.734285|
|Fixed compute count 4|Composite RL|1.000000 ± 0.000000|4.743398|127.739267|1.821421|8.639722|

在這個 toy、小預算設定下，composite RL 與 random 的最佳成本相同，且 composite 組沒有優於 atomic 組；不能宣稱 RL 或複合策略的效益已經被本實驗證實。固定數量組在本次預算內沒有改善初始化成本。這些負面／持平結果如實保存，不調整候選或 seed 來挑選較好看的結果。

所有 C1–C10 的逐 run 原始提案數、選擇數、有效數、改善率與 query 時間保存在 `macro_statistics.csv/json`。合計實際觀察到 C2、C3、C4、C5、C6、C7、C8 的選擇；C1 未觸發、C9 有提案但未選擇、C10 仍明確 unsupported。沒有觀測到的 family 不以其他 family 的結果代替其實驗證據。

`independent_audit.json` 逐 run 獨立核對：P=E/T、最佳 cost 與固定 reference 重算一致、最佳方案無硬限制違反、每個有效 step 的 reward 與 penalized cost 差一致、behavior probability/log-probability 一致、選中 macro 至少含兩個明確 edits；實際 backend full evaluations 等於 seed full + RL 16 + archive 報告重算，全部通過。
