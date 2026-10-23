# 领域模型与书籍目录

领域类型放在 `ainovel.domain`，只有数据和迁移规则，没有文件读写。JSON 字段名就是书目录里的落盘格式。未知的推进模式必须拒绝打开可写宿主，禁止猜一个默认值降级。

## 阶段 Phase

阶段只前进，允许停在原地，不允许倒退。

```text
init -> premise -> outline -> writing -> complete
```

`init` 也可以直接到 `outline` 或 `writing`（导入或一次性补齐时）。空值视为未初始化，可以进入任意合法阶段。目标为空则非法。

| 值 | 含义 |
|---|---|
| `init` | 任务已创建，还没有稳定设定 |
| `premise` | 已保存故事前提 |
| `outline` | 已保存大纲，可以写作 |
| `writing` | 已进入章节创作 |
| `complete` | 全书流程结束 |

完本之后要改旧章，走裁定的 `reopen`，由工具把阶段从完本打开并进入返工。这是唯一允许离开 `complete` 的路径，必须显式实现，不能靠放宽“只前进”的通用规则。

## 流程 Flow

流程只描述写作期里正在做什么，允许在这些值之间切换：

```text
writing   -> reviewing / rewriting / polishing / steering / writing
reviewing -> writing / rewriting / polishing / steering / reviewing
rewriting -> writing / steering / rewriting
polishing -> writing / steering / polishing
steering  -> writing / reviewing / rewriting / polishing / steering
```

| 值 | 含义 |
|---|---|
| `writing` | 正常推进下一章 |
| `reviewing` | 审阅进行中。当前生产路径里审阅完成后流程会回到 `writing` / `rewriting` / `polishing`，这条分支保留，避免以后显式进入审阅时被续写抢走 |
| `rewriting` | 处理必须重写的章节 |
| `polishing` | 处理只需打磨的章节 |
| `steering` | 正在处理用户干预 |

空值可以进入任意合法流程。`rewriting -> reviewing` 这类跳转非法。

## 规划级别

`planning_tier`：`short` / `mid` / `long`。空表示首次规划还没落盘，规划师身份还不能查表，交给启动裁定。`short` 派 `architect_short`，其余派 `architect_long`。

## 进度 Progress

文件：`meta/progress.json`。控制逻辑只读这些事实，不靠修改时间判断进度。

| 字段 | 类型 | 含义 |
|---|---|---|
| `phase` | string | 当前阶段 |
| `current_chapter` | int | 当前章节游标 |
| `total_chapters` | int | 非分层：详细大纲章数。分层：含骨架估算的容量，只用于上下文策略，不是全书固定章数 |
| `completed_chapters` | int[] | 已提交章节 |
| `total_word_count` | int | 总字数 |
| `chapter_word_counts` | map | 每章字数，重写时用来修正总数 |
| `in_progress_chapter` | int | 正在写的章节 |
| `completed_scenes` | int[] | 当前章已完成场景，可空 |
| `flow` | string | 当前流程 |
| `pending_rewrites` | int[] | 待返工队列，队首优先 |
| `rewrite_reason` | string | 返工原因 |
| `strand_history` | string[] | 按章记录的主导情节线 |
| `hook_history` | string[] | 按章记录的章末钩子类型 |
| `current_volume` | int | 分层：当前卷 |
| `current_arc` | int | 分层：当前弧 |
| `layered` | bool | 是否分层滚动规划 |
| `reopened_from_complete` | bool | 从完结重开。返工排空后按结构完整重新完结，避免终卷被扰动后卡死续写 |
| `reopen_count` | int | 重开累计次数。保证再完结时进度字节变化，检查点不会因摘要相同被当成空转 |

`LatestCompleted` 是已完成章节的最大号，没有则为 0。`NextChapter` 是它加 1。

## 检查点 Checkpoint

文件：`meta/checkpoints.jsonl`，只追加。查询走进程内镜像，镜像只能由追加和重置维护。

```json
{
  "seq": 1,
  "scope": {"kind": "chapter", "chapter": 3},
  "step": "draft",
  "artifact": "drafts/03.draft.md",
  "digest": "sha256:...",
  "occurred_at": "2026-10-17T00:00:00Z"
}
```

`scope.kind`：`chapter` / `arc` / `volume` / `global`。弧带 `volume` 和 `arc`，卷只带 `volume`。同一 `scope + step + digest` 再写视为幂等，不产生新行。`seq` 单调增加。

步骤名与工具对应：`book`、`plan`、`draft`、`edit`、`consistency_check`、`commit`、`review`、`arc_summary`、`volume_summary`，以及设定类 `premise` / `outline` / `layered_outline` / `characters` / `world_rules` / `append_volume` / `update_compass` / `complete_book`。

## 运行意图 RunMeta

文件：`meta/run.json`。这是用户运行意图，不是创作事实。`Init` 跨重启保留全部意图字段。

| 字段 | 含义 |
|---|---|
| `started_at` | 开始时间 |
| `provider` / `model` / `style` | 本次运行的模型与文风预设 |
| `planning_tier` | 已落盘的规划级别 |
| `start_prompt` | 用户原始需求。先于启动裁定落盘，裁定失败后靠它补裁 |
| `plan_start` | 启动裁定结果。规划期崩溃恢复的唯一依据，不重新裁定 |
| `pending_steer` | 尚未处理完的用户干预。单在途槽位 |
| `advance_mode` | `auto` 或 `review`。空则初始化为 `auto`。未知值拒绝打开 |
| `advance_permit_chapter` | `review` 模式下一次性放行的正向章节号。切回 `auto` 时清零 |
| `advance_hold` | 一次性暂停：`after` 为 `boundary` / `rewrites_drained` / `chapter`；`chapter` 时 `target_chapter` 必须大于 0，其余条件禁止带目标章 |

## 作品信息

`meta/book.json` 是书名和简介的唯一事实源：`title`、`synopsis`。`book.md` 只是可读投影。前提里不重复存书名，进度里不存作品信息。

## 书籍目录

章节号 1 到 9 补零，10 以上按自然宽度，因此第 100 章是 `chapters/100.md`。

```text
书目录/
  book.md
  premise.md
  outline.json
  layered_outline.json
  characters.json
  characters.md
  world_rules.json
  timeline.jsonl
  timeline.md
  chapters/01.md
  drafts/01.plan.json
  drafts/01.draft.md
  summaries/01.json
  summaries/arc-v01a01.json
  summaries/vol-v01.json
  reviews/01.json
  reviews/01-global.json
  style/                      本书文风覆盖
  meta/
    book.json
    progress.json
    checkpoints.jsonl
    run.json
    decisions.jsonl
    pending_commit.json
    last_commit.json
    last_review.json
    user_rules.json
    compass.json
    outline_feedback.jsonl
    outline_feedback_resolution.json
    state_changes.jsonl
```

分层书才有 `layered_outline.json` 和 `meta/compass.json`。时间线、角色状态变化是追加日志；旧版 JSON 数组在下一次追加时先原子写成新日志，再删旧文件。`timeline.md`、`characters.md`、`book.md` 都是可重建投影。

大纲反馈池：写作者对大纲的普通偏离，留到下一次结构操作消费。外部修订如果影响后续剧情，继续写作前优先交给规划师；处理成功后清空。机械违规不另存会过期的工件，由 `novel_context(chapter=N)` 按当前正文和用户规则即时计算。

## 原子写

单个文件：写入同目录临时文件，刷盘，再替换目标文件。Windows 上替换要覆盖已存在的目标。写失败留下临时文件，不损坏旧内容。

跨文件不假装成数据库事务。结构操作（展开下一弧、追加卷）只承诺同一参数的幂等重放：失败就返回错误，调用方用同一意图再跑。派生的可读投影可以在重放时修好。

## 章节提交 Saga

`commit_chapter` 是唯一的跨文件可恢复流程。意图先落盘，恢复时只用这份冻结载荷和正文快照，禁止用重启后模型重新生成的参数或被覆盖的草稿。

文件：`meta/pending_commit.json`。

阶段按这个顺序推进，只允许向前：

```text
started -> state_applied -> progress_marked -> signal_saved -> 清除 pending
```

| 阶段 | 已经完成的事 |
|---|---|
| `started` | 规范化参数和草稿正文已冻结 |
| `state_applied` | 终稿与世界状态（时间线、伏笔、关系、角色状态）已写入 |
| `progress_marked` | `progress.json` 已更新 |
| `signal_saved` | 检查点与 `last_commit` 信号已写入，可以清除意图 |

启动或再次调用时如果发现未完成的 `pending_commit`：

- 章节号不一致：拒绝，要求先恢复那一章。
- 阶段非法：拒绝。
- 阶段合法：从该阶段之后继续，不重做已完成的写。

同一时刻只有一个在途提交。

## 幂等

写工具执行前看当前范围最新检查点。`step` 和 `digest` 都相同则直接返回已有产物，不重复写。引擎崩溃后的重复派发因此是安全的。恢复等于重新进入循环，由 `Route` 从文件重算下一步。

## 上下文策略（纯函数）

按 `total_chapters` 选择窗口，供 `novel_context` 使用，不单独落盘。

| 总章数 | 摘要窗口 | 时间线窗口 | 分层摘要 |
|---|---|---|---|
| ≤ 15 | 10 | 10 | 否 |
| ≤ 50 | 5 | 8 | 否 |
| > 50 | 3 | 5 | 是 |

已完成章不少于 6 章的分层书，或已完成不少于 12 章的书，倾向交接摘要而不是塞全文。相关章节反查在总章数大于 30 时打开。
