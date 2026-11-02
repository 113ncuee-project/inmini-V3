# INMIN v0.2 單一 PE Array 硬體改版與 Bottleneck Aware RL 實作規格

日期：2026-11-01  
交付對象：Codex  
文件用途：作為後續程式修改、驗證與實驗的具體執行規格。本文件不是新硬體已實作、已驗證或已取得最佳 PPA 的聲明。

## 0. 本次任務與不可違反的原則

**目標：** 將目前 INMIN 的 Gemini 2×2 Core 設定改為附件 `Chiplet_Hardware_Spec_v0.2_reviewed.md` 所述的**單顆 Compute Chiplet 內有 16 個 PE、晶粒共享 W/A/O L2、沒有實體 Core**的架構，同時把既有候選式 Actor–Critic 搜尋改成能使用完整 PPA 證據診斷瓶頸、提出有策略的原子或複合動作、並能評估這些動作的 bottleneck-aware 系統。

優先順序：**正確性與資源守恆 → 搜尋可達性 → 瓶頸導向搜尋 → DF／Mapping 聯合探索 → 少量代表性測試 → 正式報告。**

1. 不得直接覆寫既有 `gemini_2x2_core_v1`、`homogeneous_mesh_4x4_v1` 與歷史 GUI v1/v2 數值實驗的模型及輸出；以**新的硬體 profile／engine schema**實作，保留舊設定回放、Checkpoint 與原報告。
2. 本版使用者仍只輸入 DNN、PPA 限制與 Preference。GUI04 固定 **Batch=1 即時推論**、`seed=7`（進階可檢視）、`budget_mode=Auto`、`search_mode=standard`。Chiplet 數、形狀、Layer Group、Mapping、Partition、Fusion Depth、Tile、Cache 由系統搜尋。
3. 新架構的部分參數在 v0.2 原稿明列為**研究假設 M 或待定 T**。M 必須寫入版本化設定及報告，不可當成 Gemini／INDM 量測值；T 不准捏造來源或悄悄給免費資源。若初版需選一個模型假設才能跑，應以明確的 `experimental_assumption` 固定、註明尚待確認，並和已定規格區分。
4. 單一步 RL **只選一個候選 ActionPlan**；它可以是一個原子動作，也可以是一組原子修改構成的複合交易。不得將「永遠只用複合動作」寫死，也不能因診斷為通訊瓶頸就完全封鎖增加 Chiplet 的探索。
5. PPA／Reward 只來自經過完整編譯、通訊、排程、容量與成本檢查的 Evaluator。Local DP、Proxy 與瓶頸診斷只負責提出候選；不得假造「預測收益」作正式 PPA、改變物理成本或給某個 Action 額外的人工 Reward。
6. **本次先修改程式並進行小規模驗證，不要直接啟動全模型、多 Seed、長時間的正式實驗。** 長跑必須可由使用者之後明確觸發。

## 1. 已確認的程式現況與問題

以下依目前提供的 `code.zip` 靜態程式審查整理。程式版本不同時須重新比對，不得直接套用行號或假定舊問題已消失。

| 優先級 | 現況／證據 | 導致的問題 | 必要修正 |
|---|---|---|---|
| P0 | `hardware.py` 的 Gemini 固定 2×2 獨立 Core、每顆 64 PE、4×2 MiB Core GLB；`gemini_network.py` 以 Core 當網路節點 | 不符合使用者 v0.2 的 16 PE／die、共享 L2、無實體 Core | 建新 Profile、PE 資源所有權與路由／排程／緩衝服務，獨立計算新硬體 PPA |
| P0 | `rl_actions.py` A9 只生成排序相鄰的硬體模板；`rl_search.py` GUI04 `horizon=4` 每 4 步重設 | 若 Seed 只有 1／2／4 Chiplet，部分 8／16 Chiplet 設計無法在單一 Episode 抵達 | 允許單步跨任意合法規模與幾何布局，提供完整重 Mapping／必要 Group 改動 |
| P0 | `fusion_planner.py:189–195` 的局部 DP 明定 `Fixed Part/CG/FD` | DF 僅帶著非融合 Mapping 測試 Tile／Cache，漏掉最佳 DF + Partition／PE 配置 | 局部有界搜尋同時調整 Fusion、Part、PE allocation、Placement、Tile、Cache；必要時 FD |
| P0 | `auto_dse.py` 首個可執行 Seed `bootstrap[0]` 作為初態，預設只追求 3 個架構種子 | 初始搜索偏斜，15 個模板不等於有完整 PPA 覆蓋 | 依計費預算做多規模 Seed，完成 Seed 保存並可輪流重啟，選用最佳合法起點或分層多起點 |
| P1 | `planner.py` 受連續 Layer、Group 層數、Beam Width 與單一最佳 Partition 約束 | Tangram-style DP 起點狹窄，不能保證全域最佳 | 保留原始 Seed，增加 P-only／K-only、Spatial／Temporal 與切分差異性，完整評估後定排序 |
| P1 | `depth_first.py` 的 Stack 需連續、單出口且與一個 Layer Group 完全重合 | 有些有用的複合 Fusion 無法直接提出；部分限制屬 DAG 正確性而不可移除 | 分離正確性硬限制與表示法限制；讓 Group 調整和 Fusion 成一個合法交易，不刪除 Residual 邊 |
| P1 | `rl_actions.py` 的 C9 會對 Temporal Group 產生多層 A4 分配；A4 要求同時資源池 | 某些本來合法的 Temporal 分組改動被前置條件拒絕 | 以合法的 Group/PE 資源重配交易更新，補 Temporal 回歸測試 |
| P1 | `communication.py` 允許同 Group 的非 DF Producer／Consumer 直接交換資料 | 無 DF 不等於必定經 DRAM；DF 可能增加重算、Tile 和 SRAM 負擔 | 同 Mapping 下配對評估 DF on/off，明列 DRAM／NoC／SRAM／MAC／Unit 差值 |
| P1 | `rl_search.py` 是零初始化線性 Actor–Critic，候選在 Shortlist 內 Softmax 抽樣 | 只有少量實體 PPA 查詢時，Policy 很難真正學到瓶頸策略 | 顯式瓶頸 State／Candidate Features、保留多來源探索、足夠牆鐘時間與 Learning／Coverage 診斷 |
| P1 | `gui_request.py` 標準設定為 480 s、RL query ceiling 48；時間已包含種子／報告 | 大模型可能 Seed 尚未完成就接近時間上限；48 只是上限不是保證實跑量 | 標準每模型端到端牆鐘上限提高到 1800 s，動態分配各階段，真實計費與可恢復 |

**判讀限制：** 「最後 Best Solution 沒有 DF」只能說明當次**已驗證候選**的勝出情形，不能證明所有合法 Fusion 都較差。正式報告必須分別顯示「未提出、合法性拒絕、Proxy 裁剪、未入 Shortlist、未被 Policy 選中、已完整評估但落敗」。

## 2. 新硬體 Profile 的必要契約

新增例如 `chiplet_single_pe_array_v0_2`；舊 `gemini_2x2_core_v1` 不可改名重用。**v0.2 是新硬體設計基準，不是舊 Gemini 的參數微調。**

### 2.1 Compute Chiplet

| 類別 | 固定值／需求 | 必須實作的成本與限制 |
|---|---|---|
| 實體運算階層 | 1 Compute die → **16 PE**；不含 4 個實體 Core | 每 PE 可作排程分配的運算槽，但名稱與實體成本不得再叫 4 Core |
| 每 PE 運算 | 16 lanes × 每 lane 16 scalar MAC = **256 MAC/cycle／PE** | 16 PE 合計 **4096 MAC/cycle／die**；1 GHz 下 4.096 TMAC/s、8.192 TOPS 峰值。須受 bandwidth／stall 限制 |
| 精度 | INT8 activation／weight、INT24 psum | 規定 rounding／saturation／requant 和 3 B packed 或 4 B aligned 的實際成本 |
| 每 PE L1 | WL1=64 KiB、AL1=16 KiB、OL1=8 KiB **每槽**，兩個 A/B 槽 | 每 PE 176 KiB；16 PE 合計 **2.75 MiB**。容量、雙緩衝、refill、bank/port、活躍區域都需計費 |
| 晶粒共享 L2 | WL2=512 KiB、AL2=256 KiB、OL2=256 KiB，**兩槽總容量** | 總計 **1 MiB／die**，不是再乘 2。是本版 Global Buffer 角色的唯一共享容量帳本 |
| 額外 UB／GLB | **不另配置舊版 8 MiB UB** | 不得隱藏免費重用快取；主要資料 SRAM 合計 **3.75 MiB／die**，未含 Register／Queue／FIFO |
| 帶寬研究假設 | L1 64 GB/s／PE 合併讀寫；共享 L2 64 GB/s／die 合併讀寫 | 必須與 PE、DMA、Vector Unit 同時受仲裁；16×64 GB/s 不是共享 L2 可任意提供的頻寬 |
| Vector Unit | 每 die **1 個**獨立 Unit；暫採 16 INT32 lanes @1 GHz | ReLU、Add、Max／Pool、Reduction、Requant 各自有執行與搬移成本；不可再把 VPU 當 16 份免費 PE 元件 |
| Control／DMA | 各 1 個邏輯單位／die；DMA 16 GB/s 合併服務上限 | 明示 Descriptor、有限 Queue、L2 staging、依賴／完成事件 |
| 時脈 | 1 GHz 分析研究目標；0.5 GHz 可作敏感度 | 不可宣稱 timing signoff 或實際可達峰值 |

### 2.2 片內 NoC 與封裝 NoP／IO

1. **片內拓樸仍未經使用者最後確認**。v0.2 的 4×4 是 PE 排布，不自動等於 4×4 Mesh。請設計可替換的 `on_die_topology` 契約；如為讓初版可執行而先使用 `pe_mesh_4x4`，必須標為**暫行研究假設**並在 Output 顯示路由、PE-to-L2 Gateway 與每條流量。不能悄悄切回 Ring／Multi-ring。
2. 片內每方向每條 Link 暫採 **16 GB/s**；含有限 Port、Gateway、router arbitration 和流量。共享 L2 64 GB/s 不能穿過只具 16 GB/s 的單一入口並當作零延遲。
3. 封裝相鄰 Compute／IO 使用**每對鄰居一條 full-duplex D2D Link**的 v0.2 A 簡化方案；每方向 **12.5 GB/s**。四方向預留最多 4 個 D2D Port／die，未接線 Port 的面積／漏電仍須明定。B 雙鏈路方案是未來獨立消融組，不能免費加倍頻寬。
4. Compute Chiplet 不放 DRAM controller／PHY。**每顆 IO Chiplet**具備一組邏輯 DRAM controller／PHY、1 個基準接入 router（研究假設）、DRAM 可見容量 **512 MiB**、有效服務 **8.192 GB/s**；所有 IO 入口共享所屬 controller Ledger。
5. R×C Compute 布局：左右每列各一顆 IO，**N_IO=2R**；由此得到 IO、DRAM、Total Area 和 Aggregate Bandwidth，不可只增加 Compute 數而省略 IO 成本。IO-IO 垂直相鄰是否接線依已選封裝模板明定，路由與端口必須一致。
6. NoP／DMA／L2／DRAM 服務帳本分離、串聯瓶頸取最低可用通路服務；真實換路、MultiCast／Halo／Reduction／Data Valid／Residual lifetime 均需守恆。路徑內中繼節點只轉送 NoP 時不可免費改讀自身 L2。
7. INT24 Psum 的來源、傳送格式、O 寫回與 INT8 Activation 之間需要顯式 Requantization；不可認為下一層可直接拿 INT24 當 INT8。
8. 面積／能量模型把 **量測或論文 Anchor、推導值 D、研究假設 M、尚待定 T** 分清楚。現有 12 nm／16 nm、Macro 假設不一致時，採單一版本化估算表或敏感度，不得直接聲稱物理量測。

### 2.3 取代 Core Mapping 的資源語意

- 物理資源以 `compute:<die>/pe:<index>`（16 個可核對 PE）與 die-level L2／VPU／DMA／NoC 表示；在程式中新增 `compute_slots`／`pe_allocations` 抽象。可保留舊欄位作歷史資料解析，但**新 Profile 不得計入 4 套 Core GLB、Router、CPU 或 PE Array**。
- 每層選擇 PE 子集與 B/K/H/W 輸出 Partition，Partition 的 shard 數必須等於實際 PE 配額；Spatial Group 同時使用的 PE 子集不能重疊，Temporal Group 可依時序重用。
- PE 路由與 Data Ownership 必須影響流量，不能把同一 Chiplet 的所有 PE 合併成零成本互連。分給 Producer／Consumer 的 PE 是否相鄰、資料從 L1 經 NoC 回 L2 或有有價 FIFO，都要由已實作通路決定。
- Fusion 的中間資料先以**容量與頻寬受限的 L1/L2 留存**建模；如果未設計、未計 FIFO／仲裁，就不能加入免費 PE→PE 或 PE→VPU bypass。
- 分別計算 DF on/off 的 `executed_macs`、`recompute_macs`、`dram_bytes`、`on_die_noc_bytes/hops`、`l1_l2_service_bytes`、`peak_live_bytes`、`unit_count`、排程時間與 PPA。

## 3. 目標執行流程

```text
GUI04 DNN＋PPA constraints＋Preference（Batch=1、Seed=7、Auto budget）
    ↓
模型 FX／ShapeProp → 無損 DAG（含 Add／Residual、Tensor shapes、data types）
    ↓
合法 Compute Chiplet count=1/2/4/8/16＋矩形布局＋IO/NoP 模板
    ↓
Tangram-style bounded DP/beam 提供多個可追蹤 Seed
    ↓  完整編譯＋容量＋通訊＋排程＋PPA 驗證
多起點 Archive＋Seed coverage
    ↓
每個 RL Step：當前狀態及完整 Evaluator diagnostics
    ↓
瓶頸辨識 → 候選動作（A／C）＋局部聯合 DP＋通用探索
    ↓
合法性／去重／多樣性 Shortlist → Actor-Critic 選一個 ActionPlan
    ↓
一次 Transaction → 完整 PPA → Physical Difference Reward
    ↓
Policy／Best-feasible Archive／Checkpoint 更新；直到預算／終止
    ↓
報告：最佳硬體、PE Mapping、Fusion、Traffic、PPA 與搜尋覆蓋
```

## 4. Bottleneck Aware 系統的定義與證據

**瓶頸不是單層 MAC 數量大，也不是任何高流量都必然在 Critical Path。** 必須從 Evaluator 真正的 Resource Calendar、流量、佇列和路徑計算出來；若證據不足，標註 `unknown`，仍允許通用探索。

| 瓶頸類別 | 建議診斷訊號 | 優先生成的候選（僅引導，不是硬遮罩） |
|---|---|---|
| Compute bottleneck | Critical-path stage 服務時間、PE busy cycles、計算等待、負載不均／可分割性 | A2、A4、C1、C2；或保留現有資源試重新 Partition |
| On-die NoC／NoP | Link utilization、queue wait、flow bytes、source/destination、time windows、inter-chiplet hops | A5、A6、C4、C5、C9；視需要 A9／C2 變更布局 |
| DRAM／DMA bottleneck | 每 IO DRAM 讀寫與排隊、DMA 壅塞、反覆 reload、外部 materialization、Controller utilization | A8、C5、C6、A10；可考慮不同 IO 布局／增加資源 |
| SRAM capacity／reuse | L1/L2 peak-live、spill、weight/activation reuse、cache lifetime、bank conflict、stall | A2、A3、A7、C6、C7、C8；必要時減小 Fusion Depth |
| Pipeline imbalance | 各 Group／Stage 延遲、利用率、Dependency wait、Resource idle | A4、A10、C1、C3、C9 |
| DF opportunity | Producer→Consumer 中間資料量、是否跨 Group／DRAM、閉合 DAG、容量、重算開銷 | A1、C6、A3、A7；先做合法子圖與 tile＋mapping 的耦合提案 |
| No clear bottleneck／局部停滯 | Evidence 缺失、連續無改善、候選重複或已探索區域狹窄 | 維持 Atomic Generic、跨架構跳躍、重新 Seed、多目標 Exploration |

### 4.1 輸出機器可讀診斷

每次已完成 PPA 應輸出類似資料（欄位名稱可依既有 schema 調整，**數值必須由 Evaluator 真算**）：

```json
{
  "diagnostics_version": "bottleneck_v1",
  "critical_path": ["layer_id/stage_id"],
  "layers": [{"layer_id": "...", "compute_busy_s": null, "resource_wait_s": null,
              "communication_wait_s": null, "criticality": null, "pe_utilization": null,
              "slack_s": null}],
  "network": [{"link_id": "...", "time_window": [0.0, 0.0],
               "bytes": null, "queue_wait_s": null, "utilization": null}],
  "memory": [{"pool_id": "...", "capacity_bytes": null, "peak_live_bytes": null,
              "spill_bytes": null, "port_wait_s": null}],
  "fusion": [{"layer_ids": [], "depth": 1, "tile_hw": null,
              "recompute_macs": null, "extra_cache_copy_bytes": null}],
  "evidence_quality": "complete_or_partial_or_unknown"
}
```

上面 `null` 代表示意欄位，不是可接受的完整實驗輸出。真實使用時應有量測值或明確「此模型不支援」標記。注意不同等待時間可能重疊，Latency breakdown 不可重複加總。

### 4.2 決策方法

1. **診斷器**對 Compute／Network／DRAM／SRAM／Pipeline 等多種瓶頸給出解釋與可信度；一個狀態允許同時有多種瓶頸。
2. **候選生成器**依診斷擴充相關 C 類動作，但永遠保留一定配額的無偏 Generic Atomic、Architecture Jump 和 Fusion 探索。診斷只引導提案與 Candidate Features，不給 Actor 硬性類別命令。
3. **Policy**在同一個合法候選池中評分原子與複合 ActionPlan；每一步抽樣／選擇**一個**。所選複合動作的內部多項 Edit 在一份 Shadow State 中原子提交，最後一次驗證與完整 PPA。
4. **學習**依固定 PPA Preference／Constraint，使用物理成本差值更新 Policy。保留劣解的合法探索能力、最佳可行全域 Archive 與每架構 Archive；不要未經證據把所有劣解都拒絕。
5. 若要新增「先分類瓶頸、再挑動作家族」的分層策略，也必須維持 Generic fallback、行為機率記錄與 Random／Greedy 消融組，不能把手寫 Rule 改名為 RL 成果。

## 5. Action Space 與複合交易的完成標準

### 5.1 原子 A1–A10 的遷移

| 動作 | 新硬體的明確語意 |
|---|---|
| A1 | 建立、移動邊界、拆分合法的 DF Fusion Stack；必須保留 DAG／Residual 的所有依賴 |
| A2 | 對一層調整 B/K/H/W Partition；Batch=1 時 B 只能為 1；不開放未計 Partial-sum Reduction 的輸入 Channel Partition |
| A3 | 修改 DF Sink H/W Tile，必要時上游 Tile 由正確依賴編譯器反推 |
| A4 | 在合法 Group 中增加／減少／轉移 PE 配額，同步產生合法整數 Partition |
| A5 | PE 子集的 Layer Placement／順序調整；不偷偷改配額 |
| A6 | Spatial Group 內跨 Layer、等量 PE 集合交換 |
| A7 | Overlap 策略：recompute、horizontal cache、full cache；要計 Cache lifetime 和 copy 開銷 |
| A8 | 合法 Tensor／Weight 的 IO DRAM 配置及 interleave；外部 Materialization 必須付成本 |
| A9 | **任一合法 Architecture／Chiplet Count／Layout 的單步切換**，伴隨完整 Mapping 遷移；不能只選相鄰的第 ±1 模板 |
| A10 | Topological Pipeline Group 切分／合併／模式改動；Batch=1 下 Microbatch 固定 1，無需假裝它是可調參數 |

`A11` 僅是 A9 的 Import Alias，沒有獨立 Actor Action Class。

### 5.2 複合 C1–C9 的必要語意

| 動作 | 完整交易 | 瓶頸意圖與檢查 |
|---|---|---|
| C1 | 重新分配 PE＋重算受影響 Layer Partition／Placement | Compute Critical Stage；不可憑空產生 PE |
| C2 | 增加 Compute Chiplet、同步改完整 PE Mapping／Partition／DRAM 指派與必要 Group | 受算力限制；需同步增加合法 IO／NoP／Area／Power 成本 |
| C3 | 減少 Compute Chiplet、完整遷出 Layer／Tensor、改 Group／DRAM | 利用率低或面積／功耗限制；不可保留指向已刪除的資源 |
| C4 | 同時改 Producer／Consumer 的 Partition 與對應 Flow 形狀 | 處理 P-only／K-only 等相依通訊；更新所有 Branch Consumer |
| C5 | Placement／IO Entry／Weight 或 Tensor DRAM Assignment 協同改動 | Net/DRAM Hotspot；需驗證鏈路與 Controller 的實際 Time Window |
| C6 | **Fusion Group＋Depth＋Partition＋PE Placement／Quota＋Tile＋Cache** 聯合候選 | 主要新增能力；必須容許 Group Split／Merge 與合法 DAG；只用局部 DP 提案，完整全域 PPA 作決勝 |
| C7 | DF Tile 縮小＋Recompute／Cache 策略 | 容量壓力與額外重算的取捨 |
| C8 | DF Tile 加大／調整＋Overlap Cache | 改善資料重用，但需付緩衝存活與 Port 競爭 |
| C9 | Layer Group 邊界／模式＋PE Resource Allocation＋Partition | 修復 Temporal／Spatial 切分時的交易前置條件，避免合法方案被錯誤拒絕 |

`C10` 目前聲明為不支援的 Communication-aware Local Partition DP。若開發過程要啟用，須另有明確 Operator、合法性證明、通訊成本、測試與報告；不要顯示成已完成。

### 5.3 實作 C6 的具體要求

- 對合法、閉合的 2～N 層 Window，建立有限候選集：`{group boundary/mode} × {B,K,H,W partition} × {PE allocation/placement} × {fusion depth} × {tile H/W} × {overlap/cache}`；DRAM Placement 可分階段加入，但不能永久固定且宣稱全域聯合最佳。
- 使用 Capacity、Topological Dependency、PE Resource、SRAM lifetime、Network Path、Recompute MAC 作 Hard Validity。保留 Pareto／Beam 剪枝，但需記錄剪掉的候選、原因和多樣性覆蓋。
- 同一 Layer Window 應提供**配對的 DF on/off 候選**：如果兩者跨 Group 的 DRAM 成本不同，需明列，不能把原本就能 Local Forward 的非 DF 版本錯算成 DRAM Round Trip。
- 允許多步重構：完整複合交易能直接跨越單一步「中間狀態不合法」的問題，但整個候選最後必須合法，不允許藉交易規避資源成本。
- 代理模型不得替代全域 PPA；必須能用 `selected/attempted/full_evaluated/best_archive` 的資料驗證 DF 到底有沒有真的被試。

## 6. Tangram Seed、探索可達性與 RL 狀態

1. 保留原 `tangram_style_adapter_v1` 以便回放；新 Profile 另有版本化 Seed Schema。Seed 是 `MappingPlan`，包含 Group（Spatial／Temporal）、PE Allocation、B/K/H/W Partition、IO Memory、Microbatch=1，通常起始 `fusion_stacks=[]`；不能只儲存估算成本。
2. 以完整 PPA 驗證可執行 Seed；對 Chiplet 規模 1/2/4/8/16 建立覆蓋計畫，再對每個規模挑幾個不同布局／Mapping。**時間不足時記錄 `not_evaluated_due_to_budget`，不能聲稱全架構已搜尋。**
3. 不應只取第一個合法 Seed 作為唯一的長期探索起點。使用最好的已完整評估合法方案＋分規模多起點輪流啟動；Archive 保留所有已驗證 Seed，即使 RL 不曾走到它。
4. A9 可以在**一個 Step**提出跨 1→16 等任意合法架構變更；配合完整 PE／IO／Group 重建及容量／PPA 驗證。新增用 4-Step Horizon 仍可到達全部 5 種規模的測試。
5. 取消將 Horizon=4 固定等同優點的假設。對新實驗可使用**版本化 8～16 Step Horizon（暫定）**、受控重啟與停滯恢復；實際值應測量並記錄，不能藉此改寫舊實驗的行為。
6. RL State 應納入完整 Global PPA、PE 利用率、Compute Criticality、Network／Memory Queue、Capacity Pressure、Group／Fusion 摘要，以及 Episode／剩餘時間等可重現特徵。Candidate Embedding 需含交易範圍、目標資源、影響 Layers、家族、診斷關聯和可核驗的 Proxy Cost；不能依候選陣列索引或隨機 ID 學習。
7. 保留原本確切 Behavior Probability、Random Seed、Policy Weight、Checkpoint 資料；最好把同一候選在不同隨機 Seed 下的探索路徑和更新次數列出，區分 Random Search 與真的學習收益。

## 7. 搜尋時間、成本與停止條件

**新版 GUI04 標準模式**每一個 DNN 模型的**端到端搜尋上限 1,800 秒（30 分鐘）**，包含 Tangram Seed、RL、局部 DP、完整 PPA、必要報告輸出與保留。這不是保證一定會用滿，也不是保證完成某個固定 Evaluator Query 數。

建議先採下列可調的內部研究配置；應依近期每次完整 Evaluator 實測成本動態調整，不把它們寫成使用者輸入：

| 階段 | 參考上限／保護 | 說明 |
|---|---|---|
| Architecture Proxy／Seed | 目標 ≤20% Wall Budget（約 360 s） | 要有 1/2/4/8/16 多規模覆蓋意識；無法全跑要記錄實際覆蓋 |
| RL＋Bounded Local DP＋PPA | 保留主要時間，目標 ≥70%（約 1260 s） | 動態估算剩餘完整查詢次數，避免全部時間消耗在初始化 |
| 最後報告與清理 | 預留約 5～10%（90～180 s） | 原子儲存最後已驗證的 Archive；超時保留 best-so-far |

- `budget_mode=Auto` 同時有**Wall Ceiling 與 Query Ceiling**；Query Ceiling 可提高至合理上限（例如研究設定 128），但受 1,800 s Wall Ceiling 強制約束。`max_steps`、Shortlist、DP Window、DP Timeout 應依資料量動態分配且列入版本化有效設定。
- 每次昂貴求值前檢查 `remaining_wall_time`，當時間不足一個完整 Oracle 估算成本及報告保留時間，停止新試探並寫回已完成的最佳可行解；不要從已超時或部分 trace 製造結果。
- Per-evaluation Timeout 必須不超過實際剩餘時間；失敗、Hard Rejection、Cache Hit 與完整評估查詢的計數分離。
- 每次已完成 Step 存 Checkpoint（含 RNG、Policy、已評估 State Hash、Oracle Fingerprint、已用時間、Bootstrap、Best-feasible Archive）；`resume` 不得變更 Code／Model／Hardware／Objective 版本後仍默默重用 PPA。
- GUI 僅顯示「標準／快速／深入」、「Batch=1」、「Seed（進階）」、「預算 Auto／手動（進階）」；不要暴露 Fusion Depth、Chiplet 數、Partition、Tile、Cache 等 DSE 內部調參給一般使用者。
- 多模型工作需分清 **1,800 秒／模型** 與總 Suite 時間；例如 3 模型最長可約 90 分鐘，而不是誤寫成全工作只要 30 分鐘。GUI 必須顯示每模型的剩餘時間與截斷狀態。

## 8. 驗證與實驗設計（先少量、具代表性）

**此階段不要一次執行完整 ResNet50／VGG16／ShuffleNet／全部偏好與多種 Seed 的笛卡兒積。** 優先通過小型測試後，才由使用者明確啟動長跑。

| 階段 | 工作負載 | 目的 | 次數建議 |
|---|---|---|---|
| T0 程式／物理正確性 | Toy 2～3 Layer Conv＋Pool、可形成 DF 的閉合鏈、含殘差 Add 的小 DAG | 驗證資料依賴、Tensor Coverage、PE ownership、L1/L2 容量、NoC、Reward、Fusion off/on，能設計小型 Exhaustive 對照 | 各 1 次，秒～分鐘級，非正式 PPA 結論 |
| T1 小型 E2E Smoke | **ResNet18**，Batch=1，Seed=7 | 驗證全模型、DAG／Layer Group、正常 Mapping＋至少一個合法 DF Candidate、報告欄位 | 1 個 Standard Profile，必要時縮時只做流程檢查 |
| T2 主要代表大型模型 | **ResNet50 v1.5**，Batch=1，Seed=7 | 大 DAG／Residual／多 Bottleneck、跨層資料留存、串接 PE／IO 與 30 分鐘 Timeout | **1 次** ≤30 分鐘／模型 |
| T3 另一種瓶頸形態 | **MobileNetV2**，Batch=1，Seed=7 | Depthwise／Pointwise／小工作單位、Bandwidth 與 Compute Utilization 對照 | **1 次** ≤30 分鐘／模型 |

首輪全模型只需 **ResNet18、ResNet50、MobileNetV2 三個**；Toy 是自動化正確性測試，不計為第四個大型模型。VGG16、ShuffleNetV2、更多 Seed、Preference Sweep、全部 15 架構全程各自跑滿，暫列下一階段，不在這輪自動執行。

### 8.1 必備的針對性測試

1. **硬體資源：** 1／2／4／8／16 Chiplet 合計 PE 數為 16×N，單 Die 計算峰值 4096 MAC/cycle，SRAM 3.75 MiB／die；N_IO=2R，沒有額外的 4 Core GLB 或 8 MiB UB，Area／Energy 隨資源守恆。
2. **映射與架構 A9：** 以 4-Step Horizon 從每個 Seed 直接生成合法 1→16 與 16→1 切換；查表 15 模板的 Coverage 不得因相鄰跳躍而不可達。B/K/H/W nonempty integer shards、PE 配額與資料依賴仍合法。
3. **複合交易：** C1～C9 每類至少有可構造的合法／非法測例；Temporal Group 的 C9 不再被不相關的 A4 前置條件錯誤拒絕；Transaction 失敗須整體 rollback。
4. **瓶頸解釋：** 人工注入 Compute Bound、NoP Congestion、DRAM Queue、SRAM Spill 的小型受控場景，檢查診斷證據、候選方向、Generic Fallback；「優先」不能等於「其他動作零機率」。
5. **DF 對照：** 同一硬體、同一負載、同一 Budget，成對比對 DF Off／On；至少檢查一個能省中間資料、一個有 Halo／Recompute 負擔的例子。不能宣稱 DF 必定更快。
6. **會計一致：** Full PPA、Proxy、Cache Hit、Rejected、Timeout、Archive Export、報告重播分別計數；截斷時無部分估計冒充完成方案。
7. **歷史回歸：** 舊 GUI v1／v2 的 Request 解析、既有 Fixture PPA、Objective／State Hash、Checkpoint 重播和先前正式報告能原樣保留；對於新 Profile 的結果，須使用新來源與硬體版本重算，不能直接貼上舊 PPA。

### 8.2 搜尋效益比較

新硬體先做 `Fusion Off`、`Fusion On` 的 paired ablation。確認程式正確後，在有限樣本條件下補同一物理 Evaluator、同一 Full-Query／Wall Budget 的 `Random`、`Greedy`、`RL atomic only`、`RL atomic + composite bottleneck aware` 對照。單一 Seed 的 RL 勝出不構成統計保證；正式論文階段再擴展 Seed=7/8/9 等重複組。未實際執行的對照標 `not_run`。

## 9. 報告與可重現性

每次實驗資料夾必須包含下列機器可讀證據（檔名可沿用既有格式）：

- `requested_ui.json`、`effective_config.json`、`hardware_profile.json`：Hardware/NoC/IO/precision／未定研究假設的**實際值與版本**。
- `source_identity.json`：程式 Commit 或 Hash、模型來源／Shape／Batch、RapidChiplet／Evaluator 版本、資料精度、依賴版本。
- `architecture_coverage.json`、`seed_attempts.json`：合法候選數、被 Proxy 排除、每規模 Seed、完整 PPA、未評估原因。
- `joint_search.json`、`checkpoint.json`：每步選的是 A 或 C、完整 Ordered Edits、Candidate Shortlist 及 Reject Reasons、Behavior Probability、Reward、Policy Update、Wall／Query Accounting。
- `bottleneck_trace.json`：每次已驗證 State 的 Critical Path、Resource Utilization／Queue Wait／Network Hotspots／SRAM Pressure，哪些候選因它被提案。
- `fusion_coverage.json`：Fusion Depth 2/3/4/… 的「合法、Proxy 留下、進入 Shortlist、被選中、完整評估、是否改善」次數，以及最深成功編譯和最高實評深度。
- `verified_archive.json`、`recommendation.json`：Best So Far／Strict Feasibility、Latency/Area/Power/Energy、每層 PE 分配、On-die/NoP/DRAM Traffic、Recompute、Peak Buffer 與模型解讀限制。

分別保存**舊硬體模板的歷史報告**與**新 Profile 的結果**。比較時先說明硬體、SRAM、IO、Bandwidth、Clock 不同：新 PPA 是新的分析估算，不能把差異全歸因於 RL 或 DF。固定以相同硬體和受控 DSE Budget 作 Fusion／Algorithm 配對比較。

## 10. Codex 實作順序與交付驗收

**Phase 0：盤點與鎖版**

- 讀取 v0.2 硬體規格、`bottleneck-aware.docx` 的原子／複合動作期望、現有 `code.zip` 與測試；確認 GUI v1、GUI04 v2、舊 Gemini／homogeneous profile 與新 profile 的共存方式。
- 先新增測試鎖定歷史 Golden 輸入輸出。不要改寫已交付的結果、未受影響的 Cache 或外部 RapidChiplet 源碼。

**Phase 1：新硬體契約與可執行物理模型**

- 新增 Versioned HardwareSpec、PE Array、分槽 L1／共享分區 L2、VPU、DMA、Control、IO／DRAM、NoC／NoP、成本明細。
- 調整 architecture／mapping／compiler／communication／schedule／capacity／evaluator／layout 和對應 State/Action。任何抽象與物理容量不一致必須明確報錯。
- 跑 Toy／物理守恆測試，**不啟動完整 ResNet50 長跑**。

**Phase 2：Bottleneck Aware Candidate RL**

- 補 Critical-path、PE/Network/Memory stall、SRAM Pressure 診斷器、可查詢的 Bottleneck Trace。
- 修正 A9 全架構跳躍、C9 Temporal Transaction、Seed Coverage／Multi-start、RL State／Candidate Features、Atomic/Composite 的共同 Shortlist 與 Generic 保留配額。
- 保留原 Reward 定義、完整成本計算、Selection Probability 與 Best Archive。完成單元／小型 E2E 測試。

**Phase 3：Fusion 與 Mapping 聯合搜尋**

- 完成受容量約束的 C6 局部聯合 DP 或等價候選產生器；加入 PE Allocation／Partition 與 Tile／Cache 耦合、跨 DAG 完整合法性檢查。
- 做 DF paired counterfactual、失敗原因／覆蓋報告、Fusion Depth 的實際完整評估證據。

**Phase 4：30 分鐘 Profile 與代表性驗證**

- 設定 Standard 每模型 End-to-end 1,800 秒 Hard Ceiling、Resume／Checkpoint／Fair Oracle Accounting，並完成 Stop/Timeout/Report-Reserve 測試。
- 先跑 Toy、ResNet18；再只各跑一次 ResNet50 v1.5、MobileNetV2，存所有有效設定及最佳可行解；若一輪完成過慢或不穩，修正模型後才決定正式實驗規模。

### 驗收定義

- [ ] 新 Profile 有 **16 PE／Compute、1 MiB 共享 L2、2.75 MiB L1、無 4 實體 Core、無額外 8 MiB UB**；每個資源與通訊流都有有效容量、頻寬及成本。
- [ ] 1/2/4/8/16 Compute 與合法 R×C／IO 布局有正確面積、DRAM、NoP、路由和可達性。
- [ ] 每個 RL Step 可在 A／C 候選中選一個合法交易；診斷能解釋動作來源，保留跨家族探索，不是硬性 Rule-based Selector。
- [ ] A9 不再被鄰接索引與 Horizon 阻斷，C9 Temporal 合法場景可執行，C6 真正可以共同變更 Fusion／PE Mapping／Partition／Tile／Cache。
- [ ] Batch=1 下 Microbatch 唯一值 1，不把它宣稱成有實際探索自由度。
- [ ] Standard 最大 1,800 秒／模型；部分或超時 Evaluator 結果不得列入 Best Archive。
- [ ] ResNet50 v1.5 等代表性模型**只是納入驗證規畫**；執行前須先完成小型測試與使用者同意的長跑啟動。
- [ ] 舊設定、舊 PPA 回放、版本、Checkpoint、正式報告與新 Profile 完全隔離，可在相同來源與參數下重現。
- [ ] Codex 最後交付：實際修改檔案清單、技術設計說明、跑過的測試及耗時、尚未跑的大型實驗、可重現指令、未實作能力與所有 M／T 假設。

## 11. 實作證據來源與界線

- **硬體唯一主規格：** `Chiplet_Hardware_Spec_v0.2_reviewed.md`。其本來是 v0.2 研究建議稿；本次使用者明確要求採用其中的硬體組織，但內文明列的 M／T 仍需在程式與報告保持來源標記。
- **決策機制參考：** `bottleneck-aware.docx`，包含「每 Step 選一個 Atomic 或 Composite」、以 Compute／NoC／DRAM／Utilization 等瓶頸引導候選，但不可把引導變成硬性排他規則。
- **現有程式基線：** `code.zip`，關鍵檔案為 `hybrid_gui.py`、`gui_request.py`、`auto_dse.py`、`tangram_seed.py`、`planner.py`、`rl_schema.py`、`rl_actions.py`、`auto_proposals.py`、`fusion_planner.py`、`depth_first.py`、`mapping.py`、`communication.py`、`gemini_network.py`、`scheduler.py`、`evaluator.py`、`rl_search.py`。
- **方法學界線：** Tangram-style Adapter 不等於原始 Tangram 執行檔；局部 DF DP 不等於已找到最佳聯合映射；RapidChiplet + 自訂分析模型輸出是未校準 PPA 估算，不是晶片實測或 Signoff。

