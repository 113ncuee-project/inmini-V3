> **2026-11-03 最新狀態請先讀 docs/inmin_v04_progress.md。** v0.4 Mapping 系統、128次完整PPA與對照已完成，舊v0.2/v0.3進度保留作歷史；不要重跑舊formal workflow。使用者最新設定為維持每小時排程暫停。以下歷史「不能停用續作」不再代表目前授權。

# INMIN v0.2 續作狀態

更新：2026-11-01 19:31 Asia/Taipei。尚未完成；先核對帳本/程序，避免重跑。17:18舊進度已備份到 docs/history/inmin_v02_progress_20261101_1718.md，該檔內容已過期。

## 使用者授權優先於附件

使用者要求按兩份附件修改；報告僅文字與數字表格，不產圖；1800秒可依證據延長，要回答 bottleneck-aware RL 是否找到好設計；額度恢復後接續。此授權覆蓋附件先不長跑/固定1800秒的限制。小型正確性已通過，三模型必要公平長跑已獲授權，無需再問。不得使用重置券、買額度或付費 API。

原附件逐字保存在 docs/specs；formal_v8/spec_identity.json 記錄原檔/副本SHA256，已核對一致。保留歷史profiles/報告及既有未提交變更，不可reset/清理。沒有適用AGENTS.md，沒有啟用子代理。

Heartbeat inmin-v0-2-rl ACTIVE，每小時第50分接續。正常運行且無實質變化時安靜；全案實驗/審計/交付完成才停用。主機/app須能運作，排程不保證睡眠時喚醒。

## 穩定實作（路徑前綴 simplified_rapidchiplet）

|檔案|實際內容|
|---|---|
|hybrid/single_array_hardware.py|profile chiplet_single_pe_array_v0_2，engine inmin_single_array_v0_2；16PE/die、4096MAC/cycle、無Core、L1 2.75MiB/共享L2 1MiB/無UB；15矩形、2R IO、四預留port成本、實際路由、M/T及成本版本；to/from_dict驗證|
|single_array_compiler.py|精確ownership/DF box；MAC L1容量與INT24 psum；INT8不重複占OL1；非MAC只用VPU/L2；無免費C-panel|
|single_array_communication.py|按group/layer/tile/execution cohort拆非weight讀取，消除免費跨group保留及future consumer入場cycle，付額外DRAM/NoP流量|
|single_array_evaluator.py|Python顯式資源calendar；PE/L1、共享L2 aggregate RW、單VPU/DMA、逐鏈路、NoP switch、各IO controller；INT24→VPU→INT8、量化參數、有限staging、SRAM/DRAM lifetime/容量、診斷及能量分項|
|single_array_proposals.py|有界C6 group/mode/quota/partition/placement/depth/tile/cache聯合候選、C9 paired-off；critical-path引導及generic/architecture同池；完整PPA決勝|
|single_array_seed.py|版本化Tangram-style prefix DP/beam，非原Tangram；保留stripes baseline、Spatial/Temporal、K/P及IO差異；Proxy僅提案/剪枝|
|rl_schema/actions/search.py|schema2為24 state/180 candidate features；A9任意合法架構跳躍、Temporal C9、C1-C9交易；schema1歷史保留；完整shortlist gzip/機率/reward/checkpoint；timeout未知、不當物理無效、不更新policy|
|single_array_runtime.py|可終止獨立worker、complete PPA/reject/timeout/export分帳、累積resume帳本；實際compile depth，即使後續timeout；無部分PPA|
|scheduler.py|新coalesced calendar，回歸驗證時間與舊排程完全一致，降低CPU成本；歷史default未改|
|single_array_dse.py|四方法CLI、共用seed/reference、多起點、seed query cap、查詢/時間上限、每步checkpoint、來源/config鎖定resume、純文字REPORT/JSON|
|gui_request_v3.py/single_array_gui.py/hybrid_gui.py/gui|schema3 DNN/PPA/preference、Batch1/Seed7/Auto、16PE engine、文字報告；舊schema1/2保留；backend E2E及JS syntax已驗證，未做browser操作QA|

已修lifetime：DRAM寫回後釋OL2；遠端recipient不延長source；同PE direct/residual讀取前不得早釋放；量化參數序列化。Depthwise以獨立通道填16 output lanes、每lane一個input MAC，最高1/16利用率，沒有假滿載。

## 驗證/環境

|證據|結果|
|---|---|
|output/inmin_v02_20261101/acceptance_final_v8/result.json|103 tests，0 failures/errors，source_stable=true，51.437秒總耗時；unittest 49.955秒|
|範圍|新硬體/compiler/evaluator、C1-C9合法/非法rollback、A9、RL/replay/timeout、scheduler、seed/cohort、GUI v3 toy；舊Joint/Acceptance/Integration/Tangram/Gemini/GUI回歸|
|JS|node --check gui/app.js通過；未宣稱browser互動驗證|

完整模型runtime：C:/Users/user/Desktop/rapidchiplet/.venv/Scripts/python.exe，torch2.7.0+cpu/torchvision0.22.0+cpu/numpy2.3.5。系統Python不適用。測試tempfile用workspace/tmp（default sandbox temp不可寫），acceptance driver已設定。CIM程序列舉被拒，改看Get-Process/run_state/suite_status/OS lock，不升權。

## 凍結來源與程序（每次核對）

正式根目錄 output/inmin_v02_20261101/formal_v8。

- source_snapshot：125個程式/設定/測試/UI檔；manifest identity b0b2cfe73707633dc3515160b21452e7afed0ee390dce0ca94cb4ecb2c5b082c。不得修改副本！live後續改動不影響正式來源。若要修oracle，保留v8並另開版本。
- snapshot_smoke：已完成，source_stable=true，44.454秒；四方法各6 completed PPA、兩個RL各4次更新。獨立audit.json通過24個cache metrics的P=E/T、energy sum、reward、機率、shortlist hash及查詢帳本。僅流程驗證。
- finite_toy：已完成，47.453秒，381次完整PPA（含baseline）、380 unique/feasible states、0reject。342同mapping Fusion配對：31勝/293負/18平。有限域最佳cost0.803940003、latency1.9428359375µs、無Fusion。僅固定1compute/2IO有限域最佳，不能與可變架構搜尋直接算同域regret。
- 正式conductor已啟動，functions session22455，owner PID29388；suite_status.json初始child launcher PID6616、實際Toy CLI PID24236。狀態在formal_v8/results/suite_status.json及各case run_state/checkpoint。腳本source_snapshot/scripts/run_single_array_research_suite.py，--snapshot本副本，--out formal_v8/results；設定--queries128 --seconds3600 --eval-timeout300 --toy-queries64 --toy-seconds600。OS lock有效；正常跑不要重啟。

正式設定：Seed7、Batch1/input224、balanced、無捏造user hard limits。Toy四方法64full PPA/600秒；ResNet18、ResNet50 v1.5、MobileNetV2每方法128full PPA/3600秒，每oracle300秒。查詢含共同seeds（seed上限8），seed elapsed也向每方法計費。四方法Random/Greedy/atomic RL/bottleneck RL；各大模型另跑fusion_off bottleneck RL。每case串行、有OS lock/checkpoint，最壞約15小時加Toy；不是保證用滿或完成128次。3600秒是證據導向延長，所有方法相同上限。Conductor執行時暫請Windows保持系統運行，結束恢復，無永久電源設定更改。

## 開發結果（不能混入v8正式比較）

|資料夾|觀察與界線|
|---|---|
|toy_smoke_initial|export timeout/seed帳本bug，DEVELOPMENT_ONLY，不可比較|
|toy_corrected_smoke_v1|舊來源16PPA/方法，Greedy約6%改善，其餘0；非目前profile結論|
|resnet18_pipeline_probe_v1|早期lifetime bug，不代表全域不可行|
|resnet18_development_profile_v2|coalesced改善CPU保持相同latency，開發profiling|
|pipeline_probes_v3|R18短跑seed改善約0.0806%；R50跨group保留、MobileNet future-consumer cycle已修；非正式比較|
|resnet50_cohort_probe_v4|修cohort後可行：4,089,184,256MAC/18224units/CPU68.906秒；後續模型變動，僅pipeline證明|
|toy_joint_finite_oracle_v3/v3b|舊來源380states，342配對36勝288負18平；保留負面結果，v8重跑中|
|toy_dp_entry_probe_v5|12查詢全耗seed、0更新；已新增seed查詢上限，非RL結果|

目前沒有完整公平的代表模型證據可證明bottleneck-aware RL優於Random/Greedy/atomic RL。

## 模型界線

新oracle是Python顯式網路/資源分析，未呼叫native RapidChiplet；不是晶片量測、原Tangram、RTL/signoff、校準PPA或量化準確率驗證。暫採4x4PE mesh/四corner gateway；有限whole-flow reservation保守，未提供cycle-accurate VC、SRAM bank-address/word-tail/byte-enable、DDR refresh/channel timing。INT24每MAC飽和/ties-even/Add共同scale都是M。MAC能量.024pJ的op/MAC convention不確定，2倍敏感度未做。外部DRAM面積/idle、IO PHY/controller、VPU/register成本是M proxy，值見hardware_profile.json。未實作C10、內部C-panel、standalone BatchNorm；搜尋fusion proposal depth<=4，不宣稱更深覆蓋。只有Seed7，無跨seed統計保證。

## 待完成順序

1. 正式conductor已啟動；每次先讀suite_status、各case checkpoint/worker ledger及Get-Process。正常跑不重啟；若owner已停且未完成，以完全相同命令重啟conductor，它會檢查source並resume。
2. 每case完成審計P=E/T、energy components、資源/lifetime、reward/probability、query/wall帳本及source/archive一致。保留失敗，不把timeout視為DF落敗。
3. 成功實評fusion state做固定硬體/Mapping的on/off counterfactual，額外oracle另計費。搜尋on/off不是同mapping因果證明；無樣本標not_run。
4. 文字表格總報告：seed與學習收益分開、對照實際budget/coverage/負面結果、三模型Mapping/traffic/PPA、有限Toy域、M/T/未做項目。分別回答「找到改善設計？」與「勝過同預算搜尋？」。
5. 完成修改清單/設計/可重現指令；全部達成才停用heartbeat，不因額度低而假稱完成。

獨立唯讀審計工具（不在凍結來源內，不會改oracle）：simplified_rapidchiplet/scripts/audit_single_array_results.py --root output/inmin_v02_20261101/formal_v8。已對snapshot_smoke跑通；未完成case不冒充已審計。輸出audit.json及comparison.csv。

## 19:23 補充交接

- 背景conductor session22455 持續運作。19:22 Toy已完成Random/Greedy/atomic三方法，各64PPA；bottleneck_rl進行中，checkpoint約6秒前更新。完整三模型仍排隊，不要誤稱完成。
- Get-Process可能看不到其他工具session中的Python，空結果不能作為程序已死的證據；以OS lock、suite_status與checkpoint/accounting檔mtime判斷。run_state只在切換arm時更新，不能僅靠該檔age判死。
- finite_toy的31勝是綜合cost下降，不是加速。342配對：延遲/能量/DRAM讀各324增加、18持平、0下降；MAC48增加、294持平。Cost含平均功耗E/T，可能慢而總能量增、平均功耗低，報告需明說。
- 固定mapping counterfactual helper已完成並以snapshot_smoke驗證：simplified_rapidchiplet/scripts/run_single_array_counterfactual.py。3個已驗證Fusion state回放無錯；選最低cost一個，重新on/off兩次額外PPA（3.984秒），replayed_on_matches_original=true；除fusion_stacks外mapping完全相同。該Toy pair是負面結果，保留於formal_v8/counterfactual_smoke；不是完整模型效益。
- 每個正式fusion_on case完成後可執行（用不同的--out counterfactual_resnet18/resnet50/mobilenet_v2）：
  & '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/scripts/run_single_array_counterfactual.py --snapshot output/inmin_v02_20261101/formal_v8/source_snapshot --run output/inmin_v02_20261101/formal_v8/results/resnet18/fusion_on --out output/inmin_v02_20261101/formal_v8/counterfactual_resnet18 --seconds 700 --eval-timeout 300
  helper只讀凍結來源/原case，額外兩oracle獨立計費；無成功Fusion則明寫not_run，不自動算DF輸。
- audit helper已擴充檢查finite全部380states/342pairs以及counterfactual只有Fusion介入、on回放、能量/功率算術。輸出formal_v8/audit.json、comparison.csv及純文字RESEARCH_REPORT.md；可在case完成後重跑，不更動oracle/checkpoint。
- 目前audit通過，snapshot manifest全125檔無變；正式root下image檔0個。技術說明/修改列表/重現指令/M/T：docs/INMIN_V02_IMPLEMENTATION.md。
- 每方法3600秒是首輪上限，不是已證明收斂。完成後需看best-so-far曲線、成功PPA/有效更新與最後改善；如果大量timeout導致證據不足或結尾仍明顯改善，可在保留v8/相同對照預算的前提另規畫必要延長，不要任意改凍結來源或強行改嚴格resume設定。

- HTTP補充：實際TCP loopback請求被sandbox WinError10013拒絕，未升權。改以同一凍結handler在記憶體呼叫GET路由，catalog schema3/16PE、實際index.html的16PE文字、Markdown text/plain MIME均通過。證據formal_v8/gui_http_smoke/result.json，明記TCP/browser not_run；沒有圖片。
- 根README已加2026-11-01新入口，保留日期更早的原文歷史。Live來源自freeze後只新增審計/固定mapping helper與docs/README，沒有改oracle。

## 最新已完成的正式 Toy 比較

正式Toy四方法已完成，source_stable=true，suite case return_code0；case實際總elapsed949.477秒（四方法串行，不是每方法949秒），每方法上限600秒/64PPA，皆達到64PPA。各方法共用8個完整種子、各自56次search full PPA。

|方法|完整PPA|Policy更新（含合法cache重訪）|最佳cost|相對最佳seed改善%|
|---|---:|---:|---:|---:|
|Random|64|0|0.8229296119|0|
|Greedy|64|0|0.8089849884|1.69450986|
|atomic RL|64|56|0.8225928523|0.04092203|
|bottleneck RL|64|68|0.8229296119|0|

這個Toy不支持bottleneck-aware RL勝過對照；不可改寫成正面結果。不是完整模型/跨seed結論。

正式Toy固定mapping counterfactual亦完成：25個成功Fusion state可回放，0 replay error；選最低cost Fusion state，在相同1Compute/2IO上重新on/off，各一次完整PPA（額外2次）。On回放與原PPA完全一致；DF on比off增加4.81622168µs延遲、1.83744545µJ能量、3150B DRAM讀，平均功耗下降0.0744823W，綜合cost反而增加0.0861358。保留負面結果；見counterfactual_toy。

兩個最初counterfactual的elapsed_s只記oracle phase，已明確補scope/end_to_end_wall_s=null，不捏造未錄到的selection wall。Helper已修未來包含selection/replay在end-to-end deadline與elapsed；原PPA/查詢未更改或重跑。

最新獨立audit通過：正式Toy四方法256個cache records、snapshot smoke24個、有限380states/342pairs、兩組額外固定mapping pair；來源125檔無變。audit產生RESEARCH_REPORT.md、comparison.csv。不要將新增audit/helper文件當成凍結oracle變更。

Conductor已自動前進resnet18/fusion_on，launcher PID33600；第一個baseline seed完整可行、第二個DP seed完整但容量不可行，後續seed還在跑；這是候選被正確拒絕，不是所有設計不可行。其餘代表模型/消融待佇列。

## 2026-11-01 20:52 例行續作（正常執行，未重啟）

來源snapshot 125檔hash一致，suite OS lock仍持有；ResNet18 fusion_on正在Greedy第一輪lookahead，已實評22個search PPA時仍正常推進，未達整個case完成。不要因尚無Greedy checkpoint就重啟；長lookahead完成後才記一個selected step。

Random組已完成：含共用seed共17個完整PPA（4 seed+13 search），1個search oracle timeout；相對最佳seed改善1.30567577%，最佳cost0.9869432423，latency23.04553792ms，32.39711576mm²，1.088061276W，energy0.0250749574J。Wall含seed3429.648秒，未達128 query ceiling，停止因剩餘時間不足最近oracle成本。這是Random結果，不能歸功於RL，也不能與尚未完成的方法宣稱勝負。

Random ledger另有2個artifact persist timeout，各約15秒；與1個evaluate timeout分開，沒有列成缺失PPA或額外完整查詢。成功實評DF深度2有1個；深度3/4只在候選池/shortlist，不能說已敗。

審計helper在凍結來源之外增添「已完成arm可先審計，外層case可仍running」支援。已通過R18 Random的15個cache records與既有全部Toy/finite/pairs審計，已更新formal_v8/audit.json、comparison.csv、RESEARCH_REPORT.md；未執行額外oracle。剩餘三方法/模型正常背景接續，本次保持靜默。

## 2026-11-01 21:52 例行續作（正常運行）

ResNet18 fusion_on已完成Random與Greedy，atomic_rl進行中；snapshot 125檔一致、suite lock持有。Greedy含seed共41次完整PPA（4 seed+37 search），無evaluate timeout，wall含seed3493.175秒，cost0.9931905170，相對最佳seed改善0.680948296%。最佳latency21.80156427ms、energy0.02557209187J、32.39711576mm²、1.172947571W。Greedy以37個lookahead後提交1個selected step；step數不是PPA次數。

兩個完成arm合計54個cache records的獨立source/能量/功率/reward/機率/shortlist/帳本審計通過，已更新audit.json/comparison.csv/RESEARCH_REPORT.md。Random與Greedy完成查詢數不同，不能直接宣稱query效率優劣；兩者使用相同上限。Atomic目前觀察到19個search完整PPA仍推進，bottleneck RL待接續。未重啟、未新增oracle、未動凍結來源，正常背景工作保持靜默。

## 2026-11-01 22:55 ResNet18 Fusion On 四方法完成

|方法|完整PPA含seed|Policy更新|最佳cost|相對seed改善%|
|---|---:|---:|---:|---:|
|random|17|0|0.9869432423|1.30567577|
|greedy|41|0|0.9931905170|0.68094830|
|atomic_rl|26|18|0.9867722659|1.32277341|
|bottleneck_rl|25|21|1.0000000000|0.00000000|

各方法共同3600秒/128完整PPA上限，但均因wall不足而未達128，實際含seed時間約3418–3493秒。Bottleneck RL有21次policy更新但沒有改善最佳seed，這輪不支持其優於對照；不能推論所有模型或跨seed表現。Atomic RL最佳cost下降1.32277%，比Random略好；查詢數不同，不宣稱query效率勝出。Conductor已進入ResNet18 fusion_off；R50/MobileNet後續。來源125檔hash一致，未重啟或更動oracle。固定mapping R18 counterfactual尚未跑，留待後續，避免與正在進行的對照爭CPU。
