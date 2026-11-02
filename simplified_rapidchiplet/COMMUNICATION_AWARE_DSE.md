# Communication-aware K mapping / DSE

`run.py` 和 `preference_dse.py` 預設執行同一個 operator-aware Q-learning。
Reference 是 TorchVision ResNet-50 v1.5，batch=1、`[1,3,224,224]`、1000 classes、
FP32 activation/weight。FX + ShapeProp 抽出 175 operators、18 semantic blocks、
4,089,184,256 MACs；人工 `models.json` 的 MiB metadata 不參與新流程。

## 執行

工作區 `.venv` 已安裝 torch 2.7.0+cpu / torchvision 0.22.0+cpu，沒有升級既有
runtime package，也不下載 pretrained weights。從 repository root：

```powershell
.\.venv\Scripts\python.exe .\simplified_rapidchiplet\preference_dse.py --models resnet50 --preference balanced --budget 64 --seed 20260915 --ablation --out .\simplified_rapidchiplet\results\my_run
.\.venv\Scripts\python.exe .\simplified_rapidchiplet\run.py --models toy --max-chiplets 2 --budget 17 --seed 7 --exhaustive-check --out .\simplified_rapidchiplet\results\toy
```

新環境請用 Python 3.12 建立隔離 venv，再安裝 `requirements-graph.txt`。
官方 RapidChiplet root / chiplet / packaging / technology 路徑在
`configs/defaults.json`；缺官方 engine 時會警告並標明 `local_proxy`。
此工作區的最終驗證使用 `official_rapidchiplet`。

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\simplified_rapidchiplet\requirements-graph.txt
cd .\simplified_rapidchiplet
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

支援 `--max-latency-ns` / `--max-area-mm2` / `--max-power-w` / `--ppa-weights L A P`。
FPS 僅由 `1e9 / total_latency_ns` 輸出。`--max-chiplets` 是 N_total 搜尋上限，
每 block 可以重用 hardware IDs；`--assignment-top-k` 是每 active count 的
ordered assignment 上限。`--budget` 計 unique 完整 evaluations，prefix、episodes、
cache hits 分開記；episode 上限可能讓實際 evaluations 小於 budget。

## 物理模型

每 block 動作是 `(N_active, ordered chiplet IDs)`，partition axis 固定 K。
quotient/remainder 分配整數 channels，逐算子 MAC/weights 精確分片。
Conv 從 groups 推 required channels；grouped/depthwise 只讀 relevant groups。
BN/ReLU 保留新的 logical tensor ID/dependency，繼承 PRIMARY layout，沒有新 transfer。

Ownership 為 destination 缺少的 versioned slice 產生 canonical Flow，received slice
保留到 last graph consumer。main/shortcut 同 tensor 去重；Add 按兩輸入的 channel
需求檢查 locality。Flow 帶 tensor、slice、producer/consumer、src/dst、bytes；
所有 network evaluation / timeline / link statistics 共用同一份 Flow。

EXTERNAL image/weights 只記 bytes，沒有 fake C0 endpoint；外部 fetch latency/energy
未建模。SRAM 計所有 live logical activation versions + current operator weights，
output 在 input retirement 前計入，fused versions 偏保守；沒有 eviction，overflow
標 infeasible。Conv/Linear 计 MAC compute；BN/ReLU fused；Add/pool/flatten 的
compute cost 暫為零，明确列 assumptions。

全局 serial FX timeline（shortcut 分支也是 serial），每算子先收齊資料後 compute：

```text
T_compute(op) = max(shard MACs × op_per_mac) / global compute rate
T_comm(event) = max(link bits / official BW) / frequency
             + max(official per-pair path cycles) / frequency
T_total = T_compute + T_intra_block + T_cross_block
```

`network_latency_ns` 只含 intra-block；`transition_latency_ns` 只含 cross-block，互斥。
Rapid average ICI 只為 diagnostic，不加回 E2E。沒有 mapping-specific efficiency。
Directed link load 含零負載鏈路；hop-weighted bytes = sum(link load bytes)。
Utilization 時間基準是完整 serial inference，congested count 是平均所需 rate > capacity。
這是 analytical bottleneck serialization + native path delay，沒有 queue/BookSim、
arbitration、multicast、memory fetch 或 compute/network overlap 模擬。
官方 fixed chiplet/packaging power 包含全部 N_total 和 physical links，沒有 idle gating
或 mapping-sensitive dynamic energy，因此相同 N_total 不一定因 mapping 改變 power。

## 搜尋與對照

REUSE_PREVIOUS / COMPACT / COMM_AWARE 產生 candidates，ordered IDs 決定 K shard
布局。每 N_active 保留 top K，依 first consumer missing bytes × Manhattan hops
排序；這是 boundary lower bound，沒有宣稱整個 block 的 placement 最優。
Families 沒有 reward bonus；全部完整 candidates 使用相同官方 evaluator。

Q-state 包含 N_total、block index、ordered history、live residency/primary owners、
shape/MAC metadata、actual prefix latency、preferences/constraints、evaluator identity。
Cache 納入 model/config、official inputs、local source fingerprints 和 ordered IDs。
Prefix 用完整 graph 的 future users 計算 liveness。TD backup 使用 next-state max
legal-action Q；alpha/gamma/epsilon 在 config。

每 N_total 先一個 uniform 最大合法 N_active initialization episode，budget 不足時只
覆蓋前幾個 N_total；全部同 terminal Q update，之後 epsilon-greedy。
Feasible reward=`1/(1+normalized LAP cost)`；infeasible reward=negative normalized
violation，SRAM invalid 加一個 feasibility violation。選 best 也先看 feasible、再
violation/LAP。沒有 FPS/mode/hop/utilization bonus。Soft scales 固定為單顆 serial
compute、configured max mesh 的官方 area/power；hard limit 取代對應 scale。

Toy exhaustive 限最多 4 chiplets / 3 blocks，逐 state 共用 RL legal generator。
它證明 bounded ordered candidate space 的 optimum，沒有宣稱所有 16! placements
的 global optimum；達 exhaustive cap 直接報錯。
`--ablation` 比較 fixed count/fixed assignment、dynamic count/fixed assignment、
dynamic communication candidates with pure exploration、Q-learning；各列列實際
seed/evaluation count，finite budget 不保證 RL 勝過其他方法。

## 輸出

保留 `best.csv`、`summary.csv`、`chiplet_results.csv`、`report.html`；新增
`mapping_trace.csv` / `mapping_plan.json`、`canonical_flows.csv/json`、
`transition_traffic.csv`、`operator_trace.csv/json`、`communication_events.json`、
`ownership_trace.json`、`per_link_statistics.csv`、`search_history.csv`、
`search_result.json`、`model_metadata.json`、`config_snapshot.json`、
`assumptions.json`、`run_manifest.json`，以及 flag 開啟時的
`exhaustive_vs_rl.csv/json` 和 `ablation.csv/json`。

HTML 可選 block 檢視 active physical chiplets，提供所有 traces 的連結。
Manifest 記 source/native hashes、package versions、seed、settings/profile、
unique/prefix evaluations 和 Q entries；完整驗證在 `results/communication_aware_validation/`。
Generated outputs 為 ignored；沒有 commit/push。

## 歷史相容

原六個人工 workloads / pipeline DP/brute-force / semantic-group RL 保留供歷史比較，
必須加 `--legacy`：

```powershell
..\.venv\Scripts\python.exe run.py --legacy --models shufflenet_v2_x1_0 --ppa-goal balanced --workload-search pareto-dp --dp-top-k 12
..\.venv\Scripts\python.exe preference_dse.py --legacy --models resnet50 --budget 8
```

Legacy abstraction 不能當新 operator model。其他 CNN exact parser、IC reduction、
spatial H/W、DRAM endpoints 留待後續，本次預設只支援 ResNet50 和 explicit toy。
