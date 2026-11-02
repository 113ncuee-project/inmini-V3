# 使用 GUI 與重跑新多模型搜尋

## GUI

在專案根目錄PowerShell執行：

```powershell
.\simplified_rapidchiplet\scripts\start_hybrid_gui.ps1
```

開啟 `http://127.0.0.1:8765`。四種偏好、模型multi-select、PPA上限、4/8/16die、ring/mesh、總UB與付費單/雙buffer均可選。按「開始共同探索」後工作在local worker執行，頁面每5秒更新；完成後查看每個model/hardware的PPA和共同最佳，點「查看布局」可選die/layer，下載架構SVG。

預設選ResNet18與VGG16、batch1、每trial RL4/8queries、總UB128MiB。較大模型／更多queries可能需要數分鐘以上；進度以trial完成數表示，沒有把evaluator CPU秒當成晶片延遲。點選toy可快速驗證流程。

每個工作都有12位ID，存於頁面及瀏覽器localStorage；相同server output資料夾重啟後可載入保存的complete工作。不要同時啟動兩個server占用8765，停止server用該terminal的Ctrl+C。關閉server時running jobs不保證自動恢復；CLI RL checkpoint可精確resume，GUI此版只支援載入已完成結果。

localhost server只有一個DSE worker，拒絕重複提交、任意model字串、shell參數、非有限上限與超大body。它不需雲端服務或預訓練權重下載。預設啟動腳本使用 `simplified_rapidchiplet/results/hybrid_gui_oct09`，可直接載入本次15 trials的工作ID `d09e10000001`；`-Out` 可明示其他資料夾，`-Port` 可改埠號。

## 可重現多模型架構比較

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet\hybrid_gui.py --suite-config simplified_rapidchiplet\configs\hybrid_oct09_suite.json --out simplified_rapidchiplet\results\my_suite
```

該JSON包含ResNet18/50、VGG16、MobileNetV2、AlexNet、4/8/16die multi-ring、batch1、seed7、RL4queries、traffic_dp及dataflow auto。共15個完整224-input trials。UB成本跟資源選擇一起保存；若超容量會明示failed/infeasible，而非刪除失敗案例。原10/06 results和10/09初步diagnostic results不參與正式排名。

若先前suite被中斷，同一command加 `--resume-suite`；只有DAG fingerprint、完整hybrid source hashes、HardwareSpec及搜尋設定均相同且輸出完整的trial才會重用。缺漏／變更會重新評估，config不符時要求新output folder。這是以保存結果接續，不需要重新跑已驗證trial。

## 單模型CLI

```powershell
.venv\Scripts\python.exe -X utf8 simplified_rapidchiplet\hybrid_dse.py --model resnet18 --batch 1 --mode search --planner traffic_dp --dataflow auto --prefetch-slots 2 --preference balanced --budget 8 --out simplified_rapidchiplet\results\my_resnet18
```

CLI `--model` 支援toy、resnet18/34/50、vgg16/19、alexnet、mobilenet_v2。原energy/latency/EDP objective、baseline methods、beam、mapping import、checkpoint/resume及full NDJSON trace仍保留。`--max-latency` 是seconds，GUI欄位為ms並轉換。`--preference`會override原objective權重，四種模式見architecture文件。

## 結果核對

每trial：summary.json、run.json、mapping.json、workload.json、hardware.json、network.json、buffers.json、layer_switching.json、timeline.csv、link_traffic.csv、architecture.svg、package.svg、die.svg、pe.svg、layout.json/html、search.json及checkpoint.json。

Suite：config.json、trials.json（逐trial保存）、suite.json（完整幾何平均排名）。GUI另保存job.json。summary.metrics有evaluator identity及所有hybrid模組SHA256；完整trials應與同一次source核對，不與舊版比較相對reward。圖與JSON可獨立讀取；本機路徑本身不能讓另一個GPT讀到內容，請實際上傳PDF或JSON/程式資料包。

全測試：

```powershell
$env:PYTHONPATH='simplified_rapidchiplet'
.venv\Scripts\python.exe -X utf8 -m unittest discover -s simplified_rapidchiplet\tests
```

NativeRapid需要 `C:/Users/user/Downloads/rapidchiplet-main (2)/rapidchiplet-main`，可用CLI `--rapid-root` 指向相同engine。沒有engine時hybrid會報錯，不把proxy當作native結果。
