# DeFiNES 分享對話與目前 Hybrid DSE 的功能差距

> 後續更新：使用者已提供16張原照片並授權實作。下方矩陣是修改前的audit；最新已實作Tile/Fusion/Reuse DP、depth-first tile DAG、三種overlap、重算帳本與UB容量／copy成本，見 [hybrid_df_dse.md](hybrid_df_dse.md)。任意memory-level配置、tile等價類等限制仍保留。

核對日期：2026-10-11。對象是目前 GUI 呼叫的 hybrid_dse / simple_rapidchiplet.hybrid 路徑，非舊 preference_dse 分支。

分享對話：https://chatgpt.com/share/6acb3157-40b4-83e8-86b6-db07b24f3723

公開頁成功讀取文字；解析出 16 個不同的原圖識別資訊，但圖像下載端點匿名存取回傳 401。沒有逐張讀到原始照片。以下依對話文字、DeFiNES 原論文及本機實作核對，不將對話的建議當成使用者要求實作的指令。

原論文：https://arxiv.org/html/2212.05344v2

原始開源：https://github.com/KULeuven-MICAS/DeFiNES

## 核心判斷

目前具備 chiplet/global mapping、跨微批次 layer pipeline、單層 macro/micro tiling、片內 reuse 與完整分析 oracle；尚未具備 DeFiNES 式的跨層空間 tile 排程，及其 tile size / overlap caching / fusion-depth 聯合探索。

三個概念不能等同：Part 的 H/W 分割是工作分配；microtile 是單層的片內運算粒度；DF tile 是融合層群最後輸出的區域，並反向決定前面多層需要運算、儲存和重算的範圍。

## 功能矩陣

| 功能 | 目前已有 | 尚未具備／限制 |
|---|---|---|
| 全算子 DAG | 七種 torchvision 模型；shape、residual、pool、group/depthwise conv 等 | 尚無 Concat 的運算語意與 FX 提取；不能概括為任意 DNN |
| 空間 tile 與 halo | TensorRegion、required_input_regions、單層 stride/padding/dilation 範圍推導、producer/consumer 交集 | 尚無以 fusion stack 終點 tile 為起點的跨多層反向依賴／to-compute 區域推導；dilation 用 dense envelope，是保守範圍 |
| Tile DAG | compile_mapping 產生 macro tile WorkUnits 與相交依賴 | 沒有融合 stack + cache/recompute 狀態的 tile 執行圖 |
| 深度優先 tile 排程 | 同 spatial group 的不同 layer/core 可依相依與資源重疊；有宏 tile 排程 | 同 core predecessor 依 group/MB/layer/tile 排序，尚無一般化的跨層 tile-first 排程搜尋；不能用跨 MB pipeline 宣稱完成 DF |
| 融合深度搜尋 | LayerGroup、CLI bounded beam 可改 grouping / microbatch；Conv+BN/ReLU post-op 合併 | 這不是卷積融合 stack 的 F 與跨層 Tx/Ty/R 聯合搜尋；GUI traffic_dp 在已有 groups 上調 mapping，RL 五操作不改 groups |
| Overlap storage modes | 容量受限的整區域 containment LRU；exact-region weight persistence | 尚無 full recompute、horizontal cache/vertical recompute、full cache 的跨層 activation overlap 政策；partially overlapping boxes 不作精確 halo slice reuse |
| 重算 MAC 帳本 | workload MAC、分割 MAC、SIMD cycles 與 energy | compile_mapping 強制 sum(unit.macs)==workload.total_macs；尚無 logical / unique / recompute / executed MAC 分帳與重算 jobs |
| 動態記憶體層級 | AL/WL/OL L1/L2 與 UB 容量、讀寫成本、scratch slots、權重與 activation lifetime | 尚無逐 layer/tile/operand 選擇最高 active memory level、跨層 L1 bypass、activation cache placement 或容量不足時比較 reload/spill/recompute 的 allocator |
| Data-copy phase | NoP/NoC、DRAM、UB/L2 read/write jobs 與共用資源衝突 | 尚無 DF overlap cache 蒐集／重排／複製的獨立 copy actions，與其來源／目的 bank、port 及成本帳本 |
| Tile execution order | OS / activation-reuse / weight-reuse 片內 loop order | 尚無跨層 tile traversal（tile-first、row/snake 等）及與 cache policy 的聯合選擇；任意 traversal 是對話提出的 extension，非 DeFiNES 原論文已全面搜尋項目 |
| Tile type 加速 | 核心服務與 plan fingerprint cache；dataflow 取代表 units | 尚無 DeFiNES 依邊界／首末列／cache availability 判定 tile 等價類，精算每類再按 multiplicity 累加；不能在 NoP 資源負载不同時無條件複用 |
| 通訊感知 DF 策略 | 精確跨 die flows、multicast path union、cluster routing、frontier DP | 尚無比较 remote halo cache / transfer / local recompute 的 adaptive tiling/fusion 決策 |
| RL local scheduling actions | OP1 Part、OP2/3 cores swap、OP4 allocation、OP5 DRAM selectors | 尚未選 DF Tx/Ty、fusion split/merge、overlap policy、active memory level、跨層 tile order；片內 dataflow 為獨立有界提案程序 |
| 硬體聯合探索 | GUI 4/8/16 dies、ring/mesh；UB/雙 buffer 是使用者設定；硬體成本重算 | 尚無 L1/L2 分布、bank/ports、NoP bandwidth、可變 IO 拓樸的全域 DSE；能讀 HardwareSpec 不等於搜尋器已搜索全部參數 |
| 驗證與研究證據 | MAC、區域、資源日曆、容量、energy ledger、resume 等測試；RL/random/greedy/SA 同預算基線 | 尚無 DF cached/recomputed tile 的數值輸出比對、DF 小空間窮舉最佳解、Tile/Fusion/Cache/Interdie 全因子消融、獨立 RTL/silicon PPA 校準 |
| 工作負載涵蓋 | ResNet18/34/50、VGG16/19、AlexNet、MobileNetV2 | 尚無對話／DeFiNES 的 FSRCNN、MC-CNN、MobileNetV1 及其 DF benchmark protocol；模型擴充需相應算子支持 |

## 最有力的程式證據

- `simplified_rapidchiplet/simple_rapidchiplet/hybrid/mapping.py:294`：單層 required_input_regions。
- 同檔 `compile_mapping`：每層各自切輸出 shard/tile，再建立 intersection dependencies；MAC 總和必須等於 workload.total_macs。這是已有 tile 基礎、但尚無 DF 重算模式的直接證據。
- `evaluator.py`：previous_core_unit 以 group、microbatch、layer、shard、tile 排序；read/compute/write 使用資源日曆，沒有新的 DF tile-first policy。
- `ondie.py`：bounded whole-region containment LRU；partial overlap 仍是分開付容量的 boxes。內部 streaming 成本投影到 macro 服務，尚無微 kernel 級 overlap credit。
- `dataflow.py`：六個有界 loop/tile/C proposals，並以整個 plan oracle 驗證接受；不等於完整跨層 spatial tile search。
- `planner.py:244`：可選 bounded graph-group beam；`hybrid_dse.py:prepare_plan` 說明 GUI traffic_dp 路徑及與五操作分工。
- `actions.py`：OP1–OP5 及 OP4 idle/resize extensions；沒有新的 DF scheduling action。
- `workload.py:102` / `models.py`：支持的 operators 與 models 範圍；`fuse_inference_postops` 是 BN/ReLU 合併，非跨卷積 stack fusion。

以上相對模組路徑除特別註明外皆位於 `simplified_rapidchiplet/simple_rapidchiplet/hybrid/`。

## 不需要重新當成缺項的基礎

真實 FX DAG、residual、單層 halo、multicast、AL/WL/OL banks、bank 成本、UB/lifetime、付費雙緩衝、原生 RapidChiplet 整合、多模型同架構推薦、四種偏好、逐項 strict/soft、closest 和實際布局 GUI 均已存在。分享對話提到「18 semantic blocks」是過往上下文；目前 hybrid 主路徑不只使用那個線性 block abstraction。

## 建議開發切入點（尚未實作）

1. 固定一個單 die 硬體，以三層 conv 和一個 residual bottleneck，建立 stack-output tile 反向區域推導；重用現有 TensorRegion 與單層 inverse dependency。
2. 增加三種固定 overlap mode、logical/recompute MAC 帳本、activation cache lifetime、memory-level copy events；數值輸出對照 PyTorch。
3. 小型 tile/fusion/cache 空間窮舉，確認成本帳本與容量檢查正確，再接 Greedy/beam/DP。
4. 接現有 NoP oracle，比較 halo transfer 與 local recompute；最後才把 scheduling proposal 接進 RL。

不用重寫原生 RapidChiplet adapter 或現有 GUI。DF 需要新增 workload/local scheduling 分析，Rapid 不會自動提供融合、cache 和重算成本。首個研究里程碑應是可驗證的 DF cost/scheduling 子系統，而非先擴大 RL 的操作列表。
