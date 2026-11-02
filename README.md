# inmini V3

INMIN v0.2：16 PE per compute chiplet、共享 1 MiB L2、無實體 Core 的 bottleneck-aware RL 設計探索。

- 程式：`simplified_rapidchiplet/`
- CLI：`simplified_rapidchiplet/single_array_dse.py`
- GUI：`simplified_rapidchiplet/hybrid_gui.py`
- 安裝與重現：[技術說明](docs/INMIN_V02_IMPLEMENTATION.md)
- 規格：`docs/specs/`
- [文字與數字實驗報告](research_results/RESEARCH_REPORT.md)
- 驗收：103 tests passed，見 `research_results/acceptance_result.json`

## 目前結果

|模型|Random 改善%|Greedy 改善%|atomic RL 改善%|bottleneck-aware composite RL 改善%|
|---|---:|---:|---:|---:|
|ResNet18|1.3057|0.6809|1.3228|0.0000|
|ResNet50 v1.5|0.1938|0.3523|5.7461|0.1938|
|MobileNetV2|0.0000|2.1835|0.0000|0.0000|

改善相對共同最佳已驗證種子，為 balanced PPA 綜合成本。每方法同為3600秒與128完整PPA上限，但實際完成查詢數不同；只有Seed7，不構成統計保證。目前結果不支持 bottleneck-aware composite RL 穩定優於對照。

PPA為未校準的Python顯式資源分析，未執行native RapidChiplet，不是晶片量測。所有M/T假設與未實作能力見技術說明。固定Mapping的Fusion補充對照與最終審計仍在整理，這是上傳時快照。

虛擬環境、快取、Git歷史、圖片及大型checkpoint/中間檔未納入。
