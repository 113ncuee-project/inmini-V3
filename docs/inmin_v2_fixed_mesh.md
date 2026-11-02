# INMIN V2：固定 chiplet、純 mesh 與軟體優化

更新日期：2026-10-14（Asia/Taipei）。本次修改同步到開發主目錄與 `output/github_inmini_v2` 發佈副本。

## 使用者輸入與系統輸出

使用者提供模型、batch、Energy／Area／Latency 偏好及可選 PPA 限制；GUI 不再要求選 PE 數、SRAM 容量、NoC 拓樸、雙緩衝或 chiplet 數量。系統對 **1／2／4／8／16 顆相同 compute chiplet** 分別搜尋 mapping，再用相同單位的目標比較，推薦顆數與每個模型的部署。這是有限候選與搜尋預算內的建議，不是全域最佳證明。

interposer 上的 compute chiplet 直接構成矩形 mesh，採固定 XY routing（先 X、後 Y）；沒有獨立 I/O die、compute leaf／I/O-cluster 或實體 ring。每顆 compute chiplet 內部也固定採 4×4 PE mesh。mesh 形狀由顆數決定：1×1、1×2、2×2、2×4、4×4。

每顆 compute chiplet 都包含相同的四個 D2D compass ports、router／crossbar 與一個記憶體控制器；本地連接一顆規格相同的 memory die。未接線的邊界 D2D port 仍支付完整面積與漏電。memory die 是外部記憶體資源，與 compute chiplet 分別計數；「推薦 N 顆 chiplet」指 N 顆 compute chiplet，封裝內另有 N 顆 memory die。

## 固定規格 `homogeneous_mesh_4x4_v1`

| 每顆 compute chiplet | 固定設定 | 來源／假設 |
|---|---|---|
| PE 陣列 | 4×4＝16 PE | INDM Table V 的 N_PE＝16；位置改成 mesh |
| 每 PE 計算單元 | 16 lanes × 16 scalar MAC | 16×256＝4096 MAC／cycle，對齊 INDM Table IV 每顆 4096 MAC；16×16 分解是本研究選定配置 |
| 數值格式 | INT8 activation／weight，INT24 partial sum | INDM Sec. V-A |
| compute clock | 500 MHz | 延續已採用的 NN-Baton 16 nm 參考成本條件；INDM 評估為 1 GHz，本版沒有宣稱複製其 8 TOPS／die |
| 每顆理論吞吐 | 2.048 TMAC/s＝4.096 TOPS | 2 ops／MAC 的 TOPS convention；與能量 op convention 分開 |
| mapping cores | 4 個，每個分到 4 PE | 本研究的軟體資源分組，L2／UB 共用；不是額外實體 chiplet |
| 每 PE、每 scratch slot 的 WL1／AL1／OL1 | 64／16／8 KiB | INDM Table V：L1_base＝8、比例 8:2:1 |
| 每 chiplet、每 scratch slot 的 WL2／AL2／OL2 | 64／16／8 KiB | INDM Eq. (2)、Table V 的 ratio_L2＝1 |
| scratch slots | 固定 2 個（雙緩衝） | L1／L2 陣列與周邊均付成本；UB 不翻倍 |
| shared unified buffer | 8 MiB | 本研究固定容量假設，沿用 V2 GUI 基準；Gemini 的 shared unified buffer 概念，不聲稱此數值是 INDM Table V |
| 片內 NoC | 4×4 PE mesh、8.5 GB/s／directed link | 68 Gb/s anchor 來自 INDM Table IV；mesh、L2 接入及 router 成本是本版模型 |
| interposer D2D | 四個方向、每方向 12.5 GB/s | 100 Gb/s anchor 來自 INDM Table IV；每 port 的全雙工 GRS macro 成本沿用 cost16 模型 |
| local DRAM bandwidth | 4.6875 GB/s＝37.5 Gb/s | INDM Table IV 的 1／4／16 顆對應 37.5／150／600 Gb/s，按顆數線性增加 |
| local memory capacity | 512 MiB／memory die | 本研究假設；16 顆時共 8 GiB，延續舊 V2 的總容量尺度 |
| integrated controller／router | 每顆相同，連同 PHY、crossbar、漏電計費 | 移除 I/O cluster 後的新架構假設，不是 INDM 原始實作；成本仍未經 RTL／實體設計校準 |

**4×4 指 PE 數量，不是整顆 chiplet 只有 16 個 scalar MAC。** 同一 compute die 的面積與資源在所有候選中相同；增加顆數會增加總 PE、SRAM、控制器、記憶體與漏電。舊版的「總 PE／SRAM 固定，再分成不同大小的 die」不再用於新版本的推薦。

| Compute chiplets | Mesh | 總 PE | 總 UB | 理論 TOPS | 總 DRAM GB/s |
|---|---|---|---|---|---|
| 1 | 1×1 | 16 | 8 MiB | 4.096 | 4.6875 |
| 2 | 1×2 | 32 | 16 MiB | 8.192 | 9.375 |
| 4 | 2×2 | 64 | 32 MiB | 16.384 | 18.75 |
| 8 | 2×4 | 128 | 64 MiB | 32.768 | 37.5 |
| 16 | 4×4 | 256 | 128 MiB | 65.536 | 75 |

Gemini Sec. III、Fig. 2 支持 mesh 與 shared-buffer 的硬體模板，但原論文仍有 I/O chiplets、多 core-side D2D interfaces 與架構共探索。本版採單一 router 聚合每顆 chiplet 的四個方向連線、將控制器放入相同 compute dies，是**本研究的簡化／改作**，不是直接重現 Gemini 或 INDM 的硬體。

## 保留的軟體優化

保留 whole-DAG communication-aware DP、RL 五個 Part／CoreGroup／DRAM placement operators、片內 loop order／tile 搜尋、內層 Tile／Fusion／Reuse DP，以及實際容量、排程與逐 link 競爭的 PPA 評估。增加顆數只是部署規模選擇；不會更改某一顆 die 的 PE、buffer 或互連資源。

傳輸在 compute-chiplet router 間中繼；中繼 die 只計 network service／energy，不憑空產生 UB read／write。multicast 的共同 directed edge 只搬一次 region；本地投遞與各 endpoint 的 SRAM 存取仍付成本。跨 group 的 DRAM materialization 與原有依賴繼續生效。`--collective ring` 若用於低階軟體實驗，代表 mesh 上的邏輯 forwarding chain，沒有增加任何實體 ring；正式 GUI 使用 multicast。

## 完整部署成果

每個模型／候選輸出：

- `hardware.json`：實際執行的硬體欄位。
- `deployment.json`：compute／IO／memory／全部 die 數、mesh 形狀、固定 profile 與資源描述。
- `package.json`：每個 die 的位置、尺寸、PHY ports、鄰接 link、bandwidth／energy。
- `mapping.json`：layer／core／Part、DRAM placement、dataflow／tile／fusion。
- `traffic_routes.json`：每個 tensor region 的 src／dst、XY path、bytes、依賴、start／finish、逐 link 與 energy 帳本。
- `link_traffic.csv`、`timeline.csv`：逐 link bytes、完整事件時間線。
- `layout.html`：可點 die、篩 layer、選 traffic 並高亮路徑的布局；`architecture.svg`／`die.svg`／`pe.svg` 是對應圖。

CLI 頂層 `recommendation.json` 提供顆數、狀態與選定資料夾。GUI `recommendation.json` 另提供各模型部署位置；原有 strict／soft constraints 與 closest fallback 繼續使用。布局保留實際分析模型幾何；它不是完成佈線的 interposer／RTL floorplan。

## 執行

開發主目錄的 GUI：

```powershell
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/hybrid_gui.py --port 8765 --out simplified_rapidchiplet/results/inmin_v2_mesh
```

預設 CLI 自動推薦顆數；快速範例含 RL 與內層 DP：

```powershell
.venv/Scripts/python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --model toy --batch 1 --preference balanced --fusion-tiles 2x2,4x4 --fusion-budget 2 --budget 3 --out simplified_rapidchiplet/results/mesh_demo
```

`--mode search --dies 4` 等只用於指定顆數的研究診斷；GUI 自動探索全組候選。PE／SRAM／prefetch／physical topology 的 JSON overrides 在正式入口會被拒絕。低階 `HardwareSpec` 與 `enumerate_legacy_architectures` 保留舊 INDM 成本／路由的重播與回歸測試；缺少 `package_topology` 的歷史 JSON 仍讀作 `indm_cluster`，不會靜默改成 mesh。

## 文獻與驗證

核對使用者提供的 INDM PDF 第 9、11 頁（Tables IV／V 與 Sec. V-A），及 Gemini PDF 第 3、4 頁（Sec. III、Fig. 2）。Gemini 作者版：[HPCA 2024 PDF](https://people.iiis.tsinghua.edu.cn/~gaomy/pubs/gemini.hpca24.pdf)；INDM：[IEEE 原文](https://ieeexplore.ieee.org/document/10318183)。詳細文獻成本與其界線仍見 `hybrid_cost16_sources.md`，本版對其中舊 cluster 拓樸的更新以本文件為準。

本次測試與搜尋紀錄保存在 `output/mesh_fixed_20261014/`。舊發佈基準與原始研究輸出是歷史證據，不作 mesh 新版的效能重跑結果。


## 2026-10-14 實際驗證結果

開發主目錄與 V2 發佈副本各完成 183 項完整回歸；最終輸出另通過 7 項固定 mesh 測試及真實瀏覽器 GUI 操作（自動 5 種顆數、推薦數字、layer／traffic 篩選、路徑高亮、0 JavaScript errors）。V2 副本獨立執行 Toy 的 1／2／4／8／16 顆 RL＋內層 DP 搜尋，全部可行。另以完整 ResNet-18 DAG、32×32 輸入、batch＝1、4 顆 chiplet 執行 traffic DP＋RL＋內層 DP，通過容量／排程檢查；延遲 2.0125 ms、能量 4.2877 mJ、總矽面積 76.764 mm²，均為分析估算。此數字不是 224×224 模型的效能基準。

詳細證據：發佈副本 `reports/2026-10-14/validation.json`、`toy_count_search/`、`resnet18_32_smoke/`；GUI 截圖與驗證紀錄也在同目錄。Toy 推荐 1 顆僅用於驗證推薦流程，不能套用到使用者的實際模型。
