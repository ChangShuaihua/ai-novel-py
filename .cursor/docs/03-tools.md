# 工具契约

工具是创作代理和文件之间的唯一出入口。代理不直接读写书籍目录。写工具单文件原子；`commit_chapter` 额外使用 [提交 Saga](02-domain-store.md)。所有写工具禁止并发。成功后追加检查点。已有相同 `scope + step + digest` 时直接返回已有产物。

返回值是事实 JSON。可以带 `next_step` 告诉当前代理下一步通常调用哪个工具。禁止夹带“去叫另一个代理”这类调度句。

## 错误分层

| 情况 | 谁处理 | 动作 |
|---|---|---|
| 参数非法 | 工具 | 校验错误上抛，代理改参数 |
| 缺前置工件、阶段冲突、在途提交章节不符 | 工具 | 冲突上抛，代理先读 `novel_context` |
| 网络超时、流中断 | 模型适配 | 就近重试，默认 3 次 |
| 429 / 503 | 模型适配 | 切到该角色的备用提供方 |
| 鉴权失败、模型不存在 | 模型适配 | 终止上抛，不重试 |
| 流空闲过久 | 代理循环 | 最多 7 次，不出这个代理 |
| 代理失败且不是确定性代码错误 | 引擎 | 同一指令再跑一次，仍失败则交裁定 |
| 参数错误、未知代理等代码错误 | 引擎 | 直接暂停，重试没有意义 |
| 同一指令反复无进展 | 引擎 | 第 3 次问裁定，第 5 次熔断暂停 |

## 读工具

任何时候可调用，不改文件，不写检查点。

### `novel_context`

按范围装入足够让模型独立决策的事实。

- `chapter=N`：前情摘要、伏笔、角色状态、文风与用户规则、相关章节推荐、下一章预告、该章机械违规（若有）。
- 规划师路径：已完成卷和当前卷的弧摘要、角色快照、大纲反馈池、设定是否齐全。长篇概览只带当前弧的章节详情，其余卷弧保留骨架；用 `volume` + `arc` 精确读取。已展开的弧返回章节，未展开的弧只返回目标。
- 已发生的正文是事实，骨架只是计划。

相关章节从四个维度反查：未收的伏笔、角色出场、状态变化、人物关系。总章数不大于 30 时不做这步反查。

### `read_chapter`

读取已提交的 `chapters/NN.md`，供写作者找回语气。章不存在则冲突。

## 写工具

### `save_book`

保存 `title` 与 `synopsis` 到 `meta/book.json`，并刷新 `book.md`。检查点步骤 `book`，范围 `global`。

### `save_foundation`

设定的唯一持久化入口。只在对话里输出 Markdown 或 JSON 等于丢失。

`type` 封闭枚举：

| type | 内容 | 落盘 |
|---|---|---|
| `premise` | Markdown 字符串 | `premise.md` |
| `outline` | 扁平章节大纲 | `outline.json` |
| `layered_outline` | 卷弧骨架 | `layered_outline.json` |
| `characters` | 角色数组 | `characters.json` 与 `characters.md` |
| `world_rules` | 世界规则 | `world_rules.json` |
| `append_volume` | 不带序号的卷 JSON，序号由系统生成 | 追加进 `layered_outline.json` |
| `update_compass` | 终局方向 | `meta/compass.json` |
| `complete_book` | 空对象 `{}` | 校验通过后阶段变为 `complete` |

`scale` 可选，只允许 `short` / `mid` / `long`，写入 `run.json` 的 `planning_tier`。

`append_volume` 与 `complete_book` 必须带 `reason`。卷 JSON 顶层 `"final": true` 表示收官卷：该卷章节写完且弧评审、弧摘要、卷摘要都齐，就自动完本，不必再调 `complete_book`。

`complete_book` 的机械条件：大纲内章节都已写完、返工队列为空、指南针没有未收束的长线。长线要先用 `update_compass` 清空再宣告。想提前收束，用带 `final` 的收官卷，不用硬调完本。

`append_volume`、`update_compass`、展开弧成功后消费已处理的大纲反馈。这些结构操作没有持久化意图文件，失败后用同一参数重放。

### `audit_foundation`

设定文件齐全之后，规划师重读 `novel_context` 里的工件和指纹，审查跨文件是否矛盾，再调用本工具记下审查结果。有问题先改设定再审。这是规划期缺项 `foundation_audit` 的完成动作。

### `plan_chapter`

写入 `drafts/NN.plan.json`：本章目标、冲突、情绪弧线、涉及角色。步骤 `plan`，范围 `chapter`。

### `draft_chapter`

整章覆盖 `drafts/NN.draft.md`。新章初稿走这里，不走定点编辑。步骤 `draft`。必须先有本章计划。

### `edit_chapter`

只允许编辑已经完成、并且位于 `pending_rewrites` 队首的章节正文。改不在队列里的章、改尚未提交的初稿，一律拒绝。步骤 `edit`。

### `check_consistency`

对照角色状态、时间线、伏笔做只读检查，结果放在返回值里，不另存工件。步骤 `consistency_check`。必须在本章草稿落盘之后。

### `commit_chapter`

提交终稿。参数是章节号加上本章事实（摘要、钩子类型、主导情节线、状态增量等）。首次执行把规范化参数和草稿正文写入 `pending_commit`；恢复时忽略新参数。

推进顺序：

1. `started`：冻结意图和正文快照。
2. `state_applied`：正文写入 `chapters/NN.md`，并追加时间线、伏笔、关系、状态变化。
3. `progress_marked`：更新已完成列表、字数、流程、卷弧游标；返工则移出队首。
4. `signal_saved`：写检查点 `commit` 和 `meta/last_commit.json`。
5. 清除 `pending_commit`。

返回字段（事实，不是调度）：

- `next_chapter`
- `flow`
- `arc_end` / `volume_end`
- `needs_expansion`
- `review_required`（非分层书的全局审阅到期镜像；`Route` 仍以文件为准）
- `book_complete`
- `rule_violations`（机械规则命中，可空）

空正文、重复提交已稳定完成且摘要相同的章，按幂等返回，不制造第二份终稿。

### `save_review`

审阅结果落到 `reviews/NN.json`；`scope=global` 时为 `reviews/NN-global.json`。步骤 `review`。

工具不替模型打分。它校验审阅事实，再把审阅者给出的结论原子映射成流程和返工队列：

- 通过：流程回到 `writing`，不入队。
- 需重写：流程 `rewriting`，相关章进入 `pending_rewrites`。
- 需打磨：流程 `polishing`，相关章进入队列。

弧级审阅的 `issues[].chapters` 必须落在该弧章节区间内。

### `save_arc_summary`

写入 `summaries/arc-vVVaAA.json`：弧摘要、角色快照、这一弧之后要遵守的写作规则。步骤 `arc_summary`，范围 `arc`。弧级审阅未完成时拒绝。

### `save_volume_summary`

写入 `summaries/vol-vVV.json`。步骤 `volume_summary`，范围 `volume`。卷末弧摘要未完成时拒绝。

### `expand_next_arc`

系统决定要展开的下一骨架弧。模型只提交该弧的 `title`、`goal` 和章节列表。已发生内容保持不动。成功后消费反馈池。目标弧不是“下一未展开弧”时拒绝。

### `revise_outline` 与 `resolve_outline_feedback`

外部修订影响后续计划时，规划师要么用 `revise_outline` 改后续大纲，要么确认无需调整并调用 `resolve_outline_feedback`。二者都不得顺手做别的规划。成功后清除这批即时反馈。

## 写作者的工具顺序

提示词可以提醒顺序，但不能充当唯一约束。下面四层同时生效：

| 层 | 作用 |
|---|---|
| 写完即停 | `commit_chapter` 成功后结束本轮写作者。审阅者在 `save_review`、`save_arc_summary` 或 `save_volume_summary` 成功后结束。规划师在弧或卷的收尾工具成功后结束 |
| 事实护栏 | 以本轮开始时的检查点序号为界。结束前必须看到本任务要求的新检查点，否则拒绝结束。连续拦截 3 次则终止本轮。审阅者被派去写摘要时，只复读不算完成 |
| `next_step` | 每个写工具的返回值写明下一步工具名 |
| 前置条件 | 没计划不能起草，没草稿不能做一致性检查，没草稿不能提交，不在返工队列不能定点改 |

因此写作者的合法顺序是：`novel_context` → `read_chapter`（首章可缺）→ `plan_chapter` → `draft_chapter` → `check_consistency` → `commit_chapter`。重写和打磨用 `edit_chapter` 代替整章初稿，其余检查和提交仍要发生。
