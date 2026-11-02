# INMIN v0.3：起點、瓶頸 Policy 與完整搜尋循環

此版依2026-11-02使用者提供的Word問題清單與nn_dataflow-master.zip修改。v0.2 profile、schema、凍結來源及歷史實驗保留，新版使用 `chiplet_single_pe_array_v0_3`、DesignState schema3、GUI schema4。報告僅文字與數字表格。

## 具體修正

|問題|v0.3行為|可核對證據|
|---|---|---|
|只允許五種顆數|開放1～16全部整數、50完整矩形，旋轉視為不同|50個hardware roundtrip、IO守恆與A9單步交易測試|
|layout被誤認單純形狀|每個R×C依N_IO=2R重新建DRAM容量/帶寬、NoP、Compute/IO/DRAM面積及能量|硬體manifest與per-architecture metrics；1×16有2IO、16×1有32IO|
|Actor缺乏target bottleneck|候選feature新增目標layer criticality、MAC/L1/VPU service、queue/wait、pool pressure、slack與動作交互項|283維candidate/24維state，target不同則features不同的受控測試|
|memory pressure未驅動tile/cache|≥90%實際pool壓力針對相關stack提C7縮tile/清cache；<65%且有重算/overlap時可提C8|交易source_tags保存pool IDs、proposal reason及實際severity；共享pool因果歸因仍partial|
|缺乏獨立dataflow動作|A12可選output_stationary、weight_reuse、activation_reuse|重算L1 W/A讀與INT24 psum RW；MAC守恆及能量改變測試；無免費bypass|
|DP起點不可行|逐segment容量篩選、真實可容納PE fragment、local schedule cache、prefix top-N beam|R18開發probe中三個DP候選均完成且可行|
|seed吃掉RL時間|seed與search有獨立預算；seed仍對每方法計費|effective_config分別記seed/search ceiling與實際elapsed|
|無法看出policy是否在學|每步保存observation、target features、selected feature向量、全candidate probabilities、normalized entropy、reward/update|trace可重建觀察→抽樣→交易→完整PPA→更新|
|大JSON匯出超時|v0.3預設compact evidence，保留metrics/mapping/buffer/有明確截斷標記的diagnostics|artifact persist不再次跑oracle；full calendar仍實際評估|

## 起點演算法與附件來源

附件原檔SHA256：`8fae65512bb780894d8cba5a0f9c6c66f40a9845178e468d435738bde028a57b`。完整參考碼與BSD-3-Clause LICENSE保存在 `third_party/nn_dataflow_reference/`。

上游nn_dataflow的README明載row-stationary Eyeriss類硬體，逐層探索array mapping/loop blocking/partition，跨層用greedy beam。INMIN不能直接套用其Eyeriss SRAM、RF或NoC數值。本版參考其逐layer schedule cache、segment枚舉、ending-layer top-N保留方法，使用INMIN自己的PE/L1/L2/IO契約產生mapping並完整核算。沒有宣稱執行原Tangram完整搜尋或重現論文PPA。

新seed搜索從每個模型的拓撲prefix開始，枚舉長度1～4的segment、Spatial/Temporal、K/P、三種dataflow。多層group以保守whole-output bound剔除明顯超L2的方案，每層的partition/dataflow先求一個符合L1/量化參數容量的真實fragment，再快取local ranking cost。每個prefix保留8個beam，預設每架構最多4個輸出（含原stripes baseline）。所有proxy都只負責排名/剪枝，最終seed必須通過完整INMIN oracle；沒有完成的prefix不當成可執行seed。

Seed初始化先挑每個顆數一個較方正layout作候選，時間/查詢內分階段完整驗證；不是宣稱50布局都已完成PPA。全部50布局皆在RL動作域內可單步抵達。Shortlist保留有限architecture quota、generic atomic、dataflow、memory-guided與joint proposals，避免50個架構跳躍塞滿policy候選池。

## Budget與回放

|模式|Seed上限|Search上限／模型／方法|單oracle上限|完整PPA總上限|
|---|---:|---:|---:|---:|
|GUI fast|600s|600s|300s|32|
|GUI standard／新CLI預設|7200s|7200s|1800s|128|
|GUI deep|14400s|14400s|3600s|256|

完整PPA上限包含共同seed，預設seed最多16次且不超總查詢的1/3。Search自己的時間不因seed耗時而被吃掉；比較方法仍各計共同seed的真實時間與查詢，報告端到端實際消耗。上下限是可恢復有限研究預算，不是數學上窮舉所有mapping。遇到timeout仍不接受部分PPA，也不產生虛構reward。

`--seed-seconds`、`--seed-dp-seconds`、`--eval-timeout`、`--seconds`可以明確延長；參數寫入effective_config，resume要求來源/設定相同。需要更長的新研究應另開output，保留原截斷結果；不改歷史checkpoint的預算證據。

## 精確加速與準確度範圍

通訊建立原本對每個Cartesian cell掃所有demand，現在先建每軸覆蓋索引；保留相同cell/consumer排序及bytes。Producer依賴與同PE需求有精確索引，NoC/NoP路徑快取，不可變region intersection有有界快取。這些改變減少重複CPU工作，不改物理成本。完整評估仍包含依賴、實際資源calendar、SRAM/DRAM lifetime、INT24→VPU→INT8與流量。

R18 baseline舊凍結程式與初次優化版本：cProfile evaluate累計62.411s→46.607s；同時有其他測試運行，這是開發profiling而非受控吞吐基準。兩者latency/energy/power/area/MAC/DRAM/NoC/NoP/unit count逐項完全相同。後續intersection cache再加速需另用穩定來源量測，不能擴大解讀。

Gemini評估方式可作分析模型與分層成本/快取的參考，但本版沒有聲稱執行Gemini原始評估器，也未呼叫native RapidChiplet。面積/能量係數仍是既有明示M/T；沒有silicon校準、SRAM bank-address/word-tail、packet/VC cycle timing或量化準確率證明。

## 運行方式

在workspace根目錄執行：

```powershell
& '.venv/Scripts/python.exe' -X utf8 simplified_rapidchiplet/single_array_dse.py --engine v03 --model resnet18 --queries 128 --seed-seconds 7200 --seed-dp-seconds 120 --seed-queries 16 --seconds 7200 --eval-timeout 1800 --shortlist 64 --out output/inmin_v03_resnet18
```

用完全相同參數加 `--resume` 接續。GUI仍由 `simplified_rapidchiplet/scripts/start_hybrid_gui.ps1` 啟動，新catalog為schema4；舊schema1/2/3可回放。

Actor的feature因果消融可在相同候選生成器下使用 `--bottleneck-features off`，讓Actor/Critic看不到動態瓶頸severity，候選generator仍有相同規則。此開關用於研究，不保證兩條不同軌跡的每一步都有相同候選；相同state時候選generator不受該開關影響。正式比較仍需要相同seed、預算、來源與重複seed證據。

## 目前的證據界線

新R18 seed probe：提案約0.656秒完整結束，baseline與三個DP proposal均可行。Baseline為22.66107075ms、26.12308559mJ；DP為20.55766574ms、17.39651436mJ。這是起點收益，尚未證明v0.3 RL在最佳seed之外有額外收益。v0.2既有負面RL結果完整保留，不能混入新profile比較。

所有新功能都須經最後來源穩定驗收與新的完整模型search結果後才能宣稱有效。不能用「features已加入」當成「policy已學會正確瓶頸策略」。
