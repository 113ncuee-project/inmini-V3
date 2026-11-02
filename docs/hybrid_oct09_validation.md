> 更新：使用者最新的16nm成本基準與strict/soft限制修正，請先看 [hybrid_cost16_sources.md](hybrid_cost16_sources.md) 與 [hybrid_cost16_progress.md](hybrid_cost16_progress.md)。本檔下方數值屬歷史版本；舊混合製程／MAC乘8推導已撤回，不可當成新成本。

# 多模型／GUI 實作與驗證結果

日期：2026-10-09 Asia/Taipei。正式結果採同一份固定估算器source；驗證資料不是silicon量測。

## 已交付的功能

支援七種torchvision真實DAG；新GUI可選均衡、低功耗、小面積、低延遲，使用Gemini V-A的Energy/Area/Delay指數目標及多模型幾何平均，另以平均Power W施加硬性上限。硬體保留IO cluster mesh與片內multi-ring，新增有成本的双L1/L2 banks預取。whole-DAG frontier DP與RL共同選mapping，named SRAM與NoP競爭由完整oracle驗證；每次結果都有實際數量的package/die/PE圖與可點選layout。

## 驗收證據

- 全回歸156 tests PASS（82 hybrid）。包含800步LRU差分、跨程序模型fingerprint一致、prefetch依賴與bank重用、paid area/leakage、Flatten精確覆蓋、四種偏好、多模型source/設定resume guard、HTTP與PPA限制。
- 實際瀏覽器完成GUI submit、四偏好切換、點compute die、layer切換、重新載入保存工作，以及Area=1mm²硬限制失敗。三級SVG已XMLparse驗證。
- 完整224×224、batch1、seed7、RL4queries的15 trials：15/15合法；三個硬體都評估ResNet18/50、VGG16、MobileNetV2、AlexNet。ResNet34/VGG19另經真實frontend及shape/MAC語意tests，未列入這15個PPA trials。
- 保存timeline的dependency/resource calendars逐份核對，dynamic energy重加與MAC守恆、NoP hopbyte重加、UB及concurrent scratch容量均通過。每份結果包含全部hybrid模組SHA256；不同process提取的同模型fingerprint已一致。

## 共同硬體結果

選定模型組合與均衡偏好的共同最佳：**dies16_multi_ring**。這是本次明示資源、單seed與小budget下的候選比較，不是所有模型／批次／成本profile的普遍最優，也不是RL優於baseline的公平優勝結論。

| 架構 | 多模型共同score（越小越佳） | 全模型可行 |
|---|---|---|
| dies4_multi_ring | 0.447084 | True |
| dies8_multi_ring | 0.411440 | True |
| dies16_multi_ring | 0.395599 | True |

共同score=(E^wE×A^wA×D^wD)對五個模型取幾何平均；E/A/D用相同固定共同單位1J/1mm²/1s，沒有使用每個architecture自己的relative improvement來排名。Area為Gemini monetary cost的明示代理，無美元／良率主張。

| 架構 / 模型 | Latency ms | Energy mJ | Avg Power W | Silicon mm² | UB peak MiB/die |
|---|---|---|---|---|---|
| dies4_multi_ring / resnet18 | 3.0229 | 33.7149 | 11.153 | 272.544 | 1.287 |
| dies4_multi_ring / resnet50 | 8.5613 | 84.4536 | 9.865 | 272.544 | 4.049 |
| dies4_multi_ring / vgg16 | 23.8539 | 265.2923 | 11.122 | 272.544 | 26.103 |
| dies4_multi_ring / mobilenet_v2 | 2.0259 | 13.7066 | 6.766 | 272.544 | 0.768 |
| dies4_multi_ring / alexnet | 6.8838 | 42.5187 | 6.177 | 272.544 | 9.440 |
| dies8_multi_ring / resnet18 | 2.3997 | 31.5147 | 13.133 | 277.113 | 0.673 |
| dies8_multi_ring / resnet50 | 6.8529 | 78.2197 | 11.414 | 277.113 | 2.044 |
| dies8_multi_ring / vgg16 | 19.2360 | 249.7547 | 12.984 | 277.113 | 13.064 |
| dies8_multi_ring / mobilenet_v2 | 1.7439 | 12.8035 | 7.342 | 277.113 | 0.359 |
| dies8_multi_ring / alexnet | 5.8808 | 39.2230 | 6.670 | 277.113 | 4.720 |
| dies16_multi_ring / resnet18 | 2.0459 | 30.5966 | 14.955 | 287.056 | 0.386 |
| dies16_multi_ring / resnet50 | 5.5150 | 74.4635 | 13.502 | 287.056 | 1.024 |
| dies16_multi_ring / vgg16 | 17.0536 | 245.3017 | 14.384 | 287.056 | 6.532 |
| dies16_multi_ring / mobilenet_v2 | 1.6448 | 12.8046 | 7.785 | 287.056 | 0.200 |
| dies16_multi_ring / alexnet | 5.3598 | 38.4423 | 7.172 | 287.056 | 2.364 |

這組完整模型候選總UB128MiB、雙scratch banks；16-die每die8MiB UB、8-die16MiB、4-die32MiB。256PE、64cores、DRAM總容量/頻寬守恆。額外SRAM、PHY、IO/controller、die面積/leakage均付費；不是舊32MiB budget的免費升級。

## 同硬體 mapping 驗證

下表比較共同最佳硬體上的balanced baseline與交付的DP＋dataflow＋RL組合。兩者使用相同物理資源與完整batch oracle；百分比只對兩者均合法時列出，不將infeasible mapping的PPA當作改善基準，也不把組合收益全歸因於RL。

| 模型 | Balanced合法 | Latency變化% | Energy變化% | NoP hopbytes變化% |
|---|---|---|---|---|
| resnet18 | True | -6.23 | -1.77 | 2.27 |
| resnet50 | True | -11.97 | -3.74 | 8.12 |
| vgg16 | True | -6.10 | -2.17 | 1.24 |
| mobilenet_v2 | True | -12.06 | -6.61 | 6.15 |
| alexnet | True | -2.17 | -1.13 | 2.69 |

## 使用方式與交付位置

GUI目前可用 http://127.0.0.1:8765，載入工作ID **d09e10000001**可查看完整五模型結果。重新啟動方式見hybrid_oct09_runbook.md；本次server使用results/hybrid_gui_oct09，完整資料保存於其ID資料夾。程式不會由另一個GPT自動讀取本機路徑，請實際上傳PDF，程式核對則附GPT資料包ZIP。

Reproduce: tools/validate_hybrid_oct09.py --worker 4/8/16（各自一次），全部完成後--merge。--resume只重用相同source、fingerprint、硬體與設定且完整的trial。Config: simplified_rapidchiplet/configs/hybrid_oct09_suite.json。

## 來源與未兌現的部分

Gemini：HPCA2024，Section V-A（PDF第6頁）與five operators；INDM：Fig.3 IO cluster/multi-ring及cross-layer mapping方法。使用者Word及補充PDF第1/2/4/5點、Word內兩張書頁均已核對。公開分享只提供文字摘要，16原圖未能取回，沒有逐圖精讀聲稱。

晶片的精確layout、packet VC/arbitration、foundry/yield、thermal、BFP/FP16及跨die IC reduction不在此原型模型內。Post-op時間/SRAM有計入，独立非MAC ALU能量/面積未獨立校準。輸出package圖是實際評估幾何；die/PE圖是資源示意，不是完成place-and-route。

本次沒有外部發布或傳送他人訊息，沒有覆寫10/06舊benchmark。
