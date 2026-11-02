# inmini V3

INMIN v0.3：每 Compute 16 PE、共享 1 MiB L2、無實體 Core；搜尋 1～16 全部整數 Compute 與 50 種完整矩形布局。

- [本輪實作與重現指令](docs/INMIN_V03_IMPLEMENTATION.md)
- [進度與背景實驗](docs/inmin_v03_progress.md)
- 程式入口：`simplified_rapidchiplet/single_array_dse.py`；GUI：`simplified_rapidchiplet/hybrid_gui.py`
- [112項穩定驗收](research_results/v03/acceptance_result.json)
- [R18新起點驗證](research_results/v03/resnet18_seed_probe_summary.json)
- [v0.2歷史比較報告](research_results/RESEARCH_REPORT.md)，不能當成v0.3結果。

## 本輪修正

候選級target bottleneck特徵、memory pressure引導C7/C8、獨立有價A12 dataflow切換、容量篩選segment beam與prefix checkpoint、獨立seed/search時間、機率/entropy/觀察紀錄、精確通訊索引/路徑快取與compact evidence匯出。

預設standard：seed最多7200秒、另保留search7200秒；單oracle最多1800秒。完整PPA上限128含common seed；每方法都計seed實際成本。舊profile/schema與結果保留。

## 已驗證與待完成

112 tests通過且source_stable=true。ResNet18開發probe的新DP起點可行：22.6611→20.5577ms，26.1231→17.3965mJ；這是seed收益，不歸功RL。新版代表模型公平比較仍在背景執行，尚未宣稱v0.3 policy優於對照。

PPA為未校準的顯式資源分析；未執行native RapidChiplet、原Tangram完整DSE或Gemini原始評估器，也不是silicon量測。M/T與限制見技術文件。

使用者提供的nn_dataflow參考碼與BSD-3-Clause LICENSE保存在`third_party/nn_dataflow_reference/`；INMIN參考其segment/cache/top-N方法，不套用其Eyeriss物理成本。

虛擬環境、圖片、快取與大型實驗中間檔未納入。使用者要求維持自動續作排程暫停；既有有限背景批次會繼續。
