# 候選式聯合 RL DSE：動作、交易與驗收契約

日期：2026-10-31。對應使用者提供的 `RL_Chiplet_DSE_Codex_Spec.md` v1.0。

本版將固定 2×2-core compute chiplet 的合法系統模板、DNN mapping、DF tile/cache 與 pipeline group 放在同一個搜尋狀態中。Gemini、INDM、DeFiNES 提供架構與 mapping 機制依據；下列 C1–C9 是本專題的工程候選生成方式，並非這些論文的原有 RL 演算法，也不保證每個候選會改善 PPA。

## 1. 程式對照與公開介面

| 責任 | 程式 |
|---|---|
| 設計與動作 schema、A11 alias、能力矩陣 | `simplified_rapidchiplet/simple_rapidchiplet/hybrid/rl_schema.py` |
| 原子操作、交易、診斷、通用與複合候選 | `simplified_rapidchiplet/simple_rapidchiplet/hybrid/rl_actions.py` |
| environment、exact cache、objective、actor-critic、archive、checkpoint | `simplified_rapidchiplet/simple_rapidchiplet/hybrid/rl_search.py` |
| 固定 core 與合法 package 模板 | `hybrid/hardware.py`、`hybrid/architecture.py` |
| 依 tensor 區域建立工作、halo、跨層相依性 | `hybrid/mapping.py`、`hybrid/depth_first.py` |
| 付費資料搬移、完整排程與 analytical PPA | `hybrid/communication.py`、`hybrid/evaluator.py`、`hybrid/scheduler.py` |
| 實際排程推導的瓶頸與容量報告 | `hybrid/diagnostics.py` |
| Tangram-style DP/beam 初始化與來源界線 | `hybrid/tangram_seed.py` |
| 使用者輸入、模型、報告與共同架構整合 | `simplified_rapidchiplet/rl_dse.py` |

此表中 `hybrid/` 皆相對於 `simplified_rapidchiplet/simple_rapidchiplet/`。

```python
state = DesignState(
    architecture_candidate_id=candidate.id,
    mapping=seed_mapping,
    model_hash=workload.fingerprint,
)
result = run_joint_search(
    workload, state, architecture_candidates,
    evaluator_factory=lambda candidate: evaluator_for(candidate).evaluate,
    objective=JointObjective(...),
    config=JointSearchConfig(...),
    checkpoint_path=output / "checkpoint.json",
    resume=False,
    evaluator_identity=source_identity,
)
```

`DesignState.mapping` 是唯一有效 mapping 決策來源，內含 groups、fusion stacks、microbatch、每層 B/K/H/W partition、有序 core 配置與 DRAM selectors。`precision_config`、`routing_config`、`scheduler_config`、模型與硬體版本也在設計 identity 內。報告與剩餘預算不屬於物理設計 identity。

`ActionPlan` 保存 base state hash、明確參數的 `ordered_edits`、family、targets、來源、提案原因及完整失效範圍。`StepResult` 分開記錄 valid、rejection、reward、terminated、truncated、實際 plan、物理報告與最佳可行解 ID。

## 2. 10 個唯一正式原子動作

使用者舊版「11 actions」的 A11 與 A9 語意相同。`ActionEdit("A11", ...)`、舊版 ActionPlan 載入及建構立即正規化為 A9；policy embedding 僅有 A1–A10 十個原子欄位。沒有獨立 A11 transition、reward 或第二份抽樣機率。

| ID | 明確參數 | 本版前置條件與連動 |
|---|---|---|
| A1 | `operation`、`layer_ids`、`tile_hw`；shift 可含 `previous_layer_ids`，split 可含 `boundary` | 融合僅接受 contiguous、closed、single-exit 子圖。本版 backend 要求一個 fused stack 恰佔一個 pipeline group，比「包含在 group」更保守。分支的真實 DAG 相依性不刪除。部分拆分需同交易提供相容 A10 group。 |
| A2 | `layer_id`、`partition=[B,K,H,W]` | 正整數、非空 tensor shards，乘積等於該層配置 core 數。不提供 package input-channel C partition。重新推導全部相關 tensor 區域與流量。 |
| A3 | `layer_ids`、`tile_hw=[H,W]` | 只改既有 stack 的末層 DF tile；前層依 receptive field 回推。實體執行可在該 DF 工作範圍內建立容量合法的 temporal microtiles，不覆寫 RL 選定的 stack tile/cache。 |
| A4 | 明確 `mapping_action`，或逐層 `allocations={cores,partition}` | donor 保持可執行。跨層 transfer 僅在同 spatial group；單層可取得/歸還合法 idle cores。不同時間可重用 core，同時 spatial 配額不可重疊。 |
| A5 | `layer_id`、完整有序 `cores` | 保持 quota；可交換 partition 對應位置或 relocation 到合法 idle core。若改數量須用 A4。 |
| A6 | 兩層 ID、等長且不重複的兩組 indices | 同 spatial group，等量交換；quota 不變。 |
| A7 | `layer_ids`、布林 `cache_h/cache_v` | 支援 `(0,0)` recompute、`(1,0)` horizontal cache、`(1,1)` full cache。`(0,1)` vertical-only 未支援。無 overlapping receptive field 時不生成重複 cache 模式；dilation 會納入 overlap 判定。 |
| A8 | `tensor_id`、`configuration_id` | 權重使用 `weight:<layer_id>`；activation 使用原始 tensor ID。只接受 package 的 DRAM endpoint 或 backend 支援的 interleave。同步 producer output 與 consumer selectors；不建立免費副本。跨 group activation 實際來源由 producer 的 materialization 決定。 |
| A9 | `architecture_candidate_id`、完整目標 `mapping` | 僅可切到合法模板。完整 mapping 是必填，移除的 core/DRAM 不可殘留引用。新硬體的 compute、IO、DRAM、link、SRAM、面積、靜態與動態成本全部重建。這是設計時規模/模板變更。 |
| A10 | 完整 `groups`、可選 `microbatch_size`、可選完整 `mapping` | groups 必須依拓撲順序恰覆蓋所有 layer，保持 stack/group 相容。microbatch 必須整除原始 workload batch，不改使用者的工作量。 |

同 compute 數的 mesh shape/IO 模板變更屬 A9，不能被標成 C2 擴容或 C3 縮容。

所有動作在 shadow state 內執行；中間步驟沒有獨立排程、reward 或 PPA。完整交易通過結構與物理可執行檢查後才提交。A9 內的完整目標 mapping 讓縮容先完整規劃撤離；C3 的 edit 清單先指定 shadow target，再列出實際 partition/placement/storage，實際 commit 仍在所有 edits 與完整評估之後。

## 3. 複合候選與診斷界線

| Family | 本版有序操作 | 證據與候選範圍 |
|---|---|---|
| C1 | A4 → donor/receiver A2 → A5 realization | 需要有可平行度的 critical compute 診斷；donor 至少有 schedule slack。多種合法份額由完整 evaluator 判斷，未把 slack 當成保證低損失。 |
| C2 | A9 → 逐層 A2 → A5 → 必要 A8 | 相鄰較大 compute 模板的探索與重新配置。新增硬體成本與 IO/DRAM 配套均由模板計算；未假設增加 compute 就增加 DRAM bandwidth。 |
| C3 | 目標撤離 mapping 的 A9 → A2 → A5 → A8 realization | 相鄰較小 compute 模板；一次交易提交完整新設計。 |
| C4 | producer A2 → consumer A2 | 固定 quota 與區段外 mapping，協同產生相鄰分割。generic pool 另保留只改 placement 的候選。所有 DAG consumers 的真實交接在完整評估時重建。 |
| C5 | A5/A6 + A8，或 A8 + A5 | 將有 queue wait 的時間窗 `flow_id` join 到 report 中實際 producer/consumer work-unit owners，再修改該 flow 的合法 external/materialized tensor 入口與相關工作位置。只有累積 bytes 高、只有 unrelated layer，或 compact report 未能識別 flow 時不冒稱 targeted C5；generic 探索仍保留。 |
| C6 | A1 → 不同 sink A3 → A7 | 合法閉合子圖的 fusion/tile/cache 協同。無 overlap 時明確使用 recompute；不生成無效 full-cache 變體。 |
| C7 | 縮 A3 → 減 A7 | 探索容量/重算取捨。backend 不支援 spill；超容量候選不會取得假的 PPA。A1 拆融合也保留為原子替代。 |
| C8 | A3 → A7 | 包含 tile 長寬調整、較大 tile/cache，以及較小 tile/recompute 方向；結果由權重重載、MAC、cache 讀寫與排程共同決定。 |
| C9 | A10 → 各新 group A4 → A2/A5 | 將分組邊界、資源配額與整數分割一併修改，固定使用者的原 workload。 |
| C10 | 關閉 | 可選 communication-aware partition DP 尚未在此 engine 啟用；不能把初始化的 Tangram-style DP/beam 當作 C10。 |

A4/A9 自身必須維持完整可執行 mapping；macro 額外列出其 linked A2/A5/A8 的**實際參數**。這些 realization 不會再呼叫 mapper、不另領 reward、不另計成多個 environment steps。C6–C9 的一部分候選是工程探索方向；不宣稱每一個都有充分的唯一瓶頸歸因。

診斷輸入來自已執行的 schedule。沒有足夠證據時使用 `unknown`。DRAM/NoC/D2D 個別 wait 無法從 atomic-route reservation 唯一拆分時保留 null；busy/wait 可能跨資源重疊，不能全部相加成 latency。DF per-stack ledger 未能精確拆分的欄位也保留 unknown。

## 4. 三層候選機制

1. **Hard validity**：先驗證模型、template、precision、partition、group、resource、端點與 DAG 語意；已經被完整 evaluator 判定不可執行的 exact state 會進入可持久化的 hard mask。未知容量候選須付費評估才能確定。
2. **Candidate shortlist**：診斷 guided pool 與獨立 generic pool 合併，依最後 shadow-state fingerprint 全域去重，再作有 seed 的 bounded shortlist。這是近似候選限制，不是安全剪枝定理。
3. **Policy**：線性 softmax actor 根據 state/candidate features 選擇；候選在 list 中的 index 沒有永久語意，論文/診斷 prior 不直接修改 logits 或 PPA。

`shortlist`、`random_quota`、`max_per_family` 都是工程超參數並輸出到報告。composite 模式要求 `shortlist >= 2`。當合法 generic 與 macro 都存在時，即使 `random_quota >= shortlist` 也至少各保留一個名額；quota 是最大 reservation。若診斷沒有可用 macro，仍使用 generic；已知不可執行 cache 使 shortlist 清空時，先擴大 generic pool 四倍再重試。仍無候選會標 `candidate_generation_stalled`，不當成使用者 PPA 條件必然無解的證明。

可比較 `atomic`、`guided_atomic`、`composite` proposal，以及共用候選/evaluator 的 `rl`、`random`、`greedy` selectors。

## 5. Objective、reward 與提交

episode 使用固定 reference：

```text
J = Σ normalized_weight_i * metric_i / initial_metric_i
V = Σ max(metric_i / hard_limit_i - 1, 0)
Q = J + violation_penalty * V
r = Q(old) - Q(new)
```

PPA 權重非負且正規化；energy 可另行加權，預設 energy weight=0，並獨立輸出。soft goal 的超額比例加到 J，與 hard feasibility 分開。所有 references 在 episode/continuation 中固定。

actor-critic 使用 NumPy 實作，`gamma=1`，TD value baseline，預設 actor/value learning rate 為 0.03、entropy coefficient 為 0.005。繼承的數值保護將 advantage 限制在 [-4,4] 並限制 update norm；trace 的 reward 保存完整物理差值。沒有「多 chiplet」「少 hops」「少 bytes」的額外獎勵。每步保存實際 behavior probability/log-probability，未混入 epsilon policy。

結構錯誤或物理不可執行的 trial 原子 rollback，記錄 rejection，沒有虛構數值 PPA，沒有物理 reward 的 actor update。原探索 state 不變。合法但 PPA 超額可以在設定允許時繼續搜尋；合法但 objective 更差的 trial 仍提交，不套 SA acceptance。

固定 horizon 結束後回到同一個可執行 Tangram seed，policy 與 global archive 保留。reward 的 telescoping 性質適用於每段固定 horizon episode；不同 episode 的 reset 不是免費的改善動作。

## 6. 可行解、成本與回報

`current_state` 保存探索位置；`best_state` 只保存滿足所有 hard PPA 限制的歷史設計，兩者分開。`architecture_archive` 對每個已評估架構保存最佳 executable entry 與 `strict_feasible`。`closest_state` 依 `(V,J)` 排序保存診斷用候選。

當沒有可行解時，`best_state=None`、`strict_feasible=false`。closest 候選不能被包裝成推薦的可行解。平均功率由 evaluator 宣告的相同 workload 能量/時間窗計算；峰值功率與實體 signoff 沒有模型支持。

exact cache key 包含模型與完整 DesignState fingerprint、完整硬體參數及 evaluator/source identity。mapping 的 grouping、partitions、有序 placement、tile/cache、DRAM、collective、precision、routing/scheduler 都會使 key 失效。evaluation report 與 remaining budget 的變化不會讓同一個物理設計重算。本版沒有增量近似 PPA；A9 與其他未知 trial 都走完整 oracle。

`evaluations` 為累計 unique full-system query 數（含 RL 初始設計）；`requests` 包含 exact cache hits。transaction/candidate generation 不呼叫 full oracle，耗時另計 `proposal_elapsed_s`。greedy 的每一個 lookahead oracle query 也計入同一 budget，不能聲稱只花一次評估。初始化 Tangram 與 report replay 由 production orchestrator 的 accounting 另外列出，不能漏列為免費搜尋。

## 7. Checkpoint 與 resume

checkpoint 保存 policy/value weights、RNG、episode position、目前/最佳/closest state、逐架構 archive、exact cache、物理-invalid identities、reference、trace、累計 query 與時間。暫存檔完成後 atomic replace。

模型、硬體、初始設計、objective、來源 identity、feature schema、proposal/learning/horizon 設定不同會拒絕續跑。cumulative `budget` 與 `max_steps` 可以提高。RL 的 budget 中斷與 step 中斷，續跑的 action、behavior probability、reward、state、query counts 均有直接測試對照一次跑相同總預算；耗時數值受實際機器執行影響。

**Greedy resume 限制**：若 query budget 在同一步 lookahead 候選集合中途耗盡，greedy 會比較當時已付費的候選前綴並提交。因此增加 budget 後續跑 greedy，不保證與一次給較大 budget 的 greedy 走相同路徑；此限制不影響已計入的 query 數或 archive 的可行性。RL 的上述 deterministic continuation 契約不套用到這種 greedy lookahead 中斷。

## 8. 驗收

執行：

```powershell
cd simplified_rapidchiplet
..\.venv\Scripts\python.exe -m unittest tests.test_joint_rl tests.test_rl_acceptance -v
```

本次 28 tests 通過，包含：

- A11→A9 只有十個 policy atom；no-op 不改 identity/PPA、不多花 query。
- macro 中途失敗、未知端點、不可執行 memory plan 的 rollback，且不製造假 reward。
- C1–C9 多 edit realization 與跨 pool final-state 去重；shape-only A9 不誤標縮容；generic quota 不吃掉全部 macros。
- C5 只根據可識別的 queued flow owners；無 overlap 時移除 cache 變體。
- native Gemini evaluator 上 chain/residual 的 1→2→1 chiplet 擴縮；MAC 與 output 覆蓋守恆；無 dangling core/memory；fresh evaluator 的還原 PPA 一致。
- 非關鍵支路改善不憑空縮短 E2E；hops 減少仍可能因共享壅塞而變差。
- 非整除 tail/halo、shortcut/cache/psum/weight 同時存活容量、單埠 GLB 資源競爭與最小 tile 超容量拒絕。
- gamma=1 reward 手算 telescoping，沒有 action bonus。
- 真 actor update 改變 behavior probability；step/query budget 中斷續跑的 RL 與完整跑相同。
- RL/random/greedy 的所有實際 oracle 呼叫計數等於公開 full-query counter，且不超過累計 ceiling。

C10、vertical-only overlap、package C-split reduction、任意 routing/floorplan、spill、peak power 與 physical signoff 都明確未支援。本文件不能被解讀成已證明全域最優、所有大模型的搜尋品質，或 RL 必然勝過共用 evaluator 的其他方法；實驗結果需另看同預算、多 seed 的紀錄。
