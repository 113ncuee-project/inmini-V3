# INMIN v0.4：本機 Mapping 搜尋與實驗

更新：2026-11-03。專案目錄 `C:\Users\user\Desktop\rapidchiplet`。

## 本版的目的與範圍

先修正「完整 PPA 太慢、Actor 幾乎均勻選擇、可改善的資料重用方案沒有被探索」三個問題。第一階段固定硬體、Batch=1、Fusion Off，獨立比較 Mapping。硬體仍是 v0.3：每 Compute 16 PE、共享 1 MiB L2、無實體 Core，IO=2R。代表輸入是兩顆 Compute 的 2×1 與四顆 IO。

本版獨立 CLI，不會把 GUI／v0.3 Actor–Critic 的歷史結果改名成新系統。原起點生成器、50 架構搜尋與 Fusion 工具保留；這輪不把架構增益混入固定硬體 Mapping。

請使用本頁的新 PowerShell 入口。GUI04 仍使用既有 v0.3 控制器，尚未接入新的 Replay-Q 按鈕。

## 一次啟動整晚實驗

可直接在檔案總管雙擊 `run_inmin_v04_overnight.cmd`，使用下列預設值並暫時防止睡眠。它會開一般 PowerShell 視窗；不用讓 Codex 持續操作。進階參數與續跑則使用下面的 PowerShell 指令。

在 PowerShell 執行：

```powershell
Set-Location C:\Users\user\Desktop\rapidchiplet
.\run_inmin_v04_overnight.ps1 -KeepAwake
```

預設 ResNet18，固定同一個最佳 Tangram-style 起點，分別使用 RNG 7、17、37；各 RNG 依序執行 replay_rl、random、sa。每方法最多 256 次完整 PPA、3600 秒搜尋；每次 oracle 最多 300 秒。共用 reference／best seed 驗證最多兩次，計入各方法查詢預算，實際只共用執行一次；兩者 mapping 相同時只有一次 full PPA，另一次是明記的 cache hit。九個方法的搜尋時間上限約九小時，另加 seed 驗證／準備時間。這些是上限，不能當作已完成查詢數或收斂證明。

長跑只用本機 Python／CPU，不需要 Codex 持續開著、不消耗 LLM 額度、不恢復每小時排程。請讓 Windows 保持開機；`-KeepAwake` 暫時阻止自動睡眠，腳本離開時還原。鎖定螢幕可繼續運行。

先看命令、不執行 PPA：

```powershell
.\run_inmin_v04_overnight.ps1 -DryRun
```

只跑一個 RNG、提高完整查詢預算：

```powershell
.\run_inmin_v04_overnight.ps1 -Seeds 7 -Queries 512 -SecondsPerMethod 7200 -OutputRoot output/replay_v04_long
.\run_inmin_v04_overnight.ps1 -Seeds 7 -Methods 'replay_rl,random,sa,greedy' -OutputRoot output/replay_v04_with_greedy
```

增加模型與不同主要目標：

```powershell
.\run_inmin_v04_overnight.ps1 -Models resnet18,resnet50,mobilenet_v2 -Seeds 7,17,37 -Queries 256 -SecondsPerMethod 7200 -OutputRoot output/replay_v04_models
.\run_inmin_v04_overnight.ps1 -Seeds 7 -Objective edp -OutputRoot output/replay_v04_edp
.\run_inmin_v04_overnight.ps1 -Seeds 7 -Methods replay_rl -Generator generic -BottleneckFeatures off -OutputRoot output/replay_v04_G0F0
```

不要同時啟動第二個大型實驗；全域 OS lock 會拒絕重複執行。失敗或停止時，不會自動跳過並繼續後面案例。輸出已存在時，必須換名稱或使用 `-Resume`，不會覆蓋舊實驗。

## 停止、續跑、查看結果

以 ResNet18 RNG 7 為例，在另一個 PowerShell：

```powershell
New-Item output/replay_v04_overnight/resnet18/7/STOP_REQUESTED -ItemType File -Force
```

目前有界 oracle 完成後才停止並儲存。也可在執行視窗按一次 Ctrl+C。繼續整個佇列：

```powershell
.\run_inmin_v04_overnight.ps1 -Resume -KeepAwake
```

續跑使用原本凍結的程式、參數、環境與模型狀態；不會把新程式混入舊來源 cohort，也不會重新計算已完成的 durable PPA。新的超參數請使用新的 OutputRoot。已完成案例的 resume 不執行額外 PPA。

```powershell
Get-Content output/replay_v04_overnight/resnet18/7/status.json
Get-Content output/replay_v04_overnight/resnet18/7/runner.log -Tail 10
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/scripts/analyze_replay_mapping.py --out output/replay_v04_overnight/resnet18/7
```

分析不執行 PPA，也不修改搜尋 checkpoint。報告只有 Markdown／JSON／CSV；不產圖。查詢數／時間的完整數字曲線在 `analysis/curves.csv`，共同預算比較在 `equal_queries.csv`、`equal_time.csv`。

加上 `--offline-feature-ablation` 可以在同一批實際 RL 訓練資料上，重建 features on/off 的兩個模型，再用未訓練過的對照組資料測試。這是固定資料的預測消融，不是額外 PPA、也不是 features 對實際搜尋勝負的因果驗證。整晚佇列會固定 source identity；若期間修改程式，後續案例會停止，避免混合不同版本。

## Mapping 與策略如何運作

|階段|方法|哪些數字可以當作 PPA|
|---|---|---|
|起點|重用已完成的 bounded Tangram-style segment-DP seed；用新完整 oracle 重新驗證物理指標一致|兩次完整 seed 驗證；不是重新執行原版 Tangram|
|全域候選|每層 PE quota 1/2/4/8/16/全部、K/P/balanced partition、contiguous/spread/gateway placement、三種 DRAM flow、cold/auto/persistent weights|沒有預先 PPA 分數|
|局部複合候選|從實際 critical-path／service／queue 資訊找相鄰 layer window，整組調整資源／partition／placement／flow|完整 oracle 執行前只是 proposal|
|內層|真實可裝入的 PE fragment，三種有流量成本的 loop-order/dataflow，以局部 time×energy 排序|只是 proposal proxy，不能報成完整 PPA|
|RL|四次均勻 warmup 後，神經 Replay-Q 使用可重播的真實 PPA reward 學習候選效用，保留探索機率|只有實際完成且可行的 PPA 才供應 reward|
|執行／評分|完整編譯、整數 MAC、流量、資源日曆、實際 buffer lifetime、SRAM／DRAM／NoC／NoP 能量|這才是 full PPA；容量不合法的完成評估也計一次查詢|

全域與局部使用相同物理 hardware/template，空間 group 的 PE 所有權必須互斥，partition 必須非空整數。Retention 不是額外 SRAM：實際 WL2 arrival-to-last-reader 同時存活容量仍必須通過。失敗設計、timeout、compile reject 保留，不給假 reward。

Replay-Q 明確是 **gamma=0、單步情境式 RL／contextual bandit**，不是原 Actor–Critic 或已證明長期規劃的 DQN。每次完成的可行新 PPA 產生一個樣本，預設做 32 次 replay SGD。1,888 次 SGD 不能寫成 1,888 次 PPA。

Reward 使用 `-100 * log(actual_cost / best_seed_cost)`；數值尺度放大以便學習，但不改變 Cost 排序。沒有「碰到瓶頸就加分」或手寫動作收益。候選的 PE／partition／placement／retention 特徵、當前 PPA 和目標 layer 的實測證據輸入模型；最終 Q 與選擇機率由訓練得出。

45 維特徵的索引：0–15 動作／狀態資訊，16–19 當前物理 PPA 的 log-ratio，20–27 目標 layer 的 criticality、memory pressure、utilization、MAC/L1/VPU service 和最大 waits，28–33 完整候選的分配／partition／retention 摘要，34–44 quota 與動作屬性交互項。`--bottleneck-features off` 關閉 20–27，`--generator generic` 分別關閉瓶頸導向 window 選擇，兩者是不同消融。

## 瓶頸的定義與限制

Critical path 以實際排程的 dependency DAG **加上資源使用的先後邊**求 latest-start slack；接近零 slack 的 job 為該排程的 critical job。Layer 的 busy／queue wait／MAC／L1／VPU 時間和實際共享 pool 的 peak/capacity 提供嚴重度資訊。這些訊號進入局部候選和 Q 特徵。

Atomic routed transfer 同時保留多個資源，無法把同一次 queue wait 唯一分成 DRAM、NoC、NoP 等待。因此診斷保留 partial／unknown，不能把重疊 busy/wait 相加冒充端到端 latency，也不能宣稱單一 link 是已證明的唯一根因。

## 完整 PPA 的加速與準確度

沒有移除 NoC/NoP、容量或 routing。C++ treap free-gap calendar 保留原 deterministic list scheduler 的決策、double 時間、priority 與 lexical tie-break；native slack 保留相同 resource-order DAG。純幾何／kernel／route cache 只重用不變的描述；retention、所有 jobs、完整日曆、容量與能量仍重新求值。

已附此 Windows x64 的 source-hash DLL。確認可用：

```powershell
$env:PYTHONPATH='simplified_rapidchiplet'
.venv/Scripts/python.exe -c "from simple_rapidchiplet.hybrid.native_schedule import available,library_path; print(available(),library_path())"
```

若重新修改 C++，必須重新建 DLL，不能改名重用舊 binary：

```powershell
.venv/Scripts/python.exe simplified_rapidchiplet/scripts/build_native_calendar.py
```

可用 `--compiler` 指定本機 g++；沒有 binary 時會回到 Python coalesced 日曆，功能相同但較慢。不可在一次凍結 cohort 中更換 DLL。編譯來源、flags 與 compiler 記在 `.build.json`。

PPA 硬體常數及 memory/timing 假設沒有因此更準確。仍是未校準的 analytical PPA，非 silicon／cycle-accurate measurement。Balanced Cost 使用相對 Latency、Area、平均 Power 的等權平均；Power=Energy/Latency，因此務必同時列出 Latency、Energy、EDP。可用 `--objective edp/latency/energy` 另開預先指定的實驗。

## 怎樣判定 RL 有幫助

Random、SA、RL 使用相同原始 seed、完整 oracle、候選 grammar、內層 optimizer 和預算。SA 是我們同一套模板上的 SA comparator，不是原版 Gemini 程式。方法路徑會分岔，實際候選清單會跟著狀態改變。

交付版的 SA acceptance RNG 與候選／抽樣 RNG 分開，uniform warmup 從已驗證 elite 出發，讓三方法能共享相同 warmup 序列。早期 `r18_retention_pilot` 使用原本的單一 RNG，SA warmup 會分岔；其凍結來源與結果完整保留，不能說那一輪三方法的每個 warmup mapping 都相同。

可選 `greedy` 做完整 lookahead：先固定一輪同樣 grammar 的 shortlist，逐一完整 PPA 計費並保留最低成本；一輪結束後才從最佳 mapping 產生下一輪。它沒有免費看過候選 PPA。Greedy 日誌的 one-hot 機率表示固定評估順序，不是已訓練 policy；若有預算不足，保留該輪已驗證的最佳解。

數字審計分別提供：共同完整查詢預算、共同時間預算、從 seed 的改善、uniform warmup 後的改善，以及初始／最終模型在**未被 RL 訓練過的 Random/SA 真實 PPA**上的排序。Feature mask 只顯示模型是否使用瓶頸資訊，不能單憑 Q 值改變宣稱因果改善。

完整 oracle 另記 process CPU time 與 wall time。桌面機同一 mapping 的 wall time 可能受其他工作／CPU 狀態影響；不能把不同候選的平均耗時當成嚴格加速倍率，也不能把 CPU time 代替使用者實際等待的 wall time。精確後端 benchmark 使用相同 mapping、相同來源、fresh evaluator、無 profiler、交替順序。

若 Random/SA 也得到相近改善，表示 search space／inner optimizer 有價值，不能把全部收益寫成 RL policy 優勢。若只有一個 RNG，不能寫「穩定勝出」。論文需同時呈現負面結果與方法的實際 full PPA 數。

`best_measured_archive_metrics.csv` 另列實際評估過的最佳 Latency／Energy／EDP 和對應完整 mapping hash。這些是實測 archive 的額外指標；若該組訓練目標是 Balanced，不可改稱「RL 專門以 EDP 訓練」或事後更換原定主要比較指標。

## 檔案與依賴

若要重新產生起點，而非重用隨附 seed，可先用既有容量感知 segment-DP／beam adapter：

```powershell
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py run --profile research --phase p1 --arms seed_only --out output/new_seed_r18 --confirm-research
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/replay_mapping_dse.py --seed-case output/new_seed_r18/cases/resnet18/7/methods --out output/replay_from_new_seed --queries 512 --seconds 7200
```

Research seed 階段預設7200秒、最多16次完整seed評估、每oracle1800秒、內層DP proposal120秒；這是保留候選／剪枝的 bounded 搜尋，不是原版 Tangram 的全域窮舉完成證明。新輸入會重新選最低可行 objective 並驗證完整 PPA；不同起點與原比較要分開報告。共用舊 seed 的歷史生成時間不會被捏造成零：隨附 provenance 保留原來源，本版表格的搜尋計時則從共用 seed 的完整重驗開始。

|檔案|用途|
|---|---|
|`run_inmin_v04_overnight.ps1`|本機序列執行／續跑／暫時防睡眠|
|`simplified_rapidchiplet/replay_mapping_dse.py`|凍結、共同 seed 驗證、搜尋、checkpoint|
|`simple_rapidchiplet/hybrid/mapping_proposals_v4.py`|結構化 Mapping 與有價內層 dataflow|
|`simple_rapidchiplet/hybrid/replay_q.py`|實際 neural Q/replay 更新|
|`simple_rapidchiplet/hybrid/native_calendar.cpp`|精確資源日曆與 slack|
|`scripts/analyze_replay_mapping.py`|數字報告／完整帳本／未見候選驗證|
|`scripts/verify_replay_oracle.py`|獨立完整 PPA benchmark 與 inner-only 歸因對照|
|`inputs/replay_v04/<model>`|可攜的原始 workload/seed evidence，附來源 hash|

沿用專案 `.venv` 的 NumPy、PyTorch；重播所附 workload 不需要下載 pretrained weights 或再次 parse torchvision。新機器請建立 `.venv` 並安裝 `simplified_rapidchiplet/requirements-replay.txt`。需要重新產生模型 workload 時才另外安裝原 `requirements-graph.txt` 的 torchvision。

本機驗證環境：Windows x64、Python3.12.14、NumPy2.3.5、PyTorch2.7.0+cpu。新機器可使用 Python3.12 建立環境；目前這台電腦直接沿用既有 `.venv`。

完整輸出包含 source snapshot／seed input snapshot 的 SHA256、environment、common、proposal domain、events、完整選中 mapping、durable PPA、policy、checkpoint、query/time 帳本。保留這些檔案才能查證與續跑。

正常停止會先向 worker 傳 EOF 讓它結束；強制終止遇到 Windows helper timeout 時，fallback 先核對實際 OS parent PID，再終止本次擁有的 worker。Completed PPA 存在 durable archive，清理錯誤不會改成設計不可行。`parent_invocations.jsonl` 記錄各次啟動／續跑的 child startup、準備、搜尋與清理時間，與各方法的 search wall 分開。
