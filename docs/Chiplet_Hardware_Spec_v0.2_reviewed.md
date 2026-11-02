# Chiplet 加速器硬體規格 v0.2：參數建議與架構審查

日期：2026-10-26（Asia/Taipei）  
狀態：**待確認的研究基準建議稿；不是已完成 RTL／實體設計，也不是目前程式的設定快照。**

本稿依使用者的 `Chiplet_Hardware_Spec_v0.1 (1).md`、新草圖、Gemini 與 INDM 原文整理。保留「同型 Compute chiplets＋獨立 IO chiplets＋外部 DRAM」；DRAM controller／PHY 放在 IO chiplet。片內拓樸仍待確認。以下容量與頻寬提供一組可審查的固定基準，沒有直接修改現有模擬器。

## 1. 結論與數值標記

**硬體的主要功能類別已列齊，適合作為架構研究起點；但端口接線、片內拓樸、DRAM 實體介面與資料精度轉換還不足以稱為完整硬體規格。** 不需要再隨意增加大型運算元件；應先補齊各元件間的服務與容量契約。

| 標記 | 意義 |
|---|---|
| U | 使用者清單／草圖指定。 |
| I | INDM 原文明確列出，後附圖、表或章節。 |
| G | Gemini 原文明確列出，後附圖、表或章節。 |
| D | 由已列數值算出；不代表原文直接報告。 |
| M | 本專案建議採用的研究假設，不能宣稱為論文實測或最佳配置。 |
| T | 尚待定義；不填入沒有依據的實體參數。 |

單位約定：本模型採 KiB＝1024 B、MiB＝1024² B；GB/s＝10⁹ B/s、Gb/s＝10⁹ bit/s。兩篇原文使用 KB，本稿把 SRAM 容量按二進位解讀，這項解讀屬 M。每一個 scalar MAC 在 TOPS 報告中算 2 operations；Vector Unit 的單一加法／比較算 1 operation。

### 1.1 建議固定的研究基準

| 項目 | 建議數值／配置 | 性質 |
|---|---|---|
| 每顆 Compute chiplet 的 PE 數 | 16，圖上可排成 4×4；PE 位置不自動決定片內拓樸 | U、I：Table V |
| 每 PE 的乘加平行度 | 16 lanes × 每 lane 16 個 scalar MAC＝256 MAC/cycle | I：Table II；D |
| Compute 目標時脈 | 1 GHz；0.5 GHz 作敏感度／舊版本對照 | I：Sec. V-A；G：Sec. VI-A；M：作為目標，非 timing 保證 |
| 每顆理論計算峰值 | 4096 MAC/cycle，4.096 TMAC/s，8.192 TOPS @ 1 GHz | D；INDM Table IV 以約 8 TOPS／顆報告 |
| Activation／weight／psum | INT8／INT8／INT24 | I：Sec. V-A；overflow、rounding、saturation 另定 |
| 每 PE L1，每一個 A/B 槽 | WL1 64 KiB、AL1 16 KiB、OL1 8 KiB | D：INDM Table V＋Eq. (1) |
| L1 雙緩衝後合計 | 每 PE 176 KiB；16 PE 共 2.75 MiB | M：兩個完整槽；D：加總 |
| 晶粒共享 L2，**包含兩槽的總容量** | WL2 512 KiB、AL2 256 KiB、OL2 256 KiB；合計 1 MiB | M；容量尺度參考 Gemini Table I／Sec. VI-A 的 GBUF；分配不是 INDM 原配置 |
| 額外 8 MiB UB／GLB | **本建議基準不再另外配置**；由上述共享 L2 承擔其角色 | M；避免保留同義名稱後重複計容量 |
| 片內鏈路頻寬 | 16 GB/s／方向／link；拓樸仍待確認 | G：Table I 的候選值；M：選此點作基準 |
| D2D 鏈路頻寬 | 每條 full-duplex link 每方向 12.5 GB/s＝100 Gb/s | I：Table IV 的 rate；M：明定全雙工方向語意 |
| 單個 IO chiplet 的 DRAM 服務 | 8.192 GB/s 有效服務上限、512 MiB 可存取容量 | M；頻寬由本稿峰值與 Gemini 的 GB/s/TOPS 研究尺度選定；容量不是論文數值 |
| IO 部署參考規則 | R×C Compute mesh 左右每列各 1 顆 IO，故 N_IO＝2R | M；保留新草圖的外側 IO 形式 |
| IO 網路接入 | 簡化基準先採 1 個 NoP router／IO；保留多入口作可選方案 | M；第 5 節說明選擇條件 |

**以上是我建議的一組一致基準，不表示使用者已批准變更。** 特別是 1 MiB L2、16 GB/s NoC、Vector Unit 配置及 IO 的 DRAM 參數，都需要在論文／報告中標成研究假設。

## 2. 先統一硬體階層

建議本專案明定為：

```text
Package
├─ 多顆同型 Compute chiplet
│  ├─ 16 PE
│  │  ├─ 16 vector-MAC lanes × 每 lane 16 MAC
│  │  ├─ lane accumulators／工作暫存器
│  │  ├─ WL1／AL1／OL1
│  │  └─ PE network interface
│  ├─ 共享 WL2／AL2／OL2
│  ├─ 片內互連（拓樸待確認）
│  ├─ 晶粒層級 Vector Unit
│  └─ Control／DMA／NoP router／D2D ports
├─ IO chiplets
│  └─ NoP 接入＋DRAM controller＋DRAM PHY
└─ 外部 DRAM
```

INDM Fig. 3 的一顆 Compute die 具有多個 PE；Gemini Fig. 2(b) 畫的是 **computing core**，而 Fig. 2(a) 的一顆 Computing chiplet 可以包含很多這種 core。兩者不是相同層級。

本稿借用 Gemini 的「共享 buffer＋PE array＋Vector Unit」功能，再搭配 INDM 的 PE 組織，是本專案的混合設計。**不能把 16 PE 解釋成 16 個 Gemini cores，再將 GBUF、Vector Unit 或 D2D 數量多乘一次。** 現有程式的四個 `mapping cores` 也只是分配 PE 的軟體群組，不是新增四套實體核心。

## 3. Compute chiplet：逐項補參數

### 3.1 PE 與本地儲存

| 元件 | 建議基本參數 | 功能與必要限制 | 來源／狀態 |
|---|---|---|---|
| PE | 16／Compute chiplet，目標 1 GHz | 4×4 是數量／排布表示；不等於已選 mesh NoC | U；I Table V、Sec. V-A |
| PE 內 vector-MAC | 16 lanes，每 lane 16 MAC，256 MAC/cycle／PE | 每顆 4096 MAC/cycle；tail、memory stall、低通道數會降低利用率 | I Table II；D |
| Accumulator | 16 個 lane 的 INT24 邏輯累加狀態 | 最小同時保留一組輸出時為 16×24 bit＝48 B；**不是整個 tile 的 psum 容量** | I Fig. 3、Sec. V-A；D：最小狀態推算 |
| WL1 | 64 KiB／PE／槽；2 槽共 128 KiB／PE | 本地權重；需要計算 refill 與重用，不能假設權重永遠已在場 | D：I Table V、Eq. (1)；M：雙槽 |
| AL1 | 16 KiB／PE／槽；2 槽共 32 KiB／PE | 本地 activation／halo；兩槽容量都計費 | 同上 |
| OL1 | 8 KiB／PE／槽；2 槽共 16 KiB／PE | 可存 INT24 psum 或量化結果；必須依實際資料型別計 bytes | 同上 |
| L1 服務頻寬 | 暫採合併讀寫 64 GB/s／PE 的分析上限 | M：有限頻寬基準；不是由容量推導出的 SRAM macro 規格。仍需以 SRAM banking／ports 驗證 | M；沿用既有分析尺度 |
| PE network interface | 1／PE；候選資料寬 128 bit、1 GHz，即 16 GB/s／方向 | 連片內互連，不是 D2D PHY；headers／backpressure 會占資源 | M；匹配本稿選用的 NoC rate |

L1 來源計算：INDM Table V 的受面積限制配置為 `L1_base＝8 KB`、W:A:O＝8:2:1。由 Eq. (1) 得 W＝64、A＝16、O＝8 KB。這是**單組 buffer 容量**；本稿額外採用兩組 A/B 是明確的 M，不將論文的容量再默認含有或不含有 ping-pong。

48 B 的 ACC 不能取代 OL1。若一次同時累加多組輸出，需額外 registers 或把中間值放入 OL1，產生相應讀寫。INT24 是論文的數值選擇，也需要規定溢位／飽和語意，不能宣稱所有任意形狀卷積都不會 overflow。

INT24 的儲存格式也要固定：緊密 packing 時每值占 3 B；若以 32-bit word 對齊則占 4 B。OL1／OL2 容量以實體 bytes 為準，元素數與傳輸量必須依實際格式重算。上述 48 B 是 ACC 的邏輯位元數下限，不是已實作的實體 register macro 面積。

可考慮補列「PE 工作 registers」：例如一組 16×16 INT8 weights 為 256 B，一組 16 個 INT8 activations 為 16 B，加上上述 48 B ACC，共 320 B／PE 的最小工作組。這是 M＋D 的**一種工作方式**，不是原文提供的完整 register-file 容量，也不能假設所有 dataflow 都只需要這麼多狀態；其成本不包含在 SRAM 容量合計內。

**頻寬與重用必須一起驗證。** 若每 cycle 都從 L1 重新讀取這 256 B weights 與 16 B activations，光讀取就要 `272 B × 1 GHz＝272 GB/s／PE`，尚未包含輸出。因而本稿暫採的 64 GB/s L1 服務上限，無法支援這種每 cycle 重載的方式。要接近 MAC 峰值，必須在 registers／dataflow 中實現足夠重用；否則模型應回報 bandwidth stall，不能直接假設 8.192 TOPS 持續可達。

### 3.2 共享 L2 與 Global Buffer 的處理

我建議把新草圖中標為 W/A/O L2 的區域明確定義為整顆 chiplet 的共享 scratchpad，承擔 Gemini GLB 的資料駐留功能。**三組分區合起來就是 1 MiB，不再另加一顆 1 MiB 或 8 MiB 的 Global Buffer。**

| L2 分區 | 物理總容量（A+B） | 每槽容量 | 角色 |
|---|---|---|---|
| WL2 | 512 KiB | A 256 KiB、B 256 KiB | 權重暫存、預取與 PE 分送 |
| AL2 | 256 KiB | A 128 KiB、B 128 KiB | activation、residual、可重用輸入 |
| OL2 | 256 KiB | A 128 KiB、B 128 KiB | psum／輸出收集、Vector Unit 前後資料、向外傳送 |
| **合計** | **1024 KiB＝1 MiB** | 兩槽合計已包含在左欄 | 不是 1 MiB 再乘 2 |

容量尺度的參考：Gemini Table I 探索每 core GBUF 的 256、512、1024、2048、4096、8192 KB；Sec. VI-A 的 baseline 亦使用 1024 KB/core。本稿選取 1024 KB 這個尺度並按上述比例分區，是 **M**。Gemini 沒有報告這一組 512/256/256 KiB W/A/O 分配。

與 INDM 的區別：INDM Table V、Eq. (2) 在 `ratio_L2＝1` 時對應 WL2／AL2／OL2＝64／16／8 KB。若完全沿用該容量、每組再配置兩槽，則整顆 L2 只有 **176 KiB**。本稿的 1 MiB 是為保留跨層 tile／residual 的空間而提出的容量放大，不是照抄 INDM 的最優值。

建議共享 L2 的分析服務上限先設為 **64 GB/s 合併讀寫／die（M）**；PE、DMA 與 Vector Unit 共用同一容量與服務帳本。這個 rate 不等於三個分區各自獨享 64 GB/s，也不保證完成 SRAM macro timing。若 SRAM 是單 RW port 或有 bank conflict，必須降低並行服務能力。

使用方式以區域與生命週期管理，不要求每層完整 tensor 都放得下。AL2、OL2 中 residual／fusion 暫存要與正在運算的 tile 一起計容量，不能再給軟體一個免費 cache。

### 3.3 原清單中其他 Compute 元件

| 元件 | 建議填入的基本參數 | 仍須明確的內容 | 來源／狀態 |
|---|---|---|---|
| 晶粒層級 Vector Unit | 1／die；參考採 16 個 INT32 lanes，目標 1 GHz；簡單加法／比較峰值 16 G lane-ops/s | 首版支援 ReLU、Add、比較／max、reduction 與定點 requantization；各算子的 cycles、讀寫與中間位寬分開定義。mul／shift／requant 不自動等於一個 add 的成本 | G Fig. 2(b)、Sec. III 提供功能；**lane 數、INT32 與 rate 都是 M** |
| Vector 量化參數儲存 | 可先在共享 L2 中保留 4 KiB 邏輯區域，不額外假裝新增 SRAM | M：若每 channel 以 8 B 保存尺度／shift／zero point／對齊資訊，一次容納 512 channels；超過時分批載入並計流量 | M、D；不是論文給定容量 |
| Control Unit | 1／die；可先採編譯指令／descriptor 驅動的控制狀態機 | 不需要為軟體 DSE 預先指定 RISC-V cache 大小。指令／descriptor 儲存位置、完成通知與同步機制要補 | G Sec. III；M：首版抽象。私有 SRAM 為 T |
| DMA | 1 個邏輯 engine／die；參考服務上限 16 GB/s 合併讀寫 | 目的地／長度／stride／依賴／tag 必須定義；outstanding 數量、burst 與 queue 深度為 T。使用 L2 staging，不另憑空增加資料 buffer | G Sec. III 提供功能；**數量與 rate 為 M** |
| 晶粒間 NoP router | 每 die 1 個邏輯 router：4 個方向＋1 個 local 接入＝5 個邏輯端口 | 每網路方向鏈路為 12.5 GB/s；Compute 的 local 端接 DMA／L2 NI。內部結構、是否與片內 gateway 共用要另畫接線表 | M；不是 INDM cluster router 的直接複製 |
| NoP 交換服務 | 可採總計 64 GB/s 的共享上限 | M：四個方向合計要求可到 50 GB/s；再加 local traffic 時仍受總服務限制，不能宣稱所有端口永遠同時滿速 | M；須計入仲裁／擁塞 |
| D2D TX/RX | 簡化方案每個方向預留 1 個 full-duplex port，共 4／die；每 port 12.5 GB/s／方向 | 四個 port 是四組對端連接，不是四個藍色區塊的圖示數量；邊界未接線仍計成本 | I Table IV 提供 rate；端口數與全雙工語意為 M |

PE 內的 vector-MAC 是 dense Conv／GEMM 的乘加組織；晶粒層級 Vector Unit 處理非矩陣算子，**建議保留這兩者，改名與分層，不要把它們當重複元件刪掉。**

第一版可讓 Vector Unit 經共享 L2 讀取 OL2 的 psum 與 AL2 的 residual，將結果寫入另一個有效區域。這是功能契約的 M；不要在尚無 FIFO／flow-control 定義時直接畫成免費的 PE→Vector Unit bypass。若要支援 inference BN，可優先將可折疊部分併入權重，再明定 scale／bias／requantization。Softmax、GELU、exp／division 不列入這一組基本 unit 的無成本支援。

## 4. IO chiplet 與外部 DRAM：逐項補參數

| 元件 | 建議基本參數 | 說明／未定義項目 | 來源／狀態 |
|---|---|---|---|
| DRAM controller | 每 IO 1 個邏輯控制器；本稿固定有效服務上限 8.192 GB/s | 記憶體通道數、實際 data bus 寬、資料率、refresh、讀寫切換與排隊模型仍需補。有效上限不是 PHY raw peak | G Sec. III 支持獨立 IO；**數值為 M** |
| DRAM PHY | 每 IO 至少 1 組對應記憶體通道的 PHY 介面 | **不把 8.192 GB/s 直接當 PHY pin rate**。DDR 版本、channel width、MT/s、pinout、尺寸與毫米座標均為 T | G Fig. 2、I Sec. III-A 支持放 IO；細節 T |
| 網路接入 router | 簡化基準 1／IO；多入口方案見第 5 節 | 因 8.192 < 12.5 GB/s，單條 D2D 在名義頻寬上已可承擔單個 controller 的單向輸送；仍需計 headers、競爭與實際路徑 | M、D；不是多入口永遠無用 |
| IO 內部交換／仲裁 | 可與此 NoP router 合併；共享服務上限暫採 64 GB/s | 不再另外為同一個交換功能重複計一個神祕 crossbar；需分開真正不同的 router switch 與 memory-side arbiter | M |
| IO-side staging／request queues | 建議明列為必要邏輯，容量暫 T | controller、router 之間須有流控及排隊；不能因圖上未畫而視為零成本、無限容量 | 新增必要項目；兩文沒有本專案所需 queue 數值 |
| IO D2D TX/RX | 簡化方案與 Compute 相同，四方向各保留 1 port，每方向 12.5 GB/s | 只有實際相鄰方向接線。IO 與 IO 間的垂直 link 若保留，須允許 IO router 中繼 | M；草圖支持外側 IO 列 |
| Host／外部 IO | 首版 inference 核心評估可先省略實體 host PHY，輸入／權重視為已在 DRAM | 必須寫明不含模型載入、相機／主機傳輸時間。若要完整板級系統，至少再指定一條控制／資料通道；其標準與 rate 為 T | G Sec. III 提及 host／其他 IO；範圍為 M |
| 外部 DRAM | 每 IO 可見 512 MiB；本稿每 IO 有效服務 8.192 GB/s | 512 MiB 是系統容量假設；不代表已選好一顆實體 DRAM die，也不決定 DDR channel／rank／bank 組織 | **M；兩文沒有給此容量** |
| D2D 實體鏈路 | 每對鄰居 1 條 full-duplex link（簡化方案）；12.5 GB/s／方向 | 對每條 link 列 source port、destination port、rate、lane／macro 數與是否使用。未選定實體 PHY 時不填毫米位置 | I Table IV：rate；其餘 M／T |
| 封裝／interposer | 研究模型可保留 passive silicon interposer 假設 | **兩篇的主要評估皆採 organic substrate**。不能把其 GRS 長度／能量直接宣稱為 silicon interposer 實測。封裝尺寸、bump pitch、線寬、層數為 T | 封裝選擇為 M；G Sec. VI-A、I Sec. III-A 為原始條件 |

### 4.1 DRAM 頻寬的來源與兩種口徑

INDM Table IV 的 Edge／Mobile／Cloud 總 DRAM bandwidth 為 **37.5／150／600 Gb/s**，分別對應 1／4／16 Compute dies；除以 8 後為 **4.6875／18.75／75 GB/s**。這是各情境的系統總頻寬，不是每一顆 IO 都有 75 GB/s。將它平均攤到 compute 數，只是 D，不表示每顆都有獨享 DRAM channel。

Gemini Table I 探索 **0.5／1／2 GB/s per TOPS** 的總 DRAM 頻寬尺度。本稿以 1 GHz、每 Compute 8.192 TOPS，選定每 IO 8.192 GB/s 作固定分析基準。其含義要搭配 IO 部署規則，而不能永遠宣稱全系統都是 1 GB/s per TOPS。

若使用 `N_IO＝2R`，且每 IO 512 MiB、8.192 GB/s，則：

| Compute 配置 | Compute 數 | IO 數 | 總 DRAM 容量 | 總有效 DRAM 上限 | 理論 Compute TOPS | GB/s per TOPS |
|---|---:|---:|---:|---:|---:|---:|
| 1×1 | 1 | 2 | 1 GiB | 16.384 GB/s | 8.192 | 2 |
| 1×2 | 2 | 2 | 1 GiB | 16.384 GB/s | 16.384 | 1 |
| 2×2 | 4 | 4 | 2 GiB | 32.768 GB/s | 32.768 | 1 |
| 2×4 | 8 | 4 | 2 GiB | 32.768 GB/s | 65.536 | 0.5 |
| 4×4 | 16 | 8 | 4 GiB | 65.536 GB/s | 131.072 | 0.5 |

這是 M＋D 的建議部署規則，數值碰巧落在 Gemini 的研究尺度內，**不是 Gemini 規定這樣配置 IO**。小系統 2 顆 IO 的成本可能偏高，也可另設小系統規則；一旦改規則，容量、頻寬、成本與限制要一起重算。有效 memory bandwidth 還受 NoP 路由／競爭限制，表中只是服務能力總和。

具體 DRAM 選型還需符合：`原始頻寬＝通道數 × data bus 寬(bit) × 資料率(GT/s) ÷ 8`；有效值再乘以效率。8.192 GB/s 是本稿的**分析上限**，不是一個 JEDEC 資料率。DRAM 延遲也不能由頻寬倒推；至少需補一組 controller／memory service latency 或另做延遲敏感度，原文沒有足以決定本專案實體時序的數值。

## 5. 草圖最需要修正：D2D 區域、端口與多入口

### 5.1 藍色區塊不能直接當成 port 數

你的草圖中，部分角落同時有水平線與垂直線。如果每條線都是獨立 point-to-point D2D link，那個角落至少包含兩個獨立 port；若要共用一個 port，就需要具體的主動交換／多點協定，不能當成普通 PHY 的被動分叉。

Gemini Fig. 2／Sec. III 的「每邊四個 D2D」來自每邊有四個 computing cores；不代表所有 16 PE chiplet 都固定要每邊四個 D2D。INDM 的七組 GRS TX/RX 是其 IO-cluster 的配置，也不能直接搬成此 mesh IO 的必備數量。

### 5.2 可選的兩套接線方案

| 項目 | A：建議先採用的簡化方案 | B：保留草圖中的雙鏈路方案 |
|---|---|---|
| 每對相鄰 dies | 1 條 full-duplex D2D | 2 條獨立 full-duplex D2D |
| 每條 link 每方向 | 12.5 GB/s | 12.5 GB/s |
| 同一對鄰居合計每方向 | 12.5 GB/s | 25 GB/s；僅在兩路可被分派與排程時成立 |
| Compute 完整四方向預留 | 4 ports／die | 8 ports／die，可放在四個 PHY 區域，但每區要明列內含 port |
| IO 入口基準 | 1 個邏輯 router＋1 個 memory local port | 可採 2 個注入 router／NI；須設計 controller 仲裁與其各自對端 |
| 多入口是否真的獨立 | 本方案不宣稱多入口 | 要定義是兩個不同 NoC 接入點，或只在同一 router 前增加鏈路；兩者不同 |
| 代價 | 可先驗證軟體；較低 PHY／端口成本 | 增加 PHY、router／FIFO、bump／面積／漏電與模型複雜度 |
| 模擬器需求 | 普通 mesh graph | 必須支援平行實體 links／multigraph，不可合成一條不付成本的加倍頻寬線 |

以草圖的 2×2 Compute＋左右四顆 IO，將 IO 也納入相鄰格點，整個 NoP 是 2×4 的圖：

- 共有 `2×3＋1×4＝10` 對相鄰 dies。
- A 方案是 10 條 D2D links，使用 20 個 port 端點。每顆 Compute 有 3 個相鄰 dies，使用 3／4 個 D2D ports；每顆 IO 有 2 個鄰居，使用 2／4 個 ports。這和先前「沒有 IO 的 2×2 Compute mesh 每顆只用 2 port」不同。
- B 方案是 20 條 links、40 個端點；每 Compute 使用 6 個獨立 port。若 IO 只為內側與上下方向各預留兩路，則每 IO 可預留 6 ports、角落使用 4 個。**四個藍色角落區域不等於四個 port。**

若想要每 IO 兩個入口，但不想把所有 compute-to-compute links 加倍，也可以設計只在 IO 邊界採雙鏈路的第三種方案；其端口數與圖需另列，不能混進 A 的四方向單鏈路設定。

### 5.3 PHY 放置應該怎麼寫

- **Compute die**：A 方案在四個方向各預留 D2D 介面區域，具體 TX/RX macro 長寬、bump 與毫米座標尚未指定。它沒有 DRAM controller／PHY。
- **IO die**：DRAM PHY 建議朝封裝外側、接外部 DRAM；D2D 朝相鄰 Compute 或 IO dies。這是建議方位，尚未構成 pinout／floorplan。
- 左右 IO 若要用同型 die，可研究旋轉後使用；需要處理 rotation、port ID 與佈線對應，不能把左右鏡像圖自動當成同一實體版圖。
- 要從 PHY 的 macro area、邊緣長度、lane/bump budget 決定能放幾組；不要先畫四個角落色塊就宣告放得下。

## 6. 片內互連：可以填 rate，不能偷偷替你決定拓樸

你在 v0.1 明確寫了拓樸尚未指定，因此本稿沒有把 4×4 PE 當成已批准的片內 mesh。先固定每條 directed link 的參考能力 **16 GB/s**，參考 Gemini Table I；INDM Table IV 的 68 Gb/s＝8.5 GB/s 另保留作敏感度比較。

| 候選 | 可以先固定的參數 | 還需決定 |
|---|---|---|
| 4×4 PE mesh | 可用 128-bit data flit、1 GHz，名義 16 GB/s／方向 | PE/router 對應、L2／VPU／DMA 接入數、路由、multicast 與 FIFO |
| Ring／multi-ring | 可使用同一 rate 做受控比較 | 方向、ring 數、注入點、跨 ring 規則與共享鏈路；不是本稿預設 |
| 其他拓樸 | 容量與端點數相同下比較 | switch 面積、連線成本、仲裁與實際流量，不使用固定效率倍率代替 |

若選 mesh，一個可研究的低複雜度方案是 PE 一對一配 router、L2 先透過邊界 router 的空閒方向接入；16 個 PE routers 不需要因此增加成 16 個 D2D。L2 只有單一 16 GB/s 接入會成為共享瓶頸，不能以「L2 可服務 64 GB/s」宣稱所有 64 GB/s 都能進入 NoC。

**128 bit × 1 GHz＝16 GB/s** 是 data-flit 的原始速率。Header、控制 flits、流控停頓與封包複製另占資源；若 header 與 payload 共用這 128 bit，則有效 tensor payload rate 低於該值。

Router 基本 FIFO 可以先用一個明示的 M 作實驗：每 input 2 個邏輯 VC／traffic classes、每 VC 8 個 128-bit flits，為 `2×8×16＝256 B/input`；5-input router 為 1280 B＝1.25 KiB。**這不是兩文的 router 規格，也不是已證明無死鎖。** 是否使用 VC、請求／回覆分流、multicast 分支與實際 buffer 深度仍需協定驗證；FIFO 面積／漏電要另計，不能包含在未擴充的舊 router 常數中。

## 7. 建議保留、整併與新增的項目

### 7.1 保留

- PE、vector-MAC、ACC、L1、共享 W/A/O L2：職責明確。
- 晶粒層級 Vector Unit：保留，尤其用於 Add／ReLU／requantization；與 PE 的 vector-MAC 分開命名。
- IO chiplet 內的 DRAM controller 與 PHY：保留，能讓 Compute chiplet 專注運算與 D2D。
- Control、DMA、router、D2D：保留，但需要分清功能服務與實體模組。

### 7.2 整併或先移出核心基準

- **不要再自動加舊程式的 8 MiB UB**。若共享 L2 承擔 global-buffer 職責，就採單一容量帳本。若未來確實採額外 UB，需說明 L2↔UB copy、各自頻寬與 lifetime，並重新計容量／成本。
- **區分片內 router 與 NoP router**。如果兩者為同一個實體 switch，不能重複算兩次；如果是兩套網路，必須列出兩者之間的 gateway。
- IO 內部 crossbar 可能就是接入 router 的 switch。名稱不同不代表多一份硬體；不同仲裁層級才分別計費。
- Host／camera 等外部 IO PHY：沒有板級需求時先移出 inference 核心基準；保留未建模範圍的說明。
- 多入口 IO：保留為候選，先不要只因 Gemini 圖上有多 router 就無條件配置、又不計相應 D2D／仲裁成本。

### 7.3 建議新增到清單，但不一定新增大型硬體

| 需要補的項目 | 為何必要 | 首版應寫到的程度 |
|---|---|---|
| Requantization／rounding／saturation | INT24 psum 不能直接當 INT8 activation 傳給下一層 | 量化尺度與 zero point、輸入／中間位寬、輸出格式、cycles／bytes；可由 Vector Unit 承擔 |
| Vector Unit 的算子與性能表 | 一個「Vector Unit」方塊不足以估計 Add／pool／scale 的效能 | 各算子每元素工作量、讀寫格式、是否支援／是否需分解；不支援的算子明確拒絕或計算 fallback |
| PE 工作 registers／ACC 邊界 | 避免把 MAC 裡的暫存狀態當免費或與 OL1 重複算 | 最小 live state、tile 溢出／spill 行為與成本；完整 RF porting 可後補 |
| NI／packetization／endpoint queues | Router 與 PE／DMA／controller 之間需要封包與流控介面 | request/reply/data 類型、payload、routing ID、credit、有限 queue；容量未知就標 T |
| DMA descriptor／task queue | 靜態排程仍需要下發與追蹤搬移工作 | 地址、長度、stride、tag、依賴、完成事件與 outstanding 上限 |
| 記憶體地址映射 | 多顆 DRAM 的容量與 locality 才有意義 | DRAM ID／bank 或抽象目標、interleave 粒度、L2 region ownership；不能讓 data 自動出現在任意 IO |
| 同步與資料有效性 | residual、fusion、跨晶粒 pipeline 必須知道何時可讀／覆寫 | event／barrier／ready-valid／ownership；讀資料、搬移、覆寫次序明定 |
| NoC/NoP flow control 與 deadlock 規則 | 有限 buffers、請求回覆及 multicast 可能互相等待 | routing、virtual networks／VC 或其他機制、backpressure、仲裁、無死鎖檢查 |
| SRAM banking／port 契約 | 容量本身不能推導頻寬 | 每個物理 pool 的 read/write aggregate、與 PE／DMA／VPU 的共享方式；後續取得 macro 後校準 |
| Controller service／refresh／queue | 多個接入 router 不會讓 DRAM 變成多份獨立頻寬 | 所有入口共用同一 controller／channel ledger；延遲、讀寫切換與排隊不能都省略 |

不建議為了「看起來完整」而先加 cache coherence、L3、HBM、通用 CPU cache 或高階 MMU。若首版採 compiler-managed scratchpad、固定地址與顯式傳輸，可先用上述 ownership／同步契約；當作業系統或共享虛擬記憶體成為需求時才另加對應機制。

## 8. 資料流與容量契約

### 8.1 DRAM 讀取與寫回

功能路徑為：`DRAM → IO PHY → controller → IO 網路接入／D2D → NoP → Compute DMA／NI → WL2 或 AL2`，寫回方向相反。這是功能分工，不代表每一段已完成實體 netlist。

多個 IO 接入點仍共享對應的 DRAM controller 與記憶體頻寬；同一 tensor 放在哪顆 DRAM，要由地址／mapping 明定。對中繼 Compute chiplet，若只做 NoP forwarding，應計 router／link 服務，但不因此讀寫其 L2。

### 8.2 晶粒內計算與 Vector Unit

功能路徑為：`WL2/AL2 → 片內互連 → WL1/AL1 → MAC/ACC → OL1 → OL2`；Vector Unit 再依算子讀取 psum／residual／量化參數並寫入輸出區域。若日後加入 PE→Vector Unit 直接 bypass，需新增其 FIFO、仲裁、吞吐與依賴，不能同時享有免費 bypass 與零 buffer 成本。

OL2 同時保存 INT24 psum 與 INT8 最終結果時，兩者的存活區域要分開計算；輸入還未被消費前不能覆寫。A/B 雙槽不保證任何三階段 pipeline 都能零 stall，實際讀寫相依仍需排程。

### 8.3 跨層重用

輸出可以直接保留給下一層或透過 NoP 發給其他 Compute chiplet，不要求每層回 DRAM。但保留資料必須有實際的 AL2／OL2 allocation、valid／ready 狀態、位寬與生命週期。重算、跨 tile overlap、殘差資料都占同一套資源，不能再有不計容量的隱藏 reuse buffer。

## 9. 容量與頻寬核算

本建議基準的單顆 Compute SRAM：

```text
L1 = 16 PE × 2 槽 × (64 + 16 + 8) KiB
   = 2816 KiB = 2.75 MiB

L2 = 512 + 256 + 256 KiB = 1024 KiB = 1 MiB
     （已包含 A/B 兩槽）

主要資料 SRAM = 2.75 + 1 = 3.75 MiB／Compute chiplet
```

Vector 量化參數的 4 KiB 若從 L2 分配，已包含在這 1 MiB 內，不再多加。Control／DMA queues、NI／router FIFOs、RF／ACC registers 的成本要另外列；因此 **3.75 MiB 是主要資料 SRAM，不是完整晶粒儲存元件總和**。

若選擇完全沿用 INDM 的小 L2 版本，則 `2.75 MiB＋176 KiB＝2.921875 MiB`。若另外保留舊程式的 8 MiB UB，才是先前的 `2.75 MiB＋176 KiB＋8 MiB＝10.921875 MiB`。三種方案不能共用同一個數字或宣稱同一面積。

對任一個資料路徑，吞吐受其所有必要服務限制：`資料路徑有效頻寬 ≤ min(DRAM、經過的 links、router、DMA、buffer／NoC gateway 的可用頻寬)`；這不是將所有 component 的 peak bandwidth 相加。VPU 16 G lane-ops/s 與 PE 8.192 TOPS 也只是算術峰值，不能取代位元組流量／排程分析。

## 10. 與現有 INMIN V2 程式的差異

本次只產生規格與審查，沒有修改硬體評估程式。

| 項目 | 目前程式 `homogeneous_mesh_4x4_v1` | 本稿 v0.2 建議／清單要求 |
|---|---|---|
| DRAM controller／PHY | 成本整合到 Compute die；沒有 IO dies | 移到獨立 IO chiplets |
| Compute clock | 500 MHz | 1 GHz 研究目標；500 MHz 作敏感度 |
| 共享 SRAM | 8 MiB UB＋兩槽合計 176 KiB L2 | 建議 1 MiB W/A/O L2，整併 GLB 角色；不另加 UB |
| NoC | 4×4 PE mesh，L2 單一接入 PE0；8.5 GB/s／link | 拓樸仍待確認；rate 建議 16 GB/s；接入點必須寫入規格 |
| 非 MAC 算子 | 目前在 PE 服務模型中計 vector cycles | 若採晶粒獨立 Vector Unit，需重新建模其單獨資源、容量、成本與爭用 |
| 每顆 memory 服務 | 每 Compute 一顆 512 MiB memory、4.6875 GB/s | 每 IO 有 512 MiB 可見容量、固定 8.192 GB/s 服務；IO 數量另定 |
| D2D／NoP | 沒有 IO 的 Compute-only mesh | 加 IO 邊界節點；雙鏈路選項需 multigraph |
| 四個 mapping cores | 軟體資源分組，平分 PE | 可保留為軟體編碼；不要誤當四個實體 Gemini cores |

所以舊版輸出的 PPA、布局與最佳顆數不能直接作為新 IO 架構的結果。若日後實作 v0.2，需更換 profile ID 並重跑；亦須把 buffer、Vector Unit、IO PHY／controller、router 與多鏈路成本同步納入，而不只是換圖。

## 11. 還需要確認的設計決策

我建議先確認以下六項，再把參數凍結成模擬器正式 profile：

1. **共享容量方案**：採本稿 1 MiB W/A/O L2，還是採 INDM 的 176 KiB 雙槽小 L2？是否真的還需要額外 UB？
2. **片內網路**：是否接受 4×4 PE mesh 作固定基準？L2、VPU 與 DMA 用幾個 gateway 接入？
3. **D2D 方案**：每對鄰居單鏈路，還是保留草圖的雙鏈路／多入口？每個藍色區域內有幾個獨立 port？
4. **IO 接入與部署**：是否採簡化的 1 router／IO、左右每列 1 顆 IO？若保留多入口，controller 如何仲裁、接到哪兩個 NoC nodes？
5. **DRAM 模型層級**：先用固定容量＋有效頻寬＋服務延遲做分析，還是立刻選 DDR 標準、通道與具體器件？後者才可決定 PHY／pinout／實體邊長。
6. **Vector／量化範圍**：首版是否只支援 INT8 CNN 的 ReLU／Add／pool／requant？是否需要 Softmax／GELU／其他算子？

這些問題是為了固定資源契約，不需要讓最終使用者逐一調硬體。決定一次後，每顆同型 Compute chiplet 都使用相同配置；最終使用者仍只輸入模型、偏好與限制，由工具決定部署顆數及軟體 mapping。

## 12. 原文核對索引

頁碼以下以使用者提供的 PDF 頁序為準，同時保留印刷頁碼，避免對不到圖表。

| 索引 | 文獻位置 | 本稿使用內容 |
|---|---|---|
| I-A | INDM PDF p.3，印刷 p.1109，Fig. 3、Sec. III-A | PE 與片上組織、L1/L2 職責、IO die 的 controller／PHY、原 cluster 架構；不是直接 Compute mesh |
| I-B | INDM PDF p.5，印刷 p.1111，Table II、Eq. (1)–(3) | 16 lanes、vector size 16、W/A/O 容量公式、乘法器數公式 |
| I-C | INDM PDF p.9，印刷 p.1115，Table IV、Sec. V-A | 1 GHz、INT8／INT24、1/4/16 dies、DRAM 37.5/150/600 Gb/s、D2D 100 Gb/s、片內 68 Gb/s |
| I-D | INDM PDF p.11，印刷 p.1117，Table V | 面積限制配置：16 dies、16 PE、L1_base 8、W:A:O＝8:2:1、L2 ratio 1 |
| G-A | Gemini PDF pp.3–4，印刷 pp.158–159，Sec. III、Fig. 2 | Compute core／chiplet 層級、GLB、獨立 Vector Unit、DMA／Control、IO 功能、多 router 接入、依 core 邊長配置 D2D |
| G-B | Gemini PDF p.9，印刷 p.164，Table I、Sec. VI-A | 1 GHz、organic substrate、GBUF 256–8192 KB/core、NoC 8/16/32/64/128 GB/s、D2D 為 NoC 的 1/4、1/2 或同值、DRAM 0.5/1/2 GB/s per TOPS |

另外注意兩個原文細節：INDM Table II 列出的 L1_base 探索集合與 Table V 報告的 8／16 KB 不完全一致；本稿以 Table V 的已報告配置推算 L1，不宣稱重現其完整 DSE 搜尋集合。Gemini 頻寬組合中的 D2D/NoC 比例也不是本稿 12.5/16 的比例；本稿刻意選取兩篇的不同 anchor 組成新方案，因此不宣稱為任一論文的原始配置。

原始文件：

- 使用者硬體清單：`C:/Users/user/Downloads/Chiplet_Hardware_Spec_v0.1 (1).md`
- INDM：`C:/Users/user/Downloads/INDM_Chiplet-Based_Interconnect_Network_and_Dataflow_Mapping_for_DNN_Accelerators.pdf`
- Gemini：`C:/Users/user/Downloads/Gemini_Mapping_and_Architecture_Co-exploration_for_Large-scale_DNN_Chiplet_Accelerators.pdf`
- [INDM IEEE 原文與 DOI](https://ieeexplore.ieee.org/document/10318183)
- [Gemini 作者版 PDF](https://people.iiis.tsinghua.edu.cn/~gaomy/pubs/gemini.hpca24.pdf)

本稿沒有把不存在於兩篇原文的 DMA queue 深度、SRAM macro port 數、PHY 尺寸或 mm 座標填成論文事實。這些欄位以 T 或 M 明確保留，便於下一次設計確認。
