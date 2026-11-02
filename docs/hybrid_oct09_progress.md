# 2026-10-08/09 新要求：硬體／多模型／GUI

狀態：**本次軟體交付 complete**，2026-10-09 Asia/Taipei。程式、15組完整模型、GUI、13頁PDF渲染與可搜尋中文均已驗證；16張原始照片的逐圖核對仍需使用者直接提供。舊 `hybrid_progress.md` 的10/06 complete僅適用舊交付。本次結果放 `hybrid_oct09_*`、`hybrid_gui_oct09`，舊數字不覆寫。

已實作：七種 torchvision FX/meta 真實 DAG（ResNet18/34/50、VGG16/19、AlexNet、MobileNetV2）；四種 E/A/D 指數偏好與Power硬限制；多模型共同架構搜尋；whole-DAG live-frontier DP + RL；可選片內 loop/tile；付費雙 L1/L2 scratch banks 預取；每次保存真實 package／die／PE SVG 與可點選 layout；stdlib localhost GUI、硬性 PPA 上限、工作保存／重載。

已驗證：全回歸156 tests PASS（82 hybrid），記錄於 `simplified_rapidchiplet/results/hybrid_oct09_unittest.txt`。新增prefetch正向重疊與bank reuse、隨機800步indexed-vs-naive LRU差分、設定/來源不符resume拒絕、跨程序模型fingerprint一致等均PASS。GUI真實瀏覽器成功提交toy RL、切換偏好、點compute:3、切layer，無JS errors；硬性Area=1mm²失敗呈現正確。最終五模型工作成功載入15列、restore設定、點compute:15、切layer及reload；`output/hybrid_oct09/gui_qa.json` 保存證據。已修正SVG文字攔截點擊、三級架構SVG duplicate attributes，XMLparse与瀏覽器render均通過。

完成：最後E/A/D目標的15個完整224-input trials合併與source/trace audit，15/15可行。均衡模式共同最佳16 compute +4 IO +4 DRAM；同硬體baseline比較，五模型latency降低2.17%–12.06%、energy降低1.13%–6.61%，NoP hopbytes反而增加1.24%–8.12%，故不宣稱所有通信都下降或將收益全歸給RL。詳細數值见 `hybrid_oct09_validation.md`。VGG16 indexed cache的CPU加速不算晶片PPA改善。

正式目標已核對Gemini V-A，採E^wE A^wA D^wD，Power作硬性上限；先前P/A/D diagnostic僅保留歷史，不參與正式排名。四種偏好的Energy係數為均衡1/3，低功耗0.8，小面積/低延遲0.1。不要將Power×Delay抵消當作低延遲收益。

最新matrix入口：`tools/validate_hybrid_oct09.py --worker 4|8|16`，三個worker均已正常完成。`--merge` 嚴格核對全部當前hybrid source hashes、真實圖數量／SVG XML、timeline dependencies/resource calendars、energy ledger、MAC、NoP hopbytes與buffer容量，生成可載入GUI的job ID `d09e10000001`。`validation.json` 全部通過；`ablation.json` 为相同硬體baseline。修正了callable repr中記憶體位址造成不穩定的DAG fingerprint，正式15trial已用修正後同版重跑。

來源限制：使用者Word及補充PDF均已讀（1/2/4/5點）、Word內兩張筆記／書頁圖片已看。Gemini V-A在PDF第6頁：原目標MC^α E^β D^γ、多模型E/D幾何平均。本GUI以Area代理MC，保留E與D，沒有宣称製造金額／良率模型。INDM對照沿用已讀來源註記。

分享聊天可公開讀到文字摘要，原16张圖片在匿名頁只顯示「已上傳一個圖像」，沒有原圖。HTTP檔案路徑要求認證；匿名瀏覽器確認img=0。已按可讀摘要與Word書頁採用capacity-backed雙buffer、片內reuse與FC權重頻寬原則，不冒稱逐張精讀原照片。不讀帳號cookie或繞過限制。

目前GUI http://127.0.0.1:8765 使用最終source，parent PID曾19540；需動作時先核對實際child/full command。預設啟動腳本已指向本次 `hybrid_gui_oct09` 輸出，不需重新搜尋即可載入ID。沒有啟用舊agents；不要再重複啟動訓練或worker。

交付目錄：`output/hybrid_oct09`（SVG/PNG、GUI截圖、PPA圖、GPT_review_code_and_results.zip、delivery_manifest.json）；13頁PDF `output/pdf/INDM_Gemini_MultiModel_GUI_20261009.pdf` 已視檢中文字型、表格跨頁、架構圖與GUI。四種偏好另用當前source跑完12個toy trials；同一硬體被四種偏好選中是合法結果，不強制不同答案。停止本次接續排程；後續已排隊heartbeat請直接核對此complete狀態，不重啟worker。原16張照片逐圖核對需使用者直接提供原圖；不靠重跑DSE解決。
