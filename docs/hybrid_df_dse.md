# Communication-aware Tile / Fusion / Reuse DP

2026-10-11：依使用者明確授權實作，取代僅討論缺項的狀態。兩份 Gmail ZIP 共16張原照片已逐張讀取；分享對話 `6acb53c9-11c8-83e8-868f-29658de363fc` 的文字已讀取。照片為 DeFiNES 的 tile、overlap、fusion 空間；採用概念而非下載／執行其原始 evaluator。

## 已接進實際執行路徑

`hybrid_dse.py / hybrid_gui.py → 初始 traffic DP + 片內 dataflow → fusion_planner → depth_first → communication / ondie / scheduler / evaluator`。

CLI 與 GUI 預設啟用內層 DP。RL／Greedy／SA／Random 每個 mapping 提案均呼叫內層排程搜尋，以完整候選的 PPA 回饋外層。硬體仍由4/8/16 dies、ring/mesh外層候選選擇，RL維持Gemini OP1–OP5。此次未建立額外 RL scheduling action。

## 搜尋維度與表示

`MappingPlan.fusion_stacks` 保存每個融合群的 layers、sink tile H/W、overlap mode。Part 是 ownership 切分；DF tile 是融合群最終輸出的執行區域，兩者不等同。

- **Tile**：CLI可設定任意正整數H×W候選，預設8×8、16×16。
- **Fusion**：DP在拓樸順序上選擇連續、封閉、單出口子圖。內部tensor不得有外部consumer／模型輸出；完整residual分支可包含在子圖內。預設深度上限4，可設定至其他正整數。
- **Reuse**：`recompute`每sink tile重新計算重疊區；`horizontal_cache`同tile-row重用、跨row重算；`full_cache`跨row重用。每個tile內的共同分支需求都共享已算值，避免把DAG共同producer誤當成額外重算。
- **Mapping**：內層固定外層 Part／CG／FD。允許多core／多die；實際重用是否跨die仍由owner與路由決定，不使用免費遠端cache。

## 可執行 tile DAG

從sink輸出tile反向呼叫既有receptive-field推導，按各層的owner shard切分。精確矩形相減將已快取區域扣除，只為未計算區域建立WorkUnit。相同tensor可能有多次重算generation；consumer只能讀compiler指定的producer，不能在所有重疊owner中任選或重複計算coverage。

`execution_order / df_tile` 驅動tile-first的core順序、依賴與排程priority。支援Conv2d（含group/depthwise、stride/padding）、Add、ReLU、BN、Identity、Max/AvgPool。Flatten、Linear、AdaptiveAvgPool仍走原路徑，不默認為合法融合stack。Dilation沿用保守dense envelope。

## 成本與容量不是折扣

MAC帳本分為logical（原模型）、unique（真正需要的獨立輸出操作）、pruned（未被sink需要）、recompute（重複操作）、executed；`executed = unique + recompute`。實際unit的MAC決定運算時間及MAC能量，不將重算當成零成本。

快取位於已付面積／能量成本的UB。跨tile同core的reuse建立`df_cache_copy`事件，付UB讀寫、DMA／fabric時間與能量；跨core的資料走既有activation傳輸及NoP／NoC模型。cache producer的整個產出tile保留至最後consumer／send完成，容量計入peak。這是保守的whole-produced-piece lifetime，未假定可免費壓縮為最小halo slice。

外部activation按DF tile的reload cohort建立讀取；cold weights照實讀取，persistent weights使用既有capacity-backed政策。AL/WL/OL的bank、ports、scratch、psum、prefetch slots仍由既有片內模型付成本與檢查。cache資料不會因為被標成reuse就免除片內消費存取。

## DP成本與近似邊界

每個合法segment×tile×mode節點，使用與完整評估器相同的物理package context、片內bank服務、resource calendar、energy ledger及容量檢查，評估隔離子圖。共享context不會再呼叫Rapid重建封裝。

DP保留前綴Energy及Latency，以E/T Pareto及beam限制搜尋；不把各組EDP直接相加。切點的邊界位置與Part由固定mapping決定，boundary依既有contract透過DRAMmaterialize。原始方案作fallback，少數完整候選再用全DAG oracle依使用者目標與限制排名。

**這仍是有界近似DP**：隔離子圖對多個外部input使用不同FD時採近似；完整DAG lifetimes及容量必須最後檢查。proxy dominance不是全模型最佳性的證明，beam可能剪掉真正最佳方案。跨group仍使用既有barrier，不宣稱新增跨group並行pipeline。

## 預算、checkpoint與結果

`--budget`是外層mapping queries，**不是總oracle預算**；`--fusion-budget`是每次內層完整候選評估上限。結果另記初始化、內層完整oracle requests、segment oracle queries，以及本process的unique full-model evaluations。比較DP+RL與其他方法必須一起報這些工作量與elapsed time。

內層候選與排序是確定性的。checkpoint identity包含物理/source identity及fusion bounds；更改inner budget／tiles／depth不會混用舊checkpoint。resume會重建必要inner候選，既有外層metrics cache仍保存於checkpoint；本process計數不能冒充跨resume累計總數。

同一oracle內的segment結果也有容量受限的memo：key包含局部workload、完整Part/CG/FD/tile/reuse與外部producer的output FD；物理硬體/source固定於該oracle。外層只改少數layer時可重用未受影響的子圖成本，實際miss才計入segment oracle queries。此cache不改任何PPA、容量或排序結果，不跨不同oracle／硬體混用。

輸出`mapping.json`有實際fusion_stacks；`summary.json`有候選成本與選擇證據；`metrics`有MAC/cache-copy帳本；`layout.html`與`layout.json`顯示各layer的fusion設定。GUI保留四種偏好、多模型strict/soft與closest邏輯。

## 驗證及限制

新增數值測試以PyTorch逐個生成WorkUnit執行，核對每一中間輸出及最終結果；覆蓋三種reuse、residual、多die、多shard、stride、depthwise及兩個microbatches。獨立小空間窮舉核對無beam／完整候選評估的DP結果；另檢查快取搬移付能量、UB不足拒絕、MAC與能量守恆、日曆無資源重疊、JSON round trip。

尚未提供任意memory-level／bank-placement聯合搜尋、最小halo的動態slice eviction、tile等價類加速、snake traversal、Concat、任意非封閉多出口fusion或RTL/silicon校準。新增能力不等於完整重現DeFiNES，也不保證RL優於Greedy。

### 此次已完成的驗收

- 全回歸 **176 tests PASS**，log：`output/df_joint_20261011/tests.txt`。包含新的跨融合群shortcut／共享DRAM讀取排序回歸，修正融合與一般units混合時的dependency cycle。
- 三種overlap的卷積／residual數值比對；stride、多shard、depthwise、兩microbatches；獨立小空間窮舉。
- torchvision ResNet50第一個完整bottleneck（含downsample與Add），32×32模型輸入的真實operator shapes：三種策略全部容量合法、資源日曆合法。這是孤立bottleneck PPA，沒有宣稱量化ResNet的數值精度。
- 同預算RL／Greedy／SA／Random主入口全部完成；RL 2→3 queries接續與直接3 queries的policy、RNG、best plan／metrics精確一致。
- 完整ResNet18 operator graph在 **32×32輸入** 下完成初始traffic DP＋Tile/Fusion/Reuse DP：batch1、16 compute dies、4IO、4DRAM；內層上限4layers、tiles4×4／8×8、beam3、完整候選上限3。保存mapping、timeline、capacities、PPA、布局及source identity，可再核對資源與依賴。
- GUI API送出實際toy共同探索、載入結果及layout iframe，瀏覽器無page errors。GUI目前提供於localhost8766；8765的既有server未強制停止。
- 架構圖PNG／SVG／PDF：真實GUI輸入截圖、演算法模組、操作、成本與reward；已檢查文字未超出畫布，PDF為單頁可選取文字的vector輸出。

`tools/audit_df_delivery.py`只讀檢查已保存source／calendar／test結果。`validation.json`與`validation_manifest.json`保存可追溯證據。

**效能限制**：224×224 ResNet18的初次子圖搜尋超過20分鐘，該次測試已停止，沒有完成PPA／加速宣稱。32×32完整圖約182秒完成。這些數字是Python分析器的運行時間，不是硬體推論latency；內層增加了許多子圖評估，第一次搜尋仍需進一步加速。此次不宣稱已完成224×224全模型的DF驗證。

範例（在`C:/Users/user/Desktop/rapidchiplet/simplified_rapidchiplet`執行）：

```powershell
../.venv/Scripts/python.exe -X utf8 hybrid_dse.py --model toy --batch 1 --planner traffic_dp --fusion dp --fusion-tiles 2x2,4x4 --fusion-depth 4 --fusion-budget 4 --budget 3 --out ../output/df_joint_20261011/toy_rl
../.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p 'test_hybrid_depth_first.py' -v
../.venv/Scripts/python.exe -X utf8 hybrid_gui.py --port 8766 --out ../output/df_joint_20261011/gui
```

對照模式：`--fusion off`關閉內層搜尋。若使用`--mapping`提供已含fusion_stacks的方案，仍忠實執行該方案，不會偷偷刪除它的排程。

架構圖：`output/df_joint_20261011/system_architecture.svg / .png / .pdf`；可用`tools/build_df_architecture.py`與`tools/render_df_architecture.cjs`重建。真實GUI截圖來自localhost8766；右側package由已執行結果的實際placement產生。
