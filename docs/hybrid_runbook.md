# INDM + Gemini + RL：執行與結果檢查

新入口是 `simplified_rapidchiplet/hybrid_dse.py`。硬體、mapping、排程、learned policy 都在 `simple_rapidchiplet/hybrid/`，與先前 phase 規劃獨立。完整設計見 [hybrid_architecture.md](hybrid_architecture.md)，方法核對見同目錄的 source notes。

## 在此工作區執行

以下 PowerShell 指令從 `C:\Users\user\Desktop\rapidchiplet` 執行。使用既有 `.venv`，shape frontend 需要 torch/torchvision；搜尋使用 numpy。Native RapidChiplet 預設讀取本機 `C:\Users\user\Downloads\rapidchiplet-main (2)\rapidchiplet-main`，不同安裝位置使用 `--rapid-root`。

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --help
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model toy --batch 4 --weights persistent --trace --out simplified_rapidchiplet/results/hybrid_toy
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode search --model toy --budget 128 --method rl --proposal cluster_guided --out simplified_rapidchiplet/results/hybrid_toy_rl
```

`balanced` 初始規劃依整數 SIMD cycles、完整收到資料的 UB 容量壓力配置 core 與 B/K/H/W partition。`--planner beam --planning-budget 4` 另外產生 grouping/microbatch 候選，再用完整物理 oracle 排名。Proposal 的 delay/energy 是剪枝估計，不代替最後 PPA，也不宣稱全域最優。外層 graph/microbatch 決策與 Gemini 五個空間 operators 分開。

可用 `--workload path/to/workload.json` 載入自己建立或之前輸出的 workload（取代 model/batch），或從 Python API 的 `from_operator_graph()` 匯入其他模型的已支援 operators。JSON 載入會核對 DAG/shape/MAC metadata；未支援算子與非INT8資料不會靜默套用此成本 profile。

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model resnet50 --batch 1 --groups 3 --out simplified_rapidchiplet/results/hybrid_resnet_b1
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model resnet50 --batch 8 --groups 3 --weights persistent --hardware simplified_rapidchiplet/configs/hybrid_pipeline_4MiB.json --out simplified_rapidchiplet/results/hybrid_resnet_b8
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode compare --model toy --budget 128 --seeds 7,8,9 --out simplified_rapidchiplet/results/hybrid_baselines
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode architecture --model toy --budget 32 --out simplified_rapidchiplet/results/hybrid_architectures
```

容量驗證也提供 `configs/hybrid_pipeline_4MiB.json`：每die unified SRAM增加到4MiB，重新導出native area/placement/idle power。2MiB是預設容量，已驗證特定batch1 mapping合法，其他mapping/batch必須檢查feasible；請使用合法結果，而不是把超容量run當加速。

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode evaluate --model resnet50 --batch 8 --groups 3 --weights persistent --hardware simplified_rapidchiplet/configs/hybrid_pipeline_4MiB.json --out simplified_rapidchiplet/results/hybrid_resnet_b8_4MiB
```

`--mode architecture` 在相同總 MAC/PE/core/L1/L2/UB/DRAM 容量與 DRAM 頻寬下比較 4/8/16 dies 和 multi-ring/mesh。每個候選都重算 IO、PHY、controller、placement 和 native 路由；不跨架構比較「相對各自初始 mapping」的 search cost。`--area-weight`/`--power-weight` 可加入共同單位的外層目標，`--max-area`/`--max-power`/`--max-latency` 是硬限制。

## Checkpoint 與額度恢復

每個 search trial 自動寫 `checkpoint.json`。它保存 actor/value weights、RNG、current/best plan、固定 reference scales、cache、計數與 trace。增加累積 budget 並加 `--resume`：

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/hybrid_dse.py --mode search --model toy --budget 256 --method rl --proposal cluster_guided --resume --out simplified_rapidchiplet/results/hybrid_toy_rl
```

必須保留 workload、硬體、window、proposal、seed 與其他 search 設定；程式/native source hash 改變會拒絕混用 checkpoint。Hourly heartbeat 是本次交付的接續安排，完成後會停止；它不修改 search 預算或繞過帳號限制。

## 如何讀結果

每個 run 保存：`summary.json`（PPA/energy/feasibility）、`mapping.json`、`hardware.json`、`network.json`（native source hash、rates、area）、`workload.json`、`buffers.json`、physical placement `package.svg`、資源/依賴 `timeline.csv` 與 `link_traffic.csv`。Search 另有 `search.json`/`checkpoint.json`；`--trace` 才輸出較大的 `trace.ndjson`，其中包含整數 ownership、tensor regions、transfers、每個 core 的內部 bank/ring 證據。這些檔案可檢查每個估計的來源。

`latency_s` 是整個固定 batch 的 makespan；`first_result_latency_s` 是第一個 microbatch 的所有 model outputs 完成時間。`energy_j` 是整批 dynamic energy + idle power×makespan，`power_w` 是平均值；`area_mm2` 是所有 dies 的 silicon area，`package_area_mm2` 是封裝占地，兩者分開。EDP 是整批 energy×makespan。

`feasible=false` 時要讀 `violations`。資料不能因 C tiling 而從 UB 消失；full received regions 保留到消費 unit 完成，作內部 streaming backing。`persistent` 只重用有 exact tensor/region/endpoint 對應的 weights，第一次 load 與保留容量均计入；不會自動 spill 超容量候選。`cold` 是明示不跨 tiles/microbatches 保留權重的 ablation。Multicast 共用 physical route prefix；unicast/ring 為額外對照。

## 模型的實際範圍

本實作是 communication-aware 分析模型。原生 RapidChiplet 提供 NoP geometry/PHY/router/wire latency、bump ceiling、silicon/package area 和 idle power；本專案估 compute、banked SRAM/NoC、DRAM、pipeline/collective service 與 operation energy。SRAM/能量/面積係數是論文与 source 啟發的未校準 profile，不能當量測晶片 PPA。INT8/INT24 是唯一目前成本 profile；FX 用 FP32 做 shape extraction，不代表已驗證量化 accuracy。

Native silicon/idle值由本專案提供的die dimensions、placement與leakage inputs聚合；Rapid沒有獨立校準SRAM/PE成本。Package合法XY路由由adapter建立，再用native path公式評估。目前沒有yield/美元製造成本模型。部分provenance字串固定記錄default profile來源，variant數量以numeric hardware/resources為準。

片內 microkernel 遵守 AL/WL/OL 分 bank 容量，保留各 PE 的 partial sums；bank miss 由計入容量的 UB backing refill。片外與片內服務採 atomic region/phase 投影與 deterministic priority list resource-calendar scheduling，不包含 packet VC/arbitration，也不宣稱 RTL cycle accuracy 或最優排程。Window 限制每 group 同時在途 microbatches；容量仍由完整 live residency 檢查。

## 驗證

```powershell
$env:PYTHONPATH='simplified_rapidchiplet'
.venv\Scripts\python.exe -X utf8 -m unittest discover -s simplified_rapidchiplet/tests -p 'test_hybrid_*.py' -v
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet/scripts/run_hybrid_search_validation.py --budgets 64,128 --seeds 7,8,9 --out simplified_rapidchiplet/results/hybrid_search_validation_reproduction
```

同 budget 比較使用實際 oracle、同 initial mapping/硬體/候選上限、不同 trial cache。Budget 是 unique mapping evaluations，初始 mapping 也占一次；cache hit 與 requests 另報。RL policy 更新與 exact checkpoint resume 有行為測試；RL 是否勝過 baseline 必須看實驗，不能由使用了 RL 就推論。

本次已完成的同預算結果在 `results/hybrid_search_validation_final/`，包含3 seeds、4 methods、uniform/cluster_guided兩種proposal與64/128 queries。`hybrid_search_validation_rl512/`是只延長RL到512 queries的補充曲線，不可拿來對128-query baselines宣稱公平優勝。完整結果與可行性限制見 [hybrid_validation.md](hybrid_validation.md)。

完整ResNet驗證工具：`tools/validate_hybrid_resnet_architectures.py`比較六個硬體的balanced初始mapping；`tools/check_hybrid_mapping_feasibility.py`保存2MiB容量診斷；`tools/check_hybrid_mapping_capacity.py`讀取已保存mapping，再評估4MiB cold/persistent；`tools/check_hybrid_resnet_searches.py`做每method八個design queries的整合smoke。這些工具保留source hashes、runner hashes、native context與公平比較條件。Matplotlib圖表用 `tools/plot_hybrid_validation.py`從JSON/CSV重建，輸出PNG/SVG，不是手動填數字。

可選batch8 temporal、逐layer配置產生4,665個normalized microkernel keys，超過固定4096-entry LRU，會反覆重算；本次該長基線未完成，不能據此提供pipeline speedup。模型的數值成本與memo加速分開；目前不提供此配置的高效搜尋承諾。
