# Gemini 2×2-core 硬體與成本契約

更新：2026-10-31（Asia/Taipei）。對應 profile：`gemini_2x2_core_v1`，`package_topology=gemini_mesh`。

## 論文與提供原始碼的對應

本版依使用者提供的 Gemini 論文 §III、Fig.2，建立跨所有 computing cores 的 mesh、每 core 獨立且全域可見的 GLB、PE array、vector unit、DMA、router、control unit，以及獨立 IO chiplets。固定每 compute chiplet 為 2×2 cores。每邊有兩個 core，因此每邊配備兩個 D2D interfaces，總計八個；邊界未連接的 interfaces 仍支付面積與漏電。

參考 §VI Table I 及 §VI-B 的 G-Arch：1024 MAC/core、2MiB GLB/core、NoC 32GB/s、D2D 16GB/s。提供的 `GEMINI-HPCA2024-master.zip/src/main.cpp` 第 985–988、1013–1019 行使用 4×4 PE bus、8 lanes × 8 vector MACs/PE，得到每 core 16×8×8 = 1024 scalar MAC/cycle；AL1/WL1/OL1 為每 PE 8/4/2KiB。第 1018、1217 行說明 OL2 是 GLB 的一部分，第 1019、1210 行不提供獨立 WL2/AL2。因此本版保留編譯器的 L2 working-set view，但不重複計算 L2 的實體 SRAM、存取能量或頻寬。

## 固定的 compute-chiplet 規格

| 資源 | 規格 |
|---|---|
| 真正的 compute cores | 2×2 = 4 |
| 每 core PE array | 16 PEs，各 8 lanes × 8 vector MACs |
| 每 core scalar MAC/cycle | 1024 |
| 每 die scalar MAC/cycle | 4096 |
| clock | 1GHz，Gemini 架構設定，沒有 timing signoff |
| 每 die 理論吞吐 | 4.096 TMAC/s = 8.192 TOPS（2 ops/MAC）|
| 每 core GLB | 2MiB，共四個獨立可計容量的 GLB |
| 每 PE WL1/AL1/OL1 | 4/8/2KiB |
| NoC directed-link bandwidth | 32GB/s |
| D2D 每 core-side interface bandwidth | 16GB/s |
| 每 chiplet D2D interfaces | 每邊兩個，共八個 |
| vector unit | 每 core 64 scalar lanes；以明確的 scalar MAC energy/area proxy 計成本 |
| precision | 延續後端已驗證的 INT8 activation/weight、INT24 psum |
| prefetch | 單 scratch slot；不給予隱藏雙緩衝容量 |

這是實際四個完整 core，各自擁有 PE array、GLB、vector、DMA 與控制資源；不同於舊版將一顆 die 的 16 PE 分成四個軟體排程 slot。每個 core 內的 PE fabric 使用後端已支援的 mesh 近似；這項適配有列於 provenance，未宣稱重現 NVDLA bus RTL。

## 合法系統模板與連線

`gemini_hardware(count, mesh_shape=(rows, cols))`、`enumerate_gemini_architectures()` 產生合法矩形 compute meshes。預設 compute 數量為 1、2、4、8、16，完整 shape 候選共 15 個。ID 為 `gemini_c{count}_{rows}x{cols}`。`include_shapes=False` 只用各顆數最接近正方形的配置。

每一 compute-chiplet row 左、右各配置一個 IO chiplet，各連一個 DRAM die。因此 compute/IO/memory 分別為 `rows*cols`、`2*rows`、`2*rows`。IO 沒有移入 compute dies。每 IO 連到該側兩個 core rows 的兩個真實 ingress routers，有共享 crossbar 與 DRAM controller 競爭。每 IO 的 DRAM 固定 16GB/s、2GiB；這兩項是本專題模板假設。只增加同一列的 compute dies 不會自動增加 DRAM 頻寬。

這個 row-side IO 模板是 Gemini 可擴充模板的明確實例。它沒有採原作者原始碼對部分多 chiplet 實驗固定四個 IO dies 的特例，亦不聲稱與該特例逐位元相同。IO 與 DRAM 的數量、controller/PHY/crossbar、silicon area 和 idle power 全部計入。

`PackageGraph` 保存實體 dies；每側 package link 以 `lane_count=2` 及 32GB/s aggregate bandwidth 表示兩個 16GB/s interfaces，供 native RapidChiplet 做 geometry/bump/PHY 檢查。`gemini_network.py` 將它展開成每 core 的真實連線。工作負載 flow 的 route、link reservation、multicast bytes 和能量都使用展開的獨立 lanes，單一 flow 不會免費取得 aggregate bandwidth。路由固定 XY（先 columns，再 rows）；沒有 torus、自由任意路由或任意 floorplan 搜尋。

## PPA 定義與證據邊界

PPA 使用既有 16nm 文獻參考成本；Gemini 論文實驗為 12nm，本版沒有虛構製程縮放。MAC、SRAM、GRS 來源與不確定性保存在 `hardware.provenance`。control/router/DMA/vector、DDR/IO、leakage 及線路 idle 成本皆為明示的分析假設。vector energy/area proxy 會隨 scalar operations/lanes 支付成本，並非校準後的 vector RTL。

* `area_mm2`：compute + IO + DRAM 的總 silicon area；`package_area_mm2` 另列封裝 footprint。
* `energy_j`：整個使用者要求 batch 的 dynamic + idle/leakage 能量；`energy_per_sample_j` 再除以 batch。
* `latency_s`：含 DAG 相依、read/compute/write、NoC/D2D/DRAM、資源競爭及 pipeline 限制的完整 makespan。
* `power_w`：完整 batch 的總能量 ÷ 完整 makespan，即平均 package power，非 peak power 或 TDP。

每 core GLB 峰值與容量獨立檢查；也保留 die-total、local scratch 和 DRAM resident capacity 檢查。無自動 spill 模型；容量超限回傳 infeasible，不偷偷忽略或給予免費重載。

每 core 的 DMA、PE 端 GLB read/write stages 共用同一個 aggregate `glb_port` 排程資源，避免三者同時各取得完整 64GB/s。SRAM bank 模型採 1RW，各 bank 若有互不衝突的實體位址分配，理論上可並行；目前沒有 bank-address allocator，因此整個 atomic stage 占用共享資源是明示的保守近似。核心 MAC 計算階段使用本地 L1，無須全程占用 GLB port。

## 瓶頸診斷

`HybridEvaluation.diagnostics` 是完整 report；`metrics.diagnostics` 是供搜尋使用的穩定摘要（全部 layer rows、最高成本前 128 flows、每 link 前 32 windows）。`HybridEvaluation.to_dict().diagnostics` 保留完整 report。compact/full trace 的 scalar metrics 與摘要完全一致。

報告包含 system、layers、flows、network、memory、df_stacks。layer 的 busy time、resource queue delay、排程 span 皆來自實際 analytical schedule；criticality/slack 的 DAG 同時包含 workload dependencies 與該排程真實的 resource order。flow 保留 tensor half-open region、producer/consumer、來源/目的、payload、逐段 bytes/capacity、ready/start/finish 與 queue delay。network 保留真實有重疊意義的 reservation windows；不能以累積 bytes 冒充壅塞。

此 scheduler 以 atomic route service 共同保留 multicast 路徑，因此無法唯一拆分 DRAM/NoC/D2D queue delay：各 split wait 明確回傳 `null`，不任意標成 compute-bound。單一 flow 的共同路徑 bytes 只計一次；各 destination core GLB 的實際副本仍付讀寫與容量成本。busy time/waits 可在不同工作之間重疊，不可把所有分項相加當 latency。每 link 的 atomic queue delay 也可能重複涵蓋同一個 flow，不能跨 link 加總。

DF report 使用 compiler-derived 各 stack executed/unique/recompute MACs、實際 sink tile types 與跨 core cache copies。尚無法從 aggregate GLB 存取唯一分離同 core overlap-cache 的讀寫，因此這兩項為 `unknown/null`；不添加任意效率係數。

## 驗證

新增 `tests/test_gemini_hardware_diagnostics.py` 九項測試：真正 core/PE/GLB 成本、IO/DRAM 模板、硬體 mutation 拒絕、獨立 core lanes 的 intra/cross-die routing、multicast/能量守恆、完整 Toy 執行、每 core GLB 超容量拒絕、診斷實際時間窗與 resource-order slack，以及實際排程中 DMA/PE GLB 讀寫無 port 重疊。九項通過。舊 hardware 11、evaluation 11、fixed_mesh 7 項亦通過。

Windows sandbox 下測試請將 `TEMP`/`TMP` 指向 workspace 內可寫的 `tmp`，再從 `simplified_rapidchiplet` 執行 `python -m unittest discover -s tests -p test_gemini_hardware_diagnostics.py -v`。

## 來源

使用者提供 Gemini PDF，§III/Fig.2、§VI/Table I/§VI-B；使用者提供 `GEMINI-HPCA2024-master.zip` 的 `src/main.cpp`；[Gemini 作者版論文](https://people.iiis.tsinghua.edu.cn/~gaomy/pubs/gemini.hpca24.pdf)。16nm 成本來源與既有不確定性說明見 `hybrid_cost16_sources.md`。
