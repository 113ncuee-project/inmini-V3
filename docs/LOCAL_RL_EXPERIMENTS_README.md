# INMIN v0.3 本機 RL 診斷實驗操作

這套工具在你的 Windows 電腦執行既有 INMIN RL 與完整 PPA evaluator。不呼叫 LLM、OpenAI 或雲端推論 API，不使用 token，不下載 pretrained weights；開始後可離開 Codex 對話。所有報告只有文字與數字表格。

**先跑 doctor、dry-run，再選一個 phase。正式實驗由你啟動。既有暫停排程維持暫停。**

## 從哪裡啟動

目前專案位置為 `C:\Users\user\Desktop\rapidchiplet`。開啟 PowerShell 或 Windows Terminal，進入專案根目錄。以下所有相對路徑都從根目錄計算；也可把整個專案移到其他位置。

```powershell
Set-Location 'C:\Users\user\Desktop\rapidchiplet'
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py doctor
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py list
```

doctor 不執行模型或 PPA，會列出 Python、numpy/torch/torchvision、CPU/RAM、可用磁碟空間、來源 hash、runner 是否已有鎖。現有 `.venv` 可直接使用。若是全新電腦，先安裝 Python 3.12，建立環境及必要套件：

```powershell
py -3.12 -m venv .venv
& '.venv/Scripts/python.exe' -m pip install numpy==2.3.5
& '.venv/Scripts/python.exe' -m pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cpu
```

套件安裝需要網路；實驗本身不需要連線。換 Python／套件版本會影響重現性，舊實驗必須維持原環境。doctor 只查安裝資訊，不代表套件原生 DLL 已可正常載入；P0 smoke 會實際檢查執行鏈。

## 最小操作：先確認本機能跑

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py dry-run --profile smoke --phase p0 --out output/my_toy_smoke
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py run --profile smoke --phase p0 --out output/my_toy_smoke
```

`run` 是前景程序，請保留這個 Terminal 視窗。可以關閉 Codex 對話；關閉 Terminal、睡眠或重開機會中斷運算。睡眠後牆鐘會受到影響，請由你設定合適的電源及更新時間；工具不更改永久電源設定。

選用捷徑（功能相同）：

```powershell
& ./scripts/run_inmin_rl_experiments.ps1 doctor
& ./scripts/run_inmin_rl_experiments.ps1 dry-run --profile diagnostic --phase p1
```

若 PowerShell 的執行原則不允許 `.ps1`，直接使用上面的 Python 命令即可，不必改全機原則。

## 正式開始 ResNet18 Mapping-only

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py dry-run --profile diagnostic --phase p1 --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py run --profile diagnostic --phase p1 --out output/local_rl_v03_r18
```

預設固定 `single_array_c2_2x1`：2 Compute、2 列 × 1 欄、4 IO、每 Compute 16 PE、共享 L2。先完成 seed-only 預檢，再讓所有方法使用同一份已完成可行 Seed archive、同一最佳起點與 reference。若容量／timeout 導致無可行 Seed，整組停止並保留失敗，**不會替各方法偷偷換架構**。預檢同時核對多 die 工作配置及非零 NoP 流量；這不是宣稱每條流都是 Compute-to-Compute。

可明確選其他完整架構，例如 `--architecture single_array_c4_2x2`。請使用新的 output 目錄；不同架構結果不可當成同一 Mapping-only 組。

Mapping-only 在候選生成、聯合提案之後、實際執行前檢查完整交易。內含 A9 的交易整筆拒絕；Fusion stacks、tile、cache 必須不變。此版本 M 使用 Fusion Off，仍允許非 Fusion 的 group、partition、quota、placement、DRAM entry 與有真實流量成本的 A12 dataflow。

## 時間、查詢與階段

|Profile|共同 Seed 上限|每搜尋方法時間|單次 oracle|總 PPA 上限／方法（含 Seed）|用途|
|---|---:|---:|---:|---:|---|
|smoke|30 秒／3 PPA|90 秒|30 秒|12|只允許 P0 Toy，不能作研究結論|
|diagnostic|300 秒／4 PPA|1500 秒|300 秒|24|預設；每方法 charged seed＋search ≤1800 秒|
|research|7200 秒／16 PPA|7200 秒|1800 秒|128|需明確選取並加 `--confirm-research`|

以上是上限，不保證填滿查詢、不保證收斂。程序啟動、報告、磁碟存取有少量額外時間。Greedy 所有 lookahead 都計費；cache hit 不算新完成 PPA。Compiler reject／timeout 另外列出，沒有合法 PPA 就不給虛構 reward 或 policy update。

|Phase|模型|內容|diagnostic 保守牆鐘上限（不含少量啟動／報告）|
|---|---|---|---:|
|P0|Toy|Seed-only＋Random／Greedy／Atomic RL／Bottleneck RL|smoke 約 6.5 分鐘上限|
|P1|ResNet18|固定硬體、Fusion Off，四方法|105 分鐘|
|P2|ResNet18|固定硬體，Generic/Guided × features Off/On 四組|105 分鐘|
|P3|ResNet18|固定硬體 Fusion Off/On 搜尋＋1 組 Fusion 配對＋最多 5 組 chosen-action 配對|140 分鐘|
|P4|ResNet50 v1.5、MobileNetV2|各模型只跑 Greedy／Bottleneck RL|110 分鐘|
|P5|ResNet18|Greedy／Bottleneck RL，RNG 7、17、37|165 分鐘|
|P6|ResNet18|可選 Joint，全部 50 架構可達|55 分鐘|

P1／P2 的 105 分鐘是整組順序執行的上限，**不是每 arm**。共用 Seed 實際只執行一次，但其成本分別向每方法計費。P5 使用 RNG 7／17／37，分別從按完整 PPA 排名的第 0／1／2 個不同 Seed state 開始；每組所有方法仍共用同一起點，改善始終相對全 archive 最佳 Seed。若沒有足夠可行且不同 fingerprint 的 Seed 就停止，請在新 output 明確增加 seed 預算。Seed beam 本身是決定性的，這不是隨機獨立抽出的起點分布；P5 同時變動起點與 RNG，不能單獨歸因其中一項。

`list`／`dry-run` 會列每個 phase 的**實際有效設定、子程序參數、unique Full PPA 保守上限及時間上限**。指定 `--arms greedy,bottleneck_rl` 可縮小原生方法比較；P2 通常保持預設以保留完整消融。

需要更長的實驗，由你明確啟動，例如：

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py dry-run --profile research --phase p1 --out output/r18_research
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py run --profile research --phase p1 --confirm-research --out output/r18_research
```

可用 `--queries`、`--seed-queries`、`--seed-seconds`、`--seconds`、`--oracle`、`--dp` 明確調整。diagnostic 超過每方法 30 分鐘會拒絕，需改選 research。這些設定建立後不可在同一 output 更改。

## 查看、停止、續跑

在另一個 PowerShell 視窗執行：

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py status --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py stop --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py resume --out output/local_rl_v03_r18
```

stop 寫入這個 output 的停止請求；目前 bounded oracle 完成或 timeout 後保存 checkpoint，再停止。**最久可能要等單次 oracle timeout**。它不殺其他研究程序。單例 OS 鎖阻擋同一 checkout 的第二個本機診斷 runner；舊 CLI 不使用這個總鎖，請勿另外啟動大型工作競爭資源。

Ctrl+C 也會盡可能收尾；如整機斷電，最後未完成的 request 是 interrupted/unknown，不能算失敗 PPA。已完成 PPA 另外存有 durable response，續跑可恢復，避免為了報告或中斷重算。中斷發生在 PPA 完成與 policy checkpoint 之間時，只恢復物理結果，不虛構已經做過的 policy 更新。

resume 使用 output 內凍結的程式，不受之後修改工作目錄影響；會核對快照 hash、有效設定與 Python／套件環境。不覆寫舊 frozen snapshot。已完成 case 直接跳過。若只想重新分析完成資料，不必 resume。

## 分析與匯出（不跑模型／oracle）

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py summarize --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py audit --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py replay --out output/local_rl_v03_r18
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py export --out output/local_rl_v03_r18
```

replay 不做 PPA、不重新訓練：取同一個決策當時的 actor、state、候選集合，只改 feature mask，輸出機率／排名／entropy 差。初始零權重的 actor 兩者相同屬預期，不能據此判定後續訓練特徵無用。

`--generator generic` 移除 measured compute/hotspot guidance、critical-window 排名及 memory-pressure 專屬提案，保留靜態合法複合動作與確定性的 window 探索。這會改變候選集合。`--bottleneck-features off` 只遮蔽 actor/critic 動態特徵。P2 分別記錄 G0F0、G0F1、G1F0、G1F1，不能把任一單獨開關說成完全關閉所有瓶頸機制。

主要輸出：

|檔案|內容|
|---|---|
|manifest.json／effective_config.json／feature_schema.json|run ID、環境、設定／hash、24／283／12 維特徵逐欄名稱及正規化|
|source_snapshot/／source_snapshot_manifest.json|不可變程式及來源檔案 SHA256|
|suite_status.json／logs/|case 狀態、所屬 PID、子命令、stdout/stderr|
|cases/.../seed_attempts.json／common_start.json|提案來源、可行 Seed、真實 seed 時間／查詢、共同起點與最佳 Seed 的分別|
|cases/.../checkpoint.json|原生 policy、RNG、archive、cache、trace|
|cases/.../shortlists/*.json.gz|完整 ordered edits、before state、決策前 actor、候選 hash|
|cases/.../worker/accounting.json|完整 PPA、cache、timeout、compile reject、export 分帳|
|cases/.../evaluation_events.jsonl／query_events.jsonl|每個搜尋 oracle 回應、完整動作及 query context，含 Greedy lookahead、cache hit、timeout、cost、時間、來源|
|reports/summary.md／compare_methods.csv|共同 Seed 及方法比較|
|reports/best_vs_wall.csv／best_vs_full_ppa.csv|含共同最佳 Seed 起點的數字曲線，不產圖|
|reports/action_funnel.csv／policy_learning.csv|提案／選擇／可行／正 reward、entropy 與更新|
|reports/bottleneck_effects.csv／failure_reasons.csv|before/after 資源量差、拒絕與失敗|
|reports/fixed_candidate_replay.json|0 PPA 的固定候選 features 消融|
|reports/fusion_pairs.csv／chosen_action_pairs.csv／diagnostics.md／audit.json|Fusion／chosen-action 配對結果、下一個最小鑑別測試與審計|

空白／unknown 表示沒有證據，不填 0 假裝有測量。行為漏斗中未記錄的中間階段也不能當成已通過。巨量 calendar 不重複保存；診斷只保存原生有界摘要，保留 truncation 標記。

## 結論邊界

Balanced cost 同時包含 latency／area／average power，平均功耗是 E/T。因此 cost 改善不一定代表 latency 或總能量改善，請一起讀各實體欄位。最佳 Mapping 的改善只相對共同最佳已完成 Seed 計算，DP Seed 收益不算 RL 收益。

PPA 是未校準的 Python resource-calendar 分析模型；沒有 silicon、SRAM macro、packet/VC cycle 或完整 C-panel/spill 校準。whole-flow reservation 保守，wait 無法唯一歸因於某個硬體資源。負面結果、timeout、容量不可行和沒有探索的區域全部保留；不能用有限搜尋宣稱全域最佳。

本輪小型驗收的實際結果另見 `docs/LOCAL_RL_TOOLS_VALIDATION.md`。新工具沒有替你啟動 P1～P6。匯出的 zip 是分析證據包；完整工作目錄與 durable responses 請保留以供續跑。
