# INDM＋Gemini＋RL：實作與驗證結果

本次交付依使用者2026-10-05的新目標建立，取代先前phase 1–10作為前進方向。新程式入口為 `simplified_rapidchiplet/hybrid_dse.py`，核心位於 `simple_rapidchiplet/hybrid/`。已完成IO-cluster mesh、capacity-backed multi-ring/mesh、layer-group/microbatch pipeline、Gemini五個空間operators的learned RL、native RapidChiplet整合、容量與energy ledger、可重現搜尋與報告。

這是一個可執行、可檢查的communication-aware研究原型。PPA係數尚未經RTL或silicon校準。下列數字均是同一最終程式的分析結果，並非兩篇論文的性能復現。

## 建議先讀與執行

- [完整硬體、mapping與評估契約](hybrid_architecture.md)
- [PowerShell指令、輸出、checkpoint與限制](hybrid_runbook.md)
- 方法來源：[INDM硬體](hybrid_hardware_source_notes.md)、[Gemini論文與C++](hybrid_gemini_source_notes.md)、[mapping/planner](hybrid_mapping_source_notes.md)
- 可直接檢查的範例：[toy完整輸出](../simplified_rapidchiplet/results/hybrid_toy_final/summary.json)、[physical placement](../simplified_rapidchiplet/results/hybrid_toy_final/package.svg)、[tensor/core trace](../simplified_rapidchiplet/results/hybrid_toy_final/trace.ndjson)

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model toy --batch 4 --weights persistent --trace --out simplified_rapidchiplet/results/my_hybrid_toy
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode search --model toy --method rl --budget 128 --proposal cluster_guided --out simplified_rapidchiplet/results/my_hybrid_rl
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model resnet50 --batch 8 --groups 3 --weights persistent --hardware simplified_rapidchiplet/configs/hybrid_pipeline_4MiB.json --out simplified_rapidchiplet/results/my_hybrid_resnet
```

## 融合方法與實作範圍

INDM提供實體層級：compute dies連到IO cluster，IO形成mesh，DRAM由各cluster的controller服務；片內以multi-ring服務PE與W/A/O buffers。Gemini提供layer encoding的Part/ordered CG/FD、跨microbatch的layer pipeline、graph cuts與architecture/mapping co-exploration。RL選擇mapping mutation，完整物理oracle提供reward。

本專案增加三個可辨識的算法extension：容量/整數SIMD-aware balanced allocation；保留graph-cut/microbatch多樣性的bounded beam；依實體cluster位置與producer-consumer需求提出候選的cluster-guided policy。OP4另外允許idle-pool acquire/release及nearest-legal resize，避免prime core-count把搜尋卡住。這些extension對所有baseline開放，並非宣稱是論文原始算法。

Layer grouping與microbatch規劃在五operators之外。五個operators分別改Part、同layer ordered-core swap、跨layer core swap、core重分配、DRAM selector。RL是有state/action features、learned actor/value weights的numpy線性actor-critic；不把random或SA重新命名為RL，也未實作GNN或跨模型預訓練。

本次讓topology follow communication pattern的做法，是外層在有成本的4/8/16-die與片內ring/mesh候選之間選architecture，再依實際幾何搜尋mapping。RL目前不直接修改實體links。Package始終採IO-cluster mesh；這符合本次硬體方向，也讓RapidChiplet可合法評估。

## 硬體與評估分工

預設16-die profile：16 compute＋4 IO＋4 DRAM，2×2 IO mesh；每compute die 16 PE、4 mapping cores、4個4-PE單向rings。每PE是16 lanes×16 INT8 MAC，1GHz；總65,536 MAC/cycle，即65.536 TMAC/s或131.072 decimal TOPS。INT8 activation/weights、INT24 partial sums。

PE L1 W/A/O為64/16/8KiB；die共享L2為64/16/8KiB。Unified SRAM預設2MiB/die，合法batch8配置採4MiB/die。NoP為每方向每link12.5GB/s，NoC8.5GB/s；總DRAM75GB/s、8GiB，IO crossbar50GB/s/cluster。完整容量與port bandwidth見架構文件及每個run的numeric `hardware.json`。

RapidChiplet以adapter提供的合法XY routes、die dimensions、placement和idle-power inputs，計算native NoP path latency、bump bandwidth ceilings與area/power聚合。本專案計算compute、獨立AL/WL/OL banks、UB residency/refill、NoC、DRAM、collective/pipeline contention和operation energy。Area/leakage參數由本專案未校準profile提供，Rapid沒有獨立校準SRAM成本。Total energy＝dynamic operations＋idle power×batch makespan；average power＝total energy/makespan。

## 驗證與來源一致性

全回歸 **143 tests PASS**，其中 **69 hybrid tests PASS**。完整log在 [hybrid_unittest.txt](../simplified_rapidchiplet/results/hybrid_unittest.txt)。覆蓋PHY/port/overlap與typed routing、integer output/MAC守恆、halo/grouped/depthwise/residual、DRAM ownership、multicast共享prefix、independent-bank容量、uneven PE port load、UB/DRAM lifetimes、排程依賴/資源互斥、energy ledger、非法action與checkpoint。

Pipeline手算驗證：兩stage服務時間2與3，四microbatches的fill/drain使總makespan為14，而逐batch串行為20。這驗證排程行為，不是完整ResNet的pipeline speedup測量。Macro units的read/compute/write依序服務；不同cores、microbatches可依真實resource calendar重疊。

CLI evaluate/search/beam/import/architecture、full trace與JSON workload/mapping round-trip均通過。實際oracle的8-query連續run與4→8 resume比對，search trajectory、plan、physical metrics及policy均exact equal；checkpoint保存RNG與固定reference，source/native/hardware/window改變會拒絕混用。

正式搜尋使用的source identity為 `558f718b91136b09fe68028921bb45e3c6deb565a066e7440244bdbdff8114c7`；結果另保存各Python模組SHA256、workload/hardware/evaluator identities及native hashes。正式資料使用以下列出的final目錄。`prefreeze`、舊 `hybrid_architecture_validation` 與早期 `hybrid_mapping_feasibility.json` 不納入本報告。

## 完整ResNet50：容量、權重重用與成本

Shape frontend使用torchvision ResNet50 v1.5，單consumer BN/ReLU fusion後73 layers。每sample精確4,089,184,256 MAC；batch8共32,713,474,048 MAC。FP32 FX只取shape，執行模型採INT8資料流profile，沒有量化accuracy主張。

使用相同g3 graph groups、microbatch1、admission window2與mapping，比較cold/persistent weight policies；新增容量時保留原plan，只更改硬體UB與重新評估native placement/area/idle。Cold與persistent的Part、CG、FD與group cuts相同，差別只有weights retention。

| Case | 容量/die | 可行 | Batch latency | Batch energy | Peak UB/die |
|---|---:|---|---:|---:|---:|
| Batch1，cold | 2MiB | 是 | 6.4138ms | 65.410mJ | 1,073,760B |
| Batch8，cold | 2MiB | 否 | 不評改善 | 不評改善 | 3,682,912B |
| Batch8，persistent | 2MiB | 否 | 不評改善 | 不評改善 | 3,682,912B |
| Batch8，cold | 4MiB | 是 | 34.7303ms | 508.599mJ | 3,682,912B |
| Batch8，persistent | 4MiB | 是 | 28.8940ms | 472.101mJ | 3,682,912B |

在兩邊都合法的4MiB配置，persistent降低batch latency **16.80%**、batch energy **7.18%**、DRAM read **62.63%**。完整weights的第一次load與最後reader前的buffer lifetime均計入；没有免費cache。

2MiB失敗只指這個16-die g3/window2 plan，不能推論所有32MiB總容量的硬體/mapping都無法跑batch8。例如4-die的8MiB/die或8-die的4MiB/die iso-total候選，重新group/map後可能改變共享存活峰值；本次未測它們的batch8。

| Traffic / energy | Cold | Persistent | 解讀 |
|---|---:|---:|---|
| DRAM reads | 285,058,560B | 106,538,176B | 降62.63% |
| DRAM writes | 80,506,688B | 80,506,688B | group boundaries相同 |
| Weight reads | 204,023,296B | 25,502,912B | 降87.5% |
| NoP byte-hops | 1,548,498,296 | 902,254,264 | 實體interdie traffic降低 |
| NoC byte-hops | 3,249,766,864 | 3,249,766,864 | 內部bank/refill相同，未下降 |
| Estimated idle energy | 93.372mJ | 77.681mJ | 相同idle power，較短makespan |
| Average power | 14.644W | 16.339W | 能量下降不代表平均power下降 |

容量增加總UB32→64MiB，付出silicon area **190.522→216.399mm²**、package footprint **231.143→260.199mm²**、estimated idle **2.162→2.688W**。它不是相同總SRAM預算的免費改善，也不等同下面8-die iso-total候選的4MiB/die。

完整資料：[hybrid_mapping_capacity_validation.json](../simplified_rapidchiplet/results/hybrid_mapping_capacity_validation.json)。內含plan fingerprints、每row完整hardware/window/native context、energy ledger、source-stable證據，以及不合法2MiB診斷。

![ResNet capacity/reuse comparison](../simplified_rapidchiplet/results/hybrid_figures/resnet_mapping.png)

## Architecture partitioning：完整模型與小模型結果不同

六候選守恆256 PE、64 cores、22MiB L1、1.375MiB L2、32MiB UB、8GiB DRAM與75GB/s DRAM頻寬。4/8/16 compute dies搭配1/2/4 IO clusters；每die的PE/core/ring/UB相應改變。IO/PHY/link geometry重新計成本；聚合NoP、IO crossbar及L2/UB服務頻寬隨實體資源複製數變化。

下表是完整ResNet50 batch1、cold weights、同一balanced初始化規則，**每個候選未追加RL optimization**。所有候選合法，沒有把各自相對initial EDP拿來跨硬體比較。

| Compute dies | 片內 | Silicon area | Latency | Energy | EDP (mJ·s) |
|---:|---|---:|---:|---:|---:|
| 4 | Multi-ring | 176.010mm² | 10.3165ms | 70.953mJ | 0.73199 |
| 4 | Mesh | 177.562mm² | 14.4279ms | 83.195mJ | 1.20033 |
| 8 | Multi-ring | 180.579mm² | 7.7373ms | 66.539mJ | 0.51483 |
| 8 | Mesh | 182.275mm² | 9.5616ms | 72.765mJ | 0.69575 |
| 16 | Multi-ring | 190.522mm² | 6.4138ms | 65.410mJ | 0.41953 |
| 16 | Mesh | 192.506mm² | 6.9368ms | 68.112mJ | 0.47248 |

在這個模型、配置與初始化中16-die multi-ring的EDP最低；小residual toy在每architecture RL16 queries的另一個protocol則偏好4-die。這支持依workload做partition/mapping共探索，不代表multi-ring普遍優於mesh或16 dies是全域最優。

原始資料：[完整ResNet comparison](../simplified_rapidchiplet/results/hybrid_resnet_architectures/comparison.json)、[toy architecture experiment](../simplified_rapidchiplet/results/hybrid_architectures_final/experiment.json)。两套protocol不同，僅用於各自候選內比較。

![Full ResNet architecture comparison](../simplified_rapidchiplet/results/hybrid_figures/resnet_architecture.png)

## 同預算RL與baseline

Residual toy，3 seeds（7/8/9）×4 methods×2 proposal policies＝24 independent trials；累積64/128 unique mapping evaluations，初始mapping占一次。所有methods共享initial plan、hardware、objective、action空間與候選上限，full evaluator/search caches各自獨立。Cluster-guided與uniform分開比較。數值為fixed initial whole-batch EDP比值，越小越好；±為sample standard deviation。

| Proposal | RL | Random | Greedy | SA |
|---|---:|---:|---:|---:|
| Uniform，128 queries | 0.54877±0.08477 | 0.60139±0.26576 | **0.37318±0.03089** | 0.48443±0.08712 |
| Cluster-guided，128 queries | 0.42059±0.13422 | 0.68166±0.17695 | **0.32802±0.06163** | 0.56536±0.24546 |

RL學到可以降低initial EDP的mapping，cluster-guided提高這三seed的RL平均表現，但**greedy目前平均最好**。Guided不是對所有methods都更好；只有3 seeds，不作顯著性、泛化或RL優越性主張。

例如guided RL seed9@128把初始52.186µs/120.523µJ降到26.344µs/63.419µJ，EDP比0.26563。NoC byte-hops249,536→159,424，而NoP66,144→68,288略增，logical/DRAM bytes相同。主要energy改善包含較短runtime的idle energy；**不能把所有EDP改善都稱為interdie traffic降低**。

完整protocol、curves、checkpoints與統計：[hybrid_search_validation_final/summary.md](../simplified_rapidchiplet/results/hybrid_search_validation_final/summary.md)、[validation.json](../simplified_rapidchiplet/results/hybrid_search_validation_final/validation.json)。

![Equal-budget search comparison](../simplified_rapidchiplet/results/hybrid_figures/search_curves.png)

RL-only512延長曲線保存在 `results/hybrid_search_validation_rl512/`；它從同source128 checkpoints接續，目的為檢查learning progress，不與128-query baselines做公平優勝比較。

六個RL延長trials已全部完成：uniform在128→512 queries的平均EDP比0.54877→0.36763，cluster-guided為0.42059→0.32285，512的sample SD分別0.14436/0.15683。這表示仍有learning/search progress，但512-query random/greedy/SA未測，不能據此判定RL優勝。補充統計見 [RL512 summary](../simplified_rapidchiplet/results/hybrid_search_validation_rl512/summary.md)。

完整ResNet batch1四methods各8 unique queries、seed7、同initial mapping/PPA、persistent weights的整合smoke已完成：

| Method | Best EDP / initial | Latency | Energy | Policy updates |
|---|---:|---:|---:|---:|
| RL | 0.9990183 | 6.4082ms | 65.403mJ | 7 |
| Random | 0.9985395 | 6.4132ms | 65.321mJ | 0 |
| Greedy | **0.9863041** | 6.3390ms | 65.275mJ | 0 |
| SA | 0.9985395 | 6.4132ms | 65.321mJ | 0 |

這驗證完整DNN可經RL/operator/native oracle流程執行，不證明收斂或算法優越性。Greedy此小smoke也最佳。原始資料：[hybrid_resnet_search_validation/validation.json](../simplified_rapidchiplet/results/hybrid_resnet_search_validation/validation.json)。

## 尚未涵蓋的範圍與下一步

片內使用byte-bounded whole-region LRU與integer microkernels；macro read/compute/write是明示phase projection，沒有細粒度streaming overlap credit。片外multicast採union directed edges的atomic region service。Scheduler是deterministic priority list、共用resource calendars，不含packet VC/arbitration，不宣稱最優或cycle accurate。MAC/SRAM/PHY/router/DDR/leakage係數需獨立校準；MAC0.192pJ是INDM表中0.024pJ/bit×8的明示假設，單位存在來源歧義。

Policy看package/IO/DMA壓力，尚未逐ring觀察NoC壅塞；沒有跨模型訓練驗證、量化accuracy、實體link RL edits、yield或美元製造成本模型。部分export provenance字串固定記default來源，非預設配置以numeric hardware/resources為準。

Vector/post-op已有integer cycles與SRAM/NoC accesses，但尚無獨立vector-ALU動態能量係數；MAC ledger只計MAC，不能稱為所有算術的gate-level能量。本次batch8的314,101,760 vector ops另保留作workload counts。

可選batch8逐layer temporal baseline已停止，沒有完成PPA，因此本次**不提供完整ResNet的pipeline-vs-temporal speedup**。只讀診斷發現37,320 units、4,665 normalized microkernel keys超過4096-entry LRU，microbatch外層遍歷造成重算；g3為12,792 units、1,599 keys。這是evaluator runtime限制，與硬體性能分開。主機約03:35至08:16暫停，平行jobs也共享CPU，因此wall time不能當算法效率比較。

接下來適合研究：校準on-die/resource overlap與PPA係數；擴大多模型/多seed、同預算RL訓練與greedy-warm-start ablation；把逐ring busy與dependency message passing納入policy；改善pure-service遍歷/cache以讓長temporal基線可完成。本次沒有用這些未實作功能支撐任何性能主張。

## 交付稽核

[hybrid_delivery_manifest.json](../simplified_rapidchiplet/results/hybrid_delivery_manifest.json)記錄final程式/native hashes、必要驗收、補充RL512與未完成的可選baseline，以及主要artifact SHA256。可在不重跑DNN的情況下核對來源、結果完整性、energy/EDP守恆與已保存toy資源日曆：

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/tools/audit_hybrid_delivery.py
```
