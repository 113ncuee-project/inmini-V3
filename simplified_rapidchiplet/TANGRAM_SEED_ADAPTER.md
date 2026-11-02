# Tangram-style RL 初始化契約

`simple_rapidchiplet/hybrid/tangram_seed.py` 提供 `build_tangram_seed`，由使用者模型的完整 operator/tensor DAG 建立初始 mapping，再交給相同的完整 evaluator 選擇 RL 起點。初始化不改精度、算子、權重、shortcut 或 Add 的輸入。`dag_snapshot(workload)` 提供可供視覺化的 nodes、tensor metadata 與每一條有序輸入 edge。

已核對使用者提供的 Tangram PDF §3.3、§4.2（印刷頁 814–815）：其搜尋沿 DAG 拓樸順序使用 DP 與 beam，探索 inter-layer pipeline、intra-layer partition 與 loop blocking。來源：[Tangram, ASPLOS 2019](https://doi.org/10.1145/3297858.3304014)。

也核對提供的 `GEMINI-HPCA2024-master.zip`：實際 main 在 `src/main.cpp:1496` 呼叫 `DP_search`；`src/spatial_mapping/segmentation.cpp:914` 的 `search_best_batch` 測 segment 的 batch divisors，`:991` 的 `DP_search` 選 contiguous segments，`:1093` 再呼叫 `SA_search_SPM`。該 member 的 SHA256 是 `1634abd4f3af8a1912a87249950c7351890bd1970d6782f66586978108a1ded8`。`src/spatial_mapping/DP.cpp` 則只有空的 `DP::transfer`，不能當成已整合的搜尋器。

目前交付的是明確標示的 **approximate adapter**：重用本專案 `planner.propose_plans` 的 bounded graph-cut DP/beam 與平衡整數 core allocation，加上 Tangram 的「新層與 segment prefix 有資料相依或共用 input」候選規則，並保留單層 sequential baseline。這是候選產生的工程先驗，不是 hard validity mask。每份候選都仍保留所有 DAG 入／出邊，最後由完整 evaluator 判定容量、流量、排程與 PPA。

與原版的差異會保存在每份結果的 `provenance`：

- 沒有執行原始 Tangram `nn_dataflow` 或 Gemini C++ binary；不宣稱原版輸出或可重現論文數值。
- `max_group_layers`、`beam_width` 與 `max_candidates` 是近似搜尋預算。
- 現有 mapping schema 每份 plan 只有一個 microbatch size；原始 Gemini 可以逐 segment 選不同 batch。
- 使用現有 INT8/INT24 core mapper 與共享 evaluator，沒有移植 Tangram 的 BSD rotation 或 ALLO timing。
- 原始 C++ 的 network、mapping、cost 與本專案的 operator DAG/precision/resources 不同；直接將其 scalar cost 當作本系統 PPA 或 reward 不正確。未完成這些 schema、同步與成本轉接前，原始 backend 保持 unsupported。

## 呼叫方式

```python
from simple_rapidchiplet.hybrid.tangram_seed import build_tangram_seed

seed = build_tangram_seed(
    workload, package.mapping_core_ids, package.memory_ids, hardware,
    evaluator=evaluator,
    objective="edp", microbatch_sizes=(1, 2, 4),
    max_group_layers=4, beam_width=4, max_candidates=8,
    max_evaluations=8,
    # 可由 orchestrator 使用固定 PPA preference/reference 計算有限 penalty。
    # score_fn=lambda metrics: fixed_episode_cost_plus_violation(metrics),
)
if seed.plan is None:
    # 查詢 seed.evaluation_records，回報無可執行起點；不建立假的 PPA。
    raise RuntimeError(seed.status)
initial_plan = seed.plan
initialization_record = seed.to_dict()
```

`evaluator` 可為 `callable(plan)` 或具備 `.evaluate(plan)` 的實例；回傳 metrics dict，或具備 `.metrics` 的 evaluation object。完整成本欄位至少需要有限正值的 `latency_s` 與 `energy_j`。`feasible=False` 表示 evaluator 判定無合法容量／執行方案，初始化不得選用。使用者 PPA 限制由 orchestrator 評估；可執行但超過 PPA 限制的方案可以作為 RL 改善起點，所以 `score_fn` 對這類方案應回傳有限 violation penalty。

結果提供 `.plan`、`.metrics`、`.candidates`、`.selected_index`、`.status`、`.provenance`、`.evaluation_records`、`.evaluator_queries`、`.full_evaluations`、`.cache_hits` 與 `.to_dict()`。沒有 evaluator 時明示 `proposal_only`，metrics 為 `None`，不能當成評估完成的 PPA。所有候選皆未通過完整 evaluator 或預算為零時，plan 為 `None`。

`proposal_elapsed_s` 包含全部 bounded proxy 搜尋與 baseline 提案時間；`evaluation_records` 逐筆記錄 evaluator 成功、拒絕、例外與耗時。若 evaluator 暴露 `evaluations`／`cache_hits` counters，也會記錄每次增量；沒有 counter 時明示 `None`。這些初始化查詢也必須加入 orchestrator 的總成本預算。

## 驗證

在 `simplified_rapidchiplet` 執行：

```powershell
python -m unittest discover -s tests -p test_tangram_seed.py -v
```

7 個測試包含：非整除 H/W/K 的尾塊元素覆蓋與互不重複、MAC 守恆、residual Add 兩路輸入與 producer 相依、完整 evaluator 取代 proxy 排名、失敗查詢記帳、PPA preference callback、預算耗盡、無合法方案與可重現性。額外以既有 native RapidChiplet／HybridEvaluator 跑小型 residual fixture：3 次查詢、3 次完整評估、取得合法 mapping；此為 adapter 整合檢查，不是使用者目標硬體或論文 PPA 的重現實驗。
