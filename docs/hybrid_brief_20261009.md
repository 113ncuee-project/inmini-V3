# 最新三頁報告與圖像化架構

更新：使用者追加整體架構總覽頁，最新交付改為 `output/brief_20261009_v2/Chiplet_DSE_4slides.pdf`／`.pptx`。第1頁為整體系統圖，原三頁順移為第2～4頁；對應講稿及圖檔在同一v2資料夾。原三頁版保留。

日期：2026-10-09。以目前 `literature16_v1` hybrid 實作為準，沒有改動程式、硬體參數或已凍結的完整模型結果。

- 三頁報告：`output/brief_20261009/Chiplet_DSE_3slides.pdf`、`.pptx`。
- 逐頁講稿：`output/brief_20261009/speaker_notes.md`。
- PPA 分工說明：`output/brief_20261009/ppa_explained.md`。
- 更新的整體系統圖：`output/brief_20261009/system_architecture.png`。
- 硬體資源圖：`output/brief_20261009/hardware_architecture.png`。

內容順序是硬體資源、跨層資料搬移規劃、PPA 評估與多模型決策。承接 INDM 的 cluster／ring、Gemini 的 pipeline／operators；本專案延伸以 whole-DAG live-frontier 規劃和實際 region／路徑／排程整合、多模型 strict／soft／closest 決策說明，不宣稱已證明學術新穎性或 RL 普遍優於其他搜尋。

硬體圖展示 actual 16-die benchmark 配置：2×2 clusters、每 cluster 四個 compute dies、一個 IO、一個 DRAM endpoint；每 compute die 4 cores／16 PE／4 rings，PE為16 lanes×16 INT8 MAC，INT24 psum。全系統256PE、64cores、500MHz、總UB128MiB、DRAM8GiB／75GB/s。L1/L2雙scratch slots，UB不倍增。

圖片是生成的資源／概念示意，不是実體 ASIC floorplan。晶片數量和配置已按实际 `hardware.json` 核對；細部匯流排和 ring injection 畫法為簡化，原生結果的真實幾何與每次映射仍看原本的 `package.svg`、`die.svg`、`layout.html`。舊 deterministic 圖和其 source SHA／封存檔不覆寫。

目前 final PPA 仍使用原生 RapidChiplet。HardwareSpec 先提供各die資源成本與idle；RapidChiplet負責幾何、面積加總、路徑延遲／bump ceiling；自寫分析模型計算MAC、memory／fabric動態能量與完整排程。Latency為batch makespan，Power為總能量除以時間，Area為total silicon。搜尋 proposal proxy不是final PPA；目前沒有學習式PPA surrogate。成本假設與實體signoff邊界詳見 `hybrid_cost16_sources.md`。
