# INMIN v0.2 實作與重現說明

本版新增獨立的 `chiplet_single_pe_array_v0_2` 分析 engine。每顆 Compute 有 16 PE、共享 W/A/O L2，沒有實體 Core。舊 `gemini_2x2_core_v1`、`homogeneous_mesh_4x4_v1`、GUI schema1/2 與歷史結果保留。新數值不能與舊硬體 PPA 混合解讀。

使用者要求的純文字／數字表格和可延長時間優先於附件的呈現與 1800 秒上限。一般 GUI standard 仍預設 1800 秒；本輪研究比較明記延長為每方法 3600 秒。這份文件是實作說明，完整模型結論待正式實驗及審計完成。

## 可核對的實體契約

|項目|實際模型|
|---|---|
|PE／die|16，每 PE 256 scalar MAC/cycle，合計 4096 MAC/cycle|
|時脈|MAC/VPU 1 GHz；支援 0.5 GHz 敏感度；非 timing signoff|
|L1／PE|W64/A16/O8 KiB 每槽，2槽；每 die 2.75 MiB|
|L2／die|W512/A256/O256 KiB，合計1 MiB，已含雙槽；量化參數從 A 分4 KiB|
|主要資料 SRAM|3.75 MiB/die；沒有額外 UB；register/queue/control另計|
|L1／L2|64 GB/s 每 PE／64 GB/s 每 die，各為合併讀寫上限|
|VPU／DMA|每 die 各1個；VPU16 INT32 lanes，DMA16 GB/s aggregate|
|片內網路|M：4×4 PE mesh，四corner L2 gateways，16 GB/s/方向/鏈路|
|封裝|15種1/2/4/8/16 Compute矩形，左右每列各1 IO；N_IO=2R|
|D2D|每鄰居對1條full-duplex，12.5 GB/s/方向；每die付四預留port成本|
|IO|每IO一個controller ledger、512 MiB可見DRAM、8.192 GB/s；IO垂直相鄰連線為M|
|精度|INT8 W/A、packed3B INT24 psum；支援aligned4B作另一次模型設定|

MAC tile 使用完整輸入通道；compiler 依 WL1/AL1/OL1 每槽容量切分。單輸出 receptive field 太大時明確拒絕，沒有尚未計價的 C-panel pipeline。MAC 的 OL1 留 INT24 psum；輸出經 L2 與共享 VPU requant 成 INT8，存 L2。非 MAC 算子只排單 die VPU 及 L2，不產生虛構 PE/L1 工作。

Depthwise 把獨立通道填16 output lanes，每lane只用一個input MAC位置，最高陣列利用率1/16；grouped/tail成本依實際kernel計算。模型FX只抽shape/DAG，不下載或使用權重，也未測量量化推論準確率。

## 執行、容量與成本

流程為精確 tile/DAG 編譯、通訊 cohort 拆分、逐資源排程、資料生命週期容量檢查、面積與能量核算。L1、共享 L2、DMA、NoC gateways/links、NoP switch/links、各 IO controller 是不同服務帳本；途經 Compute 的封裝轉送不讀它的 L2。INT24 寫回、requant、冷量化參數、額外 Halo／重算／cache copy 都有成本。

原位 direct consumer 也保留 producer OL2，直到真正讀完；寫入 DRAM 後原 OL2 依完成事件釋放，後續外存載回另付成本。讀取依 group/layer/tile/execution cohort 拆開，跨 group 不假設無限 staging。所有 W/A/O pool、L1 slots 與 DRAM resident tensor 都驗容量，溢位直接不可執行，不把它當免費 spill。

`energy_j` 是顯式 SRAM、L2、MAC、VPU、NoC、NoP、router、DRAM、idle 分項總和；平均 `power_w=energy_j/latency_s`。面積包含 Compute、IO 與明示的外部 DRAM silicon proxy，沒有聲稱封裝/實體DRAM器件已定案。

新 engine 使用 Python 顯式網路與資源 calendar，**未執行 native RapidChiplet**。Whole-flow reservation 同時保留必要通路及端點，對重疊程度保守；這不是 packet/VC cycle simulation。舊 native/backend 程式仍保留供歷史流程使用。

## RL 與聯合搜尋

新 DesignState schema2 使用24維state、180維candidate feature。Actor–Critic在同一shortlist中抽一個A或C交易，交易內所有edits在shadow state改完後統一驗證。Reward等於固定reference下、前後完整物理PPA的penalized cost差，不加瓶頸或Fusion獎金。Policy保留合法劣解探索與最佳可行archive。

A9 可一步切到任一合法架構；C9 允許合法Temporal資源重配；C1–C9都有正反交易測例。C6 同時改group/mode、PE quota/placement、partition、fusion depth、tile/cache；目前提案深度≤4。Critical-path/queue/memory證據只引導候選及features，generic atomic及architecture jumps仍保留配額。這個有界生成器不是全域joint optimum，也不是手寫規則直接決定最終action。

Tangram-style seed adapter 用prefix segmentation DP/beam提案，保留原integer-stripes baseline；Spatial/Temporal、K/P方向及IO策略具有差異。Proxy只排名/剪枝，完整PPA才進bootstrap。Seed最多用20%查詢、上限8次及20%時間，避免初始化吃完學習預算。完整seed及時間向每個方法計費，實際共用backend只執行一次。

## 預算、失敗與回放

Complete PPA、compiler reject、timeout、cache hit、artifact export各有帳本。Timeout是物理有效性未知，不產生部分PPA，不進best、不做policy update；同預算下暫排除該state，避免反覆超時。Compiler成功但排程超時仍記實際compile depth，不能寫成已完成PPA。

每步checkpoint含policy/RNG、current/best/archive、cache、短名及完整shortlist gzip hash、behavior probability、reward與完整ordered edits。Source/model/hardware/config必須一致才resume；OS file lock阻止重複工作。正式實驗另用不可修改的source snapshot，conductor每case前後核對125個來源檔hash。中斷後用相同參數重啟，已完成case不重跑。

## 重現指令（PowerShell，workspace根目錄）

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/test_single_array_acceptance.py --out output/new_acceptance

& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/single_array_dse.py --model toy --queries 32 --seconds 180 --out output/new_toy

& '.venv/Scripts/python.exe' -X utf8 output/inmin_v02_20261101/formal_v8/source_snapshot/scripts/run_single_array_research_suite.py --snapshot output/inmin_v02_20261101/formal_v8/source_snapshot --out output/inmin_v02_20261101/formal_v8/results --queries 128 --seconds 3600 --eval-timeout 300 --toy-queries 64 --toy-seconds 600

& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/audit_single_array_results.py --root output/inmin_v02_20261101/formal_v8
```

正式conductor目前正在執行；**不要同時再次啟動**。先看 `formal_v8/results/suite_status.json` 與 `docs/inmin_v02_progress.md`。若要獨立重現，使用新output目錄；已存在的完成結果不得覆寫。Acceptance driver從自己的位置找到workspace並配置temp，不依賴目前shell目錄。

## M／T 與尚未完成能力

|分類|值或限制|
|---|---|
|M topology|4×4 mesh、corner gateways、5-input router、IO垂直連線；不是使用者最後確認的物理布局|
|M queues/protocol|2VC×8flits×16B/input、1280B/router；DMA/IO各16×64B descriptors；payload256B/header16B、flit padding；DRAM固定50ns、router1cycle|
|M precision/VPU|INT24每MAC飽和、ties-to-even、INT8飽和；requant3cycles/element；共同scale Add每element1lane-op；數值準確率未驗證|
|M costs|單一16nm參考估算；MAC.024pJ/MAC的reported-op convention有來源歧義，2×能量敏感度尚未做；VPU/register/IO成本proxy；係數逐項見hardware_profile.json|
|M DRAM|每512MiB area5mm²、idle.005W/mm²；不是實際DDR器件面積或功耗|
|M SRAM|packed logical byte服務/能量、aggregate RW仲裁；物理bank-address、word-tail、byte-enable未校準|
|T|DDR器件/channel/refresh、PHY/pinout/package/timing signoff、SRAM macro timing、cycle-accurate VC deadlock proof|
|未實作|C10 communication-aware partition DP、內部C-panel、standalone BatchNorm；深度>4的提案覆蓋未聲稱|
|實驗限制|Seed7單次，無跨seed統計保證；搜尋on/off不取代固定mapping counterfactual；未評估候選不算落敗|

103項驗收與舊版回歸已在固定來源通過；結果見 `output/inmin_v02_20261101/acceptance_final_v8`。完整模型效益結論、固定mapping counterfactual與最終結果表仍須在正式計算完成後審計交付。
