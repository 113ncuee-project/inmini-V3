# 2026-10-31 改版驗證紀錄

## 執行結果

- 完整新舊回歸 **231 tests / OK**；記錄：`output/rl_dse_20261031/full_unittest_release.log`。使用 workspace TEMP、正確 `simplified_rapidchiplet` cwd 與本機 API 可存取的執行環境。先前的錯誤 log 保留，不作通過證據。
- 獨立的 joint RL、原子／複合交易、真硬體 A9 擴縮、GLB 單 port、Tangram 與 production PPA 驗收共 **39 tests / OK**；記錄：`acceptance_final/result.json`。
- GLB 修正後正式 **18 runs**：5 種策略×3 seeds 的 variable-hardware 組，加 3 seeds 的 fixed-count-4 控制組。每組都使用 16 次 RL unique full queries；18/18 找到本測試設定的嚴格可行方案，全部來源在各 run 內穩定，跨 run 僅一個 source manifest。
- 獨立稽核全部通過：reward 差值、實際 behavior probability、macro 多 edits、平均 P=E/T、硬限制、seed＋RL＋report 的真 backend 完整評估次數一致。正式證據在 `ablations_final/independent_audit.json`。
- ResNet-18 **224×224 / batch 1** 在完整 Gemini evaluator 上完成 Tangram seed＋RL C4 協同分割 smoke：固定 4 compute chiplets、1×4 模板、2 次 RL queries、1 次 policy update；延遲 **1.255806 ms**、平均功率 **10.943269 W**、總矽面積 **127.739267 mm²**、能量 **13.742625 mJ**。此為極小搜尋預算的執行驗證，不是最優性能基準。記錄：`resnet18_224_final/`。
- GUI 透過真實瀏覽器提交 Toy residual 搜尋，確認完成狀態、最佳可行推薦、PPA、2×2 完整 core、模型 layer 篩選、DRAM→IO→core 路徑及兩條實體 link 高亮；瀏覽器沒有 JavaScript errors。結果與截圖在 `gui_final/`、`gui_report.png`。

## 消融結果與能下的結論

所有變體共用完整 evaluator、相同初始化與 RL query ceiling；初始化與報告重播另行計帳。實際 wall time 有記錄，沒有聲稱固定 wall-clock。fixed 與 variable hardware 的可行域不同，成本不能跨組直接比較。

| Variable hardware / 3 seeds | 最佳可行成本均值 | 標準差 |
|---|---:|---:|
| Atomic RL | 0.953087 | 0.041365 |
| Guided atomic RL | 0.953087 | 0.041365 |
| Composite RL | 0.991697 | 0.014382 |
| Composite random | 0.991697 | 0.014382 |
| Composite greedy | 0.973160 | 0.000000 |

這些小 Toy 實驗沒有顯示 RL 優於 random，也沒有顯示複合動作優於原子動作。實驗驗證了可執行性、限制、交易與記帳，沒有證明大模型搜尋品質或全域最優。C1 未在此小例子被觸發，C9 有提出但未被選中，C10 為關閉的可選功能，不能宣稱有它們的實驗改善證據。

## 最後的呈現修正與來源邊界

正式消融後只修改了 `rl_report.py`、`visualization.py`：DAG 圖補上 model input 節點，讓 residual/Add 的外部支路也可見；路徑文字補上逐 core hops；mesh 標籤明確區分 chiplet grid。這兩檔不參與物理 evaluator、候選生成或 RL 選擇，所有硬體／mapper／scheduler／RL 與 `rl_dse.py` 皆與正式消融來源相同。歷史 manifest 不覆寫；最終 GUI 另用新輸出驗證。

PPA 仍是未經 RTL／silicon 校準的分析估算。Tangram 為來源可稽核的 bounded DP/beam adapter，沒有執行原版 Tangram／BSD／ALLO。所有 unsupported 能力見動作能力矩陣與操作手冊；不能把本紀錄當作原論文完整重現或實體設計 signoff。
