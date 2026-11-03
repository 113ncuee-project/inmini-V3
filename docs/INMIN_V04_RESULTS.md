# INMIN v0.4：搜尋改善與策略歸因

2026-11-03。報告只使用文字與數字。以下固定硬體的完整 PPA 是 analytical model，非晶片量測。舊 v0.2/v0.3 與負面結果均保留。

## 已完成的 ResNet18 Mapping 比較

Batch=1、2 Compute（2×1、每顆16PE）、4 IO、相同 SRAM／頻率／NoC／NoP／DRAM、Fusion Off。共同起點是既有 bounded Tangram-style DP adapter 的最佳合法 seed；不是原版 Tangram executable。所有原始 seed 的 latency、energy、power、area、MAC、DRAM bytes、NoC/NoP hop-bytes 都以新 full oracle 重新驗證一致。

|指標|共同最佳 seed|Replay RL 最佳|變化|
|---|---:|---:|---:|
|Balanced Cost|0.8390362762|0.7635362340|−8.9984%|
|Latency (ms)|11.818170|8.909681|−24.6103%|
|Energy (mJ)|18.438092|12.620154|−31.5539%|
|平均 Power (W)|1.560148|1.416454|−9.2103%|
|Area (mm²)|64.794232|64.794232|0%|
|DRAM read (MB，十進位)|54.080428|16.986779|−68.5898%|
|NoC hop-bytes (MB)|241.375552|98.491520|−59.1957%|
|NoP hop-bytes (MB)|68.313792|34.601216|−49.3496%|
|Executed MACs|1,814,073,344|1,814,073,344|0%|
|Recompute MACs|0|0|0|

這個解同時降低 latency 與 energy，與先前「延遲增加但平均功耗下降」的 Cost 改善不同。這裡沒有增加硬體、刪除通訊或增加免費 SRAM。權重保留是原 evaluator 已支援的有價選項，真正的 arrival-to-last-reader WL2 peak 仍須通過。

RL 組完成 64 次 charged full PPA（含共用2次、搜尋62次，其中59次可行），0 timeout。1,888 次 replay SGD 是59筆真實樣本的訓練更新，不是1,888次 PPA。最佳 state 出現在搜尋 step47；四次 uniform warmup 的最佳 Cost 為0.7960567486，後續又改善4.0852%。這個差值仍不能單獨當成 policy 相對 Random 的因果效益。

|方法|完整PPA，含共用2次|最佳Cost改善 %|該解Latency改善 %|該解Energy改善 %|Seed重驗＋Search s|
|---|---:|---:|---:|---:|---:|
|Replay RL|64|8.9984|24.6103|31.5539|919.569|
|Random|64|9.1302|17.5388|28.8658|936.546|
|SA comparator|58|8.7869|29.2805|33.4477|940.023|

SA因900秒搜尋上限結束，另有1次尾端timeout，沒有接受partial PPA。三方法在相同58次查詢預算下的Cost改善仍分別為8.9984%、9.1302%、8.7869%。完整曲線在 `analysis/equal_queries.csv`／`equal_time.csv`。上述早期pilot時間不含一次2.219秒的共用global-bank生成；後續交付版另外記錄並計入準備時間。

目前不支持 RL 穩定勝過 Random。RL與SA這輪的Balanced最佳解取捨不同，表中每列是各方法的Cost最佳解，不是把不同mapping的最低Latency／Energy拼成一個設計。完整實評archive的額外指標另列CSV。

RL的推薦同時使用兩顆Compute，各layer使用2～8PE，平均7.4375PE；兩顆Compute的面積與靜態成本均完整計費。新mapping降低資料重讀、片內與跨晶片移動；沒有以增加硬體換取改善。

## 哪些問題已經修正

舊 P5 的 Actor–Critic 只有約15–18次有效更新，normalized entropy 幾乎1；這些資料不能支持已學會瓶頸選擇。新系統把原本混雜的決策拆開：固定架構，外層執行結構化 global/window Mapping transaction，內層使用可裝入 fragment 的有價 dataflow 排序，full oracle 統一決定真實 PPA 與可行性。

新控制器明確是 gamma=0 contextual neural Replay-Q，而非舊 Actor–Critic。它對每個候選讀取 Mapping 參數、當前 PPA、目標 layer 的 criticality／memory pressure／MAC/L1/VPU／queue wait，從實際完成的 PPA reward 學習效用。Reward 只是已宣告 Cost 的 scaled log transform，沒有手寫的瓶頸收益。

本輪最後十步 normalized entropy 約0.742，已非近乎均勻。另以92個未被RL訓練過的Random／SA完整PPA state測試：

|模型|Spearman排序相關|Pairwise排序正確率|Utility MSE|
|---|---:|---:|---:|
|初始Replay-Q|−0.3465|38.1032%|38.4602|
|實際訓練後Replay-Q|0.7650|78.4520%|18.7356|
|相同59筆訓練資料，features off重建|0.7726|79.0253%|20.0379|

Features on模型從原始初始checkpoint與真實59筆樣本重建後，與實際final模型的prediction最大差為0。這支持模型學到了候選效用排序；沒有使用control-arm結果訓練搜尋policy。

可歸因的具體決策是step47：policy已做1,376次SGD，選中 `layer1_1_conv1 / layer1_1_conv2 / add_1` 的critical window，把三層8PE改為2PE，使用balanced partition、spread placement、interleave DRAM、auto retention。該候選在63個候選中Q排序第8，被選機率5.6314%，均勻機率1.5873%。目標有實際零slack訊號；完整before/after與分配保存在 `analysis/critical_window_case_study.json`。

這個局部步驟也顯示objective的限制：它讓Cost從0.765311降到0.763536，但Latency由8.357755ms升到8.909681ms、Energy由12.270966mJ升到12.620154mJ，靠平均Power下降取得較低Balanced Cost。因此不能把「選中critical window」等同「縮短critical path」。若研究主張高效能與低能耗，應另用預先指定的EDP／Latency／Energy目標長跑，並保留Balanced這組原始結果。

但本輪未證明瓶頸特徵本身帶來額外排序優勢：features off排序略高、features on的MSE略低。這是同一批guided資料的固定資料消融，不是generator guidance消融，也不是實際on-policy勝負。不能把「不再均勻」直接寫成「bottleneck-aware policy優於Random」。

## Gemini 的參考價值與界線

參考本機 Gemini 的 `layerengine.cpp`、`coremapping.cpp`、`noc.cpp` 及論文：其優點包含清楚的 Part／CG／FD 空間、內層 loop-order/tiling engine、輕量 analytical throughput/resource limits，以及架構與 Mapping 的分層探索。不能把其新架構＋Mapping 的論文總收益，全當成 SA 控制器收益。

本輪借鏡分層與可達空間，沒有聲稱已重現原版 Gemini。SA comparator 使用我們相同的 reduced structured Mapping grammar 與 full oracle，不是原 Gemini executable。沒有進行同機同設定的原版 Gemini DSE timing 比較，因此不能宣稱比 Gemini 更快。

## 瓶頸與評估加速

Criticality 根據實際 scheduled dependency DAG 加資源先後邊求 slack；目標 layer 的 service／queue waits／共享 pool peak 提供嚴重度。Atomic route reservation 無法唯一歸因到單一 DRAM／NoC／NoP wait，故保留 partial／unknown，而非把重疊時間相加。

新 native calendar 用 exact free-gap treap 與 C++ slack，保留 deterministic priority 與 lexical ties。Kernel／route／compile-communication geometry cache 只重用不變的描述，依然完整重做所有受影響的成本與容量。沒有把 proxy 或 partial simulation 冒充 full PPA。

完整同源benchmark與inner-only對照已在大型比較結束後序列完成，額外8次full PPA，未加入policy訓練：

|相同seed的完整oracle|兩次Wall s|中位s|
|---|---|---:|
|Python coalesced calendar|23.8005、24.0720|23.9362|
|Native exact calendar|9.7310、10.2390|9.9850|

相同來源、相同mapping、fresh evaluator、交替次序、無profiler；所有核對的物理PPA數字完全一致，完整oracle中位時間加速2.3972倍。這是該seed的受控結果，不是所有候選／模型的通用倍率。

|固定原始空間Mapping的介入|Cost改善 %|Latency ms|Energy mJ|
|---|---:|---:|---:|
|原始seed|0|11.818170|18.438092|
|只調dataflow|0|11.818170|18.438092|
|只使用auto retention|1.5752|11.285378|17.343812|
|dataflow＋auto retention|1.5752|11.285378|17.343812|

對比這個較強的seed＋inner對照，RL64-query推薦仍改善Cost7.5420%、Latency21.0511%、Energy27.2354%。這是Mapping搜尋的收益證據；Random也有相近收益，因此不能全歸因於神經policy。

完整來源與結果在 `output/inmin_v04_20261103/oracle_controls_release`，source-stable=true。舊cProfile耗時沒有被拿來和新無profiler耗時相除。

## 重現與後續驗收

凍結原始比較：`output/inmin_v04_20261103/r18_retention_pilot`，source identity `73ec2f92c2f33d02b47104103d491952f84839f86e9a768a66e5437191823390`。其 source snapshot、full mapping、候選、policy、PPA 與時間帳本都保留。

交付版另增加 exact native slack／geometry cache、seed input snapshot、獨立 SA acceptance RNG、可選完整 Greedy lookahead、CPU/wall 分開記錄與更完整 Q-update 診斷。不能把舊 pilot 的數值說成所有新入口／模型／RNG 都已驗證。

交付核心已通過146項回歸與四方法Toy的停止／續跑：相同動作順序、相同最佳mapping與policy更新、每方法12次完整查詢、無durable重算；analysis／completed-resume不修改PPA或checkpoint。另以真實Windows venv子程序驗證taskkill timeout時的安全清理。

128-query補充驗證已完整完成，位於 `output/inmin_v04_20261103/r18_release_128`，source identity `139b7fa2dffa727dafbaaea11c27fe6e7efa36197a47e1b2d70ad9dec6fb9310`：

|指標|128-query Replay RL|
|---|---:|
|完整PPA|128（共用seed重驗2＋search126）|
|可行search PPA|121|
|容量不合法但完整評估的search PPA|5|
|Search timeout／compiler reject|0／0|
|SGD updates|3,872|
|最佳Cost|0.7623902943|
|相對共同seed Cost改善|9.1350%|
|最佳Cost解的Latency|9.344121ms（−20.9343%）|
|最佳Cost解的Energy|12.866347mJ（−30.2187%）|
|EDP改善|44.8269%|
|Area|64.794232mm²（不變）|
|DRAM read|17.197723MB（−68.1997%）|
|NoC hop-bytes|104.779904MB（−56.5905%）|
|NoP hop-bytes|34.112896MB（−50.0644%）|
|Executed／Recompute MACs|1,814,073,344／0|
|最佳解出現的search step|113|
|Search wall|1,077.351s，7.0172完整search PPA/min|
|Seed重驗＋準備＋search charge|1,115.183s|
|最後10步normalized entropy|0.7012|

整個128次都是真實完成的完整PPA，不含SGD重播或proxy。相對uniform warmup最佳解又改善4.2292%；仍不可把這個差值當成相對Random的policy因果收益。最後13次search沒有刷新最佳Cost，不能據此證明全域收斂。

此組比64-query對照使用更多查詢，且探索率的排程取決於預先指定的horizon；不宣稱128-query結果贏過64-query Random。它的Balanced最佳解也比64-query RL最佳解更慢、能量更高，展示平均Power與Latency的取捨。全部完整mapping與額外archive指標都保留，不拼接不同設計的最佳數字。

同一輪另有一個**同時較快且較省能量的已驗證mapping**，state hash `0148d65ca3afacc20c626edf54421f4f06f3a41bcc3a38813577273b8ca1ebc7`。它在第86次charged full PPA被找到，Latency8.359087ms（−29.2692%）、Energy12.430293mJ（−32.5836%）、EDP改善52.3159%，Cost0.7691683952（−8.3272%）。這些數字來自同一個完整mapping，不是取各自的最小值拼接。它是事後從Balanced訓練archive選出的EDP方案，不改稱EDP訓練結果。完整狀態與原始PPA已匯出到 `inputs/replay_v04/recommendations/resnet18_query128_edp_archive.json`，Balanced最低Cost方案另存同資料夾。

以121筆實際訓練樣本訓練的final Q，另在排除訓練state後的92個control PPA上，Spearman由−0.3034變為0.7938、pairwise排序正確率由39.3215%變為79.9331%。此組held-out集合與64-query分析不完全相同，不能直接當成訓練資料量的因果比較。沒有額外PPA或policy更新；source與physical-reference核對都通過。

這個來源在兩次seed PPA完成後遇到Windows taskkill清理逾時，資料已持久化；後續沿同一凍結來源resume，沒有重算共用seed。事故保存在 `cleanup_incident.json`；最終status=completed、return_code=0、source_stable=true、audit零error／零warning。新版host清理修正另經146項測試。兩次已知child invocation總wall1,131.074秒，包含清理／啟動；不包含人工修復的停頓、source-copy/import overhead或歷史seed生成。這些scope在 `known_invocation_accounting.json` 明記。

操作入口：`run_inmin_v04_overnight.ps1`。預設同一原始 Mapping seed，RNG 7/17/37，三方法各256完整查詢／3600秒，可由本機獨立長跑；不用恢復 Codex 排程。可選 Greedy 與 EDP／Latency／Energy 目標，須使用獨立、預先指定的 OutputRoot。

仍需多 RNG／跨模型實驗來判定策略穩定性。第一階段沒有把 Fusion、架構數量變動混入比較；也未解決物理校準、packet arbitration、bank conflict、C-panel streaming 等模型界線。
