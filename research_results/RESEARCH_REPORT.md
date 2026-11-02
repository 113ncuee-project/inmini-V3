# INMIN v0.2 研究結果（持續更新）

更新 UTC：2026-11-02T00:39:55.664207+00:00

本檔只呈現已完成並審計的實驗；整個研究尚未完成時，不把部分結果當成最終結論。報告僅文字與數字表格。

來源 snapshot：`b0b2cfe73707633dc3515160b21452e7afed0ee390dce0ca94cb4ecb2c5b082c`。新 profile 每 Compute 16PE、L1 2.75MiB、共享L2 1MiB、無實體Core/額外UB；Batch1、Seed7、balanced、無外加PPA硬限制。

新 oracle 是 Python 顯式網路/資源 calendar，沒有執行 native RapidChiplet。PPA 未校準，不是晶片量測或timing signoff。舊硬體結果不混入本表。

## 完整模型與搜尋對照

正式上限：三模型每方法128次完整PPA、3600秒；Toy為64次、600秒。初始化成本向各方法計費，timeout/reject/export另列帳。相同上限不保證相同完成次數；未達相同完成查詢時，不能以本表單獨宣稱query efficiency勝出。

|模型|Fusion|方法|Full PPA|Policy更新|Timeout|Wall s|最佳成本|種子後改善 %|Latency ms|Area mm²|Power W|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|mobilenet_v2|off|bottleneck_rl|27|20|0|3513.2323|0.98589585|1.4104152|14.367151|32.397116|0.7005834|
|mobilenet_v2|on|atomic_rl|41|34|1|3457.5384|1|0|15.283687|32.397116|0.68842865|
|mobilenet_v2|on|bottleneck_rl|31|21|2|3546.9893|1|0|15.283687|32.397116|0.68842865|
|mobilenet_v2|on|greedy|59|0|1|3512.4505|0.97816457|2.1835425|14.317931|32.397116|0.68683317|
|mobilenet_v2|on|random|32|0|1|3551.8717|1|0|15.283687|32.397116|0.68842865|
|resnet18|off|bottleneck_rl|21|16|4|3542.7431|0.98837434|1.1625659|21.542324|32.397116|1.1694793|
|resnet18|on|atomic_rl|26|18|0|3467.9762|0.98677227|1.3227734|21.407811|32.397116|1.1707815|
|resnet18|on|bottleneck_rl|25|21|0|3417.73|1|0|22.661071|32.397116|1.1527737|
|resnet18|on|greedy|41|0|0|3493.1752|0.99319052|0.6809483|21.801564|32.397116|1.1729476|
|resnet18|on|random|17|0|1|3429.6482|0.98694324|1.3056758|23.045538|32.397116|1.0880613|
|resnet50|off|bottleneck_rl|20|16|0|3440.1626|0.99590028|0.40997238|88.411354|32.397116|0.95566354|
|resnet50|on|atomic_rl|21|14|0|3416.7544|0.94253864|5.7461357|64.469281|32.397116|1.055751|
|resnet50|on|bottleneck_rl|13|8|2|3508.69|0.99806238|0.19376213|89.546341|32.397116|0.94987253|
|resnet50|on|greedy|19|0|0|3408.1534|0.99647675|0.35232463|88.64866|32.397116|0.95480694|
|resnet50|on|random|15|0|2|3417.3513|0.99806238|0.19376213|89.546341|32.397116|0.94987253|
|toy|on|atomic_rl|64|56|0|204.76639|0.82259285|0.040922035|0.0034730293|32.397116|0.40497683|
|toy|on|bottleneck_rl|64|68|0|370.9917|0.82292961|0|0.0034740293|32.397116|0.40530378|
|toy|on|greedy|64|0|0|35.41403|0.80898499|1.6945099|0.0028716533|32.397116|0.41121386|
|toy|on|random|64|0|0|339.43548|0.82292961|0|0.0034740293|32.397116|0.40530378|

整個正式佇列狀態：`completed`。

|Case|狀態|
|---|---|
|toy/fusion_on|completed|
|resnet18/fusion_on|completed|
|resnet18/fusion_off|completed|
|resnet50/fusion_on|completed|
|resnet50/fusion_off|completed|
|mobilenet_v2/fusion_on|completed|
|mobilenet_v2/fusion_off|completed|

## 種子與搜尋軌跡

這裡的step是一個所選交易；Greedy的lookahead與失敗/timeout成本另在查詢帳本，不能把step視為完整PPA次數。最後10步沒有改善只表示這段已觀察軌跡停滯，不能證明全域收斂。

|模型|Fusion|方法|最佳種子成本|選擇步數|首個改善step|最後改善step|最後10選擇步的成本下降|最高實評DF深度|
|---|---|---|---:|---:|---:|---:|---:|---:|
|mobilenet_v2|off|bottleneck_rl|1|21|3|5|0|0|
|mobilenet_v2|on|atomic_rl|1|35|none_observed|none_observed|0|0|
|mobilenet_v2|on|bottleneck_rl|1|26|none_observed|none_observed|0|4|
|mobilenet_v2|on|greedy|1|2|1|2|0.021835425|4|
|mobilenet_v2|on|random|1|26|none_observed|none_observed|0|0|
|resnet18|off|bottleneck_rl|1|21|1|7|0|0|
|resnet18|on|atomic_rl|1|22|3|8|0|0|
|resnet18|on|bottleneck_rl|1|21|none_observed|none_observed|0|2|
|resnet18|on|greedy|1|1|1|1|0.006809483|4|
|resnet18|on|random|1|14|11|12|0.013056758|2|
|resnet50|off|bottleneck_rl|1|17|1|2|0|0|
|resnet50|on|atomic_rl|1|18|2|8|0|0|
|resnet50|on|bottleneck_rl|1|12|5|7|0.0019376213|3|
|resnet50|on|greedy|1|1|1|1|0.0035232463|4|
|resnet50|on|random|1|14|5|7|0.0019376213|3|
|toy|on|atomic_rl|0.82292961|56|1|2|0|0|
|toy|on|bottleneck_rl|0.82292961|68|none_observed|none_observed|0|2|
|toy|on|greedy|0.82292961|2|1|2|0.013944623|3|
|toy|on|random|0.82292961|57|none_observed|none_observed|0|3|

## 固定硬體的有限 Toy 枚舉

固定1 Compute/2 IO，380個去重狀態，381次完整PPA（含baseline），耗時47.453秒。範圍是Temporal/Spatial、PE配額1/2/4、K/W分割、contiguous/spread placement、IO0/interleave、off及三種cache策略、2/4/7方形tile。這是有限域最佳，不是全域最佳，也不與可變架構搜尋直接算regret。

|有限域最佳|成本（baseline=1）|Latency µs|Energy µJ|Power W|DRAM讀 B|重算 MAC|Units|
|---|---:|---:|---:|---:|---:|---:|---:|
|Fusion off|0.8039400032|1.942835937|0.8509591538|0.4379984627|900|0|6|
|Fusion on|0.811348726|2.150898437|0.9436867315|0.4387407211|1220|0|6|

|同Mapping Fusion on−off 指標|下降組數|持平組數|增加組數|
|---|---:|---:|---:|
|綜合成本|31|18|293|
|延遲|0|18|324|
|能量|0|18|324|
|DRAM讀取|0|18|324|
|執行MAC|0|294|48|

綜合成本包含平均功耗E/T，因此分數改善可能同時伴隨延遲和能量變差。此Toy的31組綜合成本改善，不能寫成31組加速；342組裡沒有延遲或能量下降。此有限域最佳是無Fusion，不能推論所有DNN/Mapping的Fusion都無效。

## 固定Mapping的Fusion介入

每組只移除fusion_stacks，保留硬體/groups/PE配額與placement/partition/DRAM等全部欄位；重新執行on和off，額外PPA單獨計費。負差表示Fusion on降低該指標；綜合cost降低不必然更快。這是選中的樣本，不代表全部候選。

|Case|狀態|額外Full PPA|架構|On回放一致|Cost差|Latency差 µs|Energy差 µJ|DRAM讀差 B|執行MAC差|
|---|---|---:|---|---|---:|---:|---:|---:|---:|
|counterfactual_toy|completed_matched_pair|2|single_array_c1_1x1|True|0.0861358255|4.81622168|1.83744545|3150|0|

## 證據與限制

已通過103項固定來源驗收（舊版回歸亦包含）。獨立審計檢查P×T=E、energy分項總和、reward物理差值、機率/shortlist hash、query/export/timeout帳本、PE資源與來源hash；詳細結果見audit.json。審計完成不代表尚在排隊的實驗已完成。

所有M/T實值見各case hardware_profile.json；技術設計與修改清單見workspace docs/INMIN_V02_IMPLEMENTATION.md。4×4 PE mesh/four corner gateways、queues/protocol、INT24 rounding/saturation、共同scale Add、16nm成本、DRAM面積/idle、VPU/IO/register proxy均為分析假設。Whole-flow reservation保守，SRAM bank/word-tail、cycle-accurate VC、DDR refresh、量化準確率、實體校準未完成。MAC .024pJ的op/MAC convention有歧義，2×敏感度尚未做。

只有Seed7；不能作跨seed統計保證。未實作C10、內部C-panel、standalone BatchNorm；提案Fusion depth≤4。完整per-layer mapping、traffic、深度覆蓋、未選/拒絕/timeout原因與best archive見各case REPORT.md及JSON。

最終需分別回答：RL是否在最佳已驗證seed之外找到更好的設計；是否優於同預算Random/Greedy/atomic RL。正式三模型未完成前，兩者均不預設正面答案。
