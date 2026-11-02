> 更新：使用者最新的16nm成本基準與strict/soft限制修正，請先看 [hybrid_cost16_sources.md](hybrid_cost16_sources.md) 與 [hybrid_cost16_progress.md](hybrid_cost16_progress.md)。本檔下方數值屬歷史版本；舊混合製程／MAC乘8推導已撤回，不可當成新成本。

> 2026-10-11新授權：已新增跨層Tile/Fusion/Reuse內層DP與可執行DF DAG，RL外層mapping維持五operators。現況／驗證以 [hybrid_df_dse.md](hybrid_df_dse.md) 為準；下方舊freeze不適用於此次明確授權的新功能。全回歸與真實模型驗證結果保存於output/df_joint_20261011。

# INDM + Gemini 融合 DSE 進度

**2026-10-09新增軟體交付已完成**：使用者10/08的新要求（七種模型、四種偏好GUI、實際布局圖、whole-DAG traffic DP、片內dataflow與付費雙buffer）與15組完整模型驗證、13頁PDF見 `docs/hybrid_oct09_progress.md`、`hybrid_oct09_validation.md`。分享聊天16原圖未取得，逐圖核對仍需使用者直接提供。下方10/06數字與freeze保留為舊交付紀錄，不與新source混用。

啟動：2026-10-05 23:35 Asia/Taipei。依使用者本次目標重新設計，不以舊 phase 1–10 作驗收邊界。

狀態：**complete（可執行研究原型）**，2026-10-06 08:30 Asia/Taipei全部必要驗收及補充RL512已完成。主機約03:35至08:16有暫停，不能用這段wall time評估效能。Hourly heartbeat indm-gemini-dse依完成條件停止，後續heartbeat若仍queued應直接核對此complete狀態，不重啟任務。

共同設計：cluster 間 IO mesh；每 cluster 至多4 compute dies及1 DRAM；每 die 16 PEs、每PE16 lanes×16 vector MAC；每die4個mapping core slots，每slot4PE；WL/AL/OL L1/L2 加2MiB unified buffer（融合extension，計入成本）；INT8 activation/weight、24-bit psum。Gemini layer-group/microbatch pipeline；RL五operator改Part、core ordering、跨layer core swap、core reallocation、DRAM source。端點字串 compute:0/core:0、io:0、memory:0，package nodes為compute:0等physical die，避免typed ID碰撞。

分工（同一共享workspace，多agent工作時避免覆寫）：
- hardware_backend：hybrid/hardware.py、rapid_backend.py及對應tests。
- mapping_frontend：hybrid/workload.py、mapping.py、communication.py及對應tests。
- gemini_methods：hybrid/actions.py、search.py及對應tests。
- root：architecture文件、OnDieModel、scheduler/evaluator、CLI/reports、整合測試與validation結果。

已完成（請核對實際tests，勿重做）：硬體nativeRapid cluster mesh與costprofile；integer mapping/halo/residual/INT8 post-opfusion；五operators+learnedactorcritic+checkpointexactresume；groupingbeam/balancedallocator、六個iso-resource architectures；scheduler/evaluator三phase/data/resourcecalendar+有限microbatchwindow；persistent weight exact-regionreuse占fullUB直到unit完成；DRAMresidentcapacity；CLI hybrid_dse.py/report.py；11+7+11+12+6 hybrid behavior tests，root新增10evaluator/scheduler checks。

重大修正：原globallyearliestready heap在fullResNet fanout退化O(N²)，batch1耗7056s。現預設deterministic priority list scheduling，依caller group/MB/layer順序放resourcecalendar gaps，保留earliest policy僅小toy核對，不claim最優排程。BalancedResNetbatch1已FEASIBLE：73fusedlayers、1599units、8809transfers、4.089184256G MAC精確；oracle約21.5s；UBmax1.39MiB<2MiB。當時ondie版本未加入bankmicrokernel，所以PPA只是preliminary，不可當最後結果。

最終程式已freeze，請勿改 `simple_rapidchiplet/hybrid/*.py`：bank-backed microkernel、perPE L1 max、normalized memo、compact search result均完成。全回歸143 tests PASS，69 hybrid tests PASS；log在 `simplified_rapidchiplet/results/hybrid_unittest.txt`。CLI evaluate/search/beam/import/architecture與full trace都已通過。Exact checkpoint8 vs4→8與unit tests已通過。若必須修新的correctness bug，需作新的source identity與重驗證，不可混入現在的數字。

正式同source結果：`hybrid_search_validation_final/` 的24 trials，3 seeds×4 methods×2 proposals、64/128 queries，已全部完成。128-query cluster-guided mean±SD：RL0.42059±0.13422、greedy0.32802±0.06163；uniform RL0.54877±0.08477、greedy0.37318±0.03089。Greedy目前平均最好，不能宣稱RL全面優勝。RL-only512六trials也已全部完成：uniform0.36763±0.14436、guided0.32285±0.15683，不與128-query baselines作公平優勝比較。

六個iso-resource toy RL16 architectures與完整ResNet50 batch1 balanced architectures已完成：完整ResNet所有候選合法，4ring10.3165ms、8ring7.7373ms、16ring6.4138ms，mesh各14.4279/9.5616/6.9368ms。Small toy偏好4die，而完整ResNet偏好16ring；不是通用最優結論。完整toy結果/trace在 `hybrid_toy_final/`，圖表在 `hybrid_figures/`。

ResNet容量正式驗證已完成：2MiB batch1 g3合法，UBpeak1,073,760B；batch8 g3 cold/persistent需要3,682,912B，兩者皆超容量，不計任何gain。4MiB同一mapping重新付出native area/idle/placement成本，cold與persistent皆合法：latency34.7303→28.8940ms（−16.80%）、energy0.508599→0.472101J（−7.18%）、DRAM read−62.63%。Silicon216.3990mm²、idle2.68849W。正式五列與成本在 `hybrid_mapping_capacity_validation.json`，未重跑已保存的base。

Agents/process：mapping_frontend的4MiB與ResNet batch1四methods8-query全完成，RL7次policy updates，greedy此smoke最佳；gemini_methods的RL512曲線與exact8 vs4→8 verification全完成，workers已exit；hardware_backend只讀驗收完成；root已完成validation文件、PNG/SVG圖表視檢與交付manifest。勿重啟任何benchmark。

可選batch8 temporal g1 baseline已按wall-time上限停止，前3個完成cases保留、無未完成PPA宣稱。唯讀診斷：g1 37,320 units/4,665 normalized cache keys超過4096-entry LRU，以microbatch外層循序重算；g3 12,792/1,599全可保留。這是evaluator runtime限制，不是加速器性能或pipeline speedup證據。

交付入口：`docs/hybrid_validation.md`、`docs/hybrid_architecture.md`、`docs/hybrid_runbook.md`。Machine audit：`simplified_rapidchiplet/results/hybrid_delivery_manifest.json`；不用重跑模型即可用 `tools/audit_hybrid_delivery.py`核對結果/source/native hashes與已保存資源日曆。必要工作無待辦；可選temporal基線、PPA/RTL校準與更強policy列為後續研究，未用未完成數字支持本次結果。

後續接續請先看本檔與docs/hybrid_architecture.md，核對仍在執行的agents與process、實際files/tests，不要重跑已完成步驟。核心程式舊版本留供回歸；新入口使用simple_rapidchiplet.hybrid。
