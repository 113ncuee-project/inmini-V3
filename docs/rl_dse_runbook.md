# Gemini 2×2-core／複合動作 RL 操作手冊

2026-10-31，Asia/Taipei。這份說明取代 production 入口的舊 V2 行為，歷史輸出不變。

## 執行

從專案根目錄啟動 GUI：

```powershell
.\simplified_rapidchiplet\scripts\start_hybrid_gui.ps1
```

開啟 `http://127.0.0.1:8765`。使用者選擇一或多個模型、batch、PPA 偏好及上限；系統負責探索 chiplet 數量與部署。多模型共同推薦的架構，必須被每個模型的搜尋實際評估且全部符合硬限制。未訪問的候選不補造評分；小預算可能只涵蓋部分架構。

CLI 的預設模式聯合搜尋顆數、合法形狀與 mapping：

```powershell
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --model toy --batch 1 --preference balanced --budget 24 --planning-budget 2 --out simplified_rapidchiplet/results/gemini_rl_demo

.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --model resnet18 --batch 1 --preference low_latency --max-area 800 --max-power 16 --max-latency 0.5 --budget 64 --out simplified_rapidchiplet/results/resnet18_rl
```

`--max-latency` 單位為秒，GUI 為毫秒。`--soft-area`／`--soft-power`／`--soft-latency` 將相應上限轉成軟目標。`--mode search --dies 4` 固定 compute 數量，仍可比較合法矩形形狀；`--mode evaluate` 僅評估起點。`--input-size 32` 是 smoke test；真實模型預設 224，不得把 32 的數字當 224 的效能。`--workload path.json` 可輸入後端支援算子的明確 DAG（欄位見輸出的 `workload.json`）；未知算子／精度／形狀會拒絕。

`--resume` 讀回 checkpoint；來源、工作量、硬體、偏好與設定必須一致。checkpoint 保存探索 state、最佳 archive、精確 cache、RNG、policy／critic、候選統計與消耗預算。異動來源後應使用新 output 資料夾，不能沿用舊 PPA。直接 `run_joint_search` 可提高累計 budget 繼續；production suite 使用同設定接續中斷工作。

舊 V2 重播：

```powershell
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --engine legacy_v2 --model toy --batch 1 --budget 8 --out simplified_rapidchiplet/results/legacy_replay
```

## 系統資料流與介面

1. `hybrid/models.py`／`workload.py` 解析 FX/meta 模型或明確 operator/tensor DAG，保存 residual／Add、形狀、precision 與來源。
2. `tangram_seed.py` 重用 DAG segmentation DP/beam，提出 grouping／microbatch／allocation 起點，並以完整 evaluator 排名。每次 proposal、失敗、評估與耗時都有記錄。
3. `hardware.py`／`architecture.py`／`gemini_network.py` 建立固定四 core chiplet、合法矩形模板、雙側 IO／DRAM 與逐 core NoC／D2D links。
4. `rl_schema.py` 保存 DesignState、ActionEdit 與 ActionPlan。`rl_actions.py` 以明確參數做交易式原子／複合修改，重建所有受影響 mapping、資料位置與相依。
5. `rl_search.py` 的 masked candidate softmax actor-critic 從真實成本差值學習；先驗只影響候選生成，不修改物理成本或添加「增加 core」bonus。每筆保存實際 behavior probability。合法但較差的探索狀態仍提交，最佳可行 archive 另存。
6. `evaluator.py`／`scheduler.py` 完整重算容量、tensor regions、MAC、DRAM／NoC／D2D、共享資源與完整 makespan。`diagnostics.py` 提供有依據的瓶頸報告。
7. `rl_report.py`／`visualization.py` 輸出實際 DAG、搜尋曲線、動作／診斷、架構、core／layer mapping 與逐流路徑。

## 硬體與 PPA 定義

每顆 compute chiplet 固定 2×2 完整 cores；每 core 1024 MAC/cycle、16 PEs、2MiB GLB、vector／control／DMA／router。每側兩個 D2D interfaces，共八個，未連接的邊界 interfaces 也付面積／漏電。預設探索 1／2／4／8／16 顆與 15 個矩形模板。每一 compute-chiplet row 的左、右各一 IO＋DRAM；相同 row 增加 compute 不會憑空增加 DRAM 帶寬。詳見 [硬體與成本契約](gemini_hardware_contract.md)。

`area_mm2` 包含 compute＋IO＋DRAM 的總矽面積；封裝 footprint 另列。`latency_s` 為固定 batch 完整 makespan；`energy_j` 為同一時間窗能量；`power_w=energy_j/latency_s` 為平均功率，Energy 與 Power 不混用。PPA 是未校準的文獻參考分析估算，沒有 RTL／timing／silicon signoff。

偏好使用正規化線性成本 `J=wL L/Lref+wA A/Aref+wP P/Pref`；references 在每個模型的整次搜尋固定。均衡各 1/3；低功率／小面積／低延遲的主要權重 0.8、其餘各 0.1。軟目標加入正的相對超標 penalty。硬限制違反量 `V` 輔助中途探索，`r=(Jold+10 Vold)-(Jnew+10 Vnew)`，gamma=1。最終 archive 先要求硬限制可行，再比較 J。找不到可行解時 `recommended_architecture=null`，最近的可執行診斷方案另存 `closest_architecture`，不冒稱推薦。

## 動作與能力邊界

歷史清單有 11 個標籤；A11 匯入時正規化成 A9，所以只有 10 個唯一 transitions：fusion、parallel partition、DF tile、resource transfer、同層位置、跨層位置、overlap cache、DRAM 配置、架構切換、pipeline group。A9 是設計時硬體變更，必須顯式撤離／重新分配工作及資料，重算 IO／帶寬／面積／功率。

C1–C9 提供有序的協同修改；候選名稱表示意圖，不能保證 reward 為正。hard validity mask、瓶頸 shortlist 和 policy selection 分開記錄，並保留不依賴診斷的通用候選。完整能力矩陣在 `joint_search.json.capabilities`，動作細節見 [動作契約](rl_dse_action_contract.md)。

目前不支援：原版 Tangram binary／BSD／ALLO、任意 physical floorplan 或 routing、input-channel C 的跨 chiplet partial-sum reduction、peak power、無 backing capacity 的自動 spill、垂直單軸 overlap cache。C10 局部 communication-aware DP 為可選擴充，預設關閉。Tangram 起點是來源可稽核的 **adapter**，未宣稱與原版輸出等價，詳見 [來源對應與差異](../simplified_rapidchiplet/TANGRAM_SEED_ADAPTER.md)。

RL 指定的 tile／cache 不會交由隱藏的內層 fusion optimizer 覆寫；現有單層 temporal mapper 仍推導實際 PE 服務成本。`--fusion off` 關閉相關 DF／fusion 動作。無法唯一拆分的 NoC／D2D／DRAM queue waits 顯示 unknown／null，不能把重疊時間全部相加。

## 輸出與驗證

每模型資料夾有 `report.html`、`seed.json`、`joint_search.json`、`checkpoint.json`、`accounting.json`。每個已探索架構 archive 有 `mapping.json`、`deployment.json`、`hardware.json`、`package.json`、`diagnostics.json`、`traffic_routes.json`、`timeline.csv`、`link_traffic.csv`、`layout.html`、`architecture.svg`。suite 頂層有共同推薦 `recommendation.json` 與 `suite.json`。

初始化預算和 RL 唯一完整設計評估預算分開，全部耗時／查詢都列帳；seed 後清除底層評估 cache，避免將 seed hit 記成完整 RL query。輸出重播的完整 trace 評估也包括在 `total_full_evaluations_this_process`。Greedy lookahead 每個實際評估都扣預算，不能將一輪 lookahead 稱為一次查詢。

測試與正式消融位置：`output/rl_dse_20261031/`；正式 GLB-port 修正後實驗為 `ablations_final/`，舊 `ablations/` 僅為修正前證據，不可混合比較。完整驗收見 [acceptance 說明](../simplified_rapidchiplet/RL_DSE_ACCEPTANCE_20261031.md)。

```powershell
$env:TEMP=(Resolve-Path tmp).Path
$env:TMP=$env:TEMP
cd simplified_rapidchiplet
..\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
```

測試涵蓋 alias 去重、交易回復、尾塊／halo、residual 存活、A9 擴縮、資源競爭、非關鍵路徑反例、reward 差值守恆、精確快取和 checkpoint 重現。Toy 多 seed、相同完整 query 預算的消融用於驗證機制，不能證明真實模型上 RL 優於 random 或全域最優。
