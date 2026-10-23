# 裁定与三个创作代理

裁定是单次模型调用：事实进去，结构化决定出来。它不写正文，不执行动作。执行在引擎里，顺序固定。每次成功或失败都追加 `meta/decisions.jsonl`，记录场景、输入事实、决定或错误。这是审计，不是恢复数据源。恢复只看进度、检查点和 `run.json`。

四个场景各有自己的决定类型。一个场景里表达不了另一个场景的动作。收集事实的函数可以读盘；做决定的函数除了这一次模型请求外不读盘，以便用记录离线重放。

模型输出先过 JSON 结构。结构或业务校验失败时，把精确原因送回模型修正，直到成功或上下文结束。拒答、截断、不可重试的请求错误立刻返回。启动失败就明确报错。失败和僵局裁定失败则暂停。干预失败不产生写入。

用量计入默认模型的预算。裁定不单独配置角色模型。

## `plan_start`

新书启动时调用。输入是用户需求原文和可选文风名。

```text
planner   architect_long | architect_short
task      交给规划师的完整任务
reason    非空
```

需求过短（少于 20 个字）时，`task` 里补上差异化方向、目标读者、核心消费点，以及至少一个非常规钩子。三个字段都必填。规划师只能是这两个名字。

## `intervention`

用户插话。动作可以组合，引擎执行顺序固定：`answer` → `rules` → `hold` → `reopen` → `dispatch`。至多一个 `dispatch`。至少一个动作或一句 `answer`，`reason` 非空。

| 字段 | 约束 |
|---|---|
| `answer` | 回显给用户的话，可空 |
| `rules` | 要落盘的长效写作规则原文，可空 |
| `hold` | 一次性暂停，或 `cancel=true` 取消已有暂停。仅写作期。`after=chapter` 时目标章不得早于下一章 |
| `reopen` | 仅完本期。章节号从 1 到已完成章数。完本期禁止直接 `dispatch`，返工靠重开后由 `Route` 派写作者 |
| `dispatch` | 派给某个代理的一条任务。阶段不匹配的派单在校验阶段拒绝 |

## `worker_failure` 与 `deadlock`

共用一种决定。送到这里的都是确定性代码给不出出路的残余：可重试错误已经在模型层消化，代码错误已经直接暂停。

```text
action     retry | reroute | abort
dispatch   仅 reroute 时必填
reason     非空
```

事实包包括：场景名、代理、任务、错误文本、错误类别、僵局重复次数、阶段、下一章、返工队列、设定缺项。`retry` 和 `abort` 不带派单。`reroute` 的派单再按当前阶段校验。

僵局咨询里，`retry` 不清零重复计数。

## 三个代理

每次运行是一次独立循环：独立上下文、独立模型、独立重试。代理之间不共享对话。协作只通过文件。

装配时固定：

- 角色模型与备用提供方
- 提示词缓存键：一书一基、一角色一名、一次运行一个序号。进缓存键的值在本次运行里第一次算完就冻结
- 写作者专用的上下文管理器，随模型切换重建窗口
- 停止条件和事实护栏

进度事件分两类：模型响应的生命周期，以及工具执行、流式正文、思考、重试、上下文占用。只有真正开始执行工具才算工具时间。

### 规划师

`architect_short` 与 `architect_long` 使用不同系统提示词。短篇一次规划扁平大纲。长篇只做指南针、起步两卷骨架和第 1 弧的详细章节；后面的弧和卷在写到边界时再展开。

工具：`novel_context`、`save_book`、`save_foundation`、`audit_foundation`、`expand_next_arc`、`revise_outline`、`resolve_outline_feedback`。

收尾工具成功即结束本轮。结束前必须出现本任务对应的新检查点。

卷末任务是三选一，并在 `reason` 里写判定理由：

- `append_volume`：故事继续
- `append_volume` 且卷上 `"final": true`：收官卷
- `complete_book`：完结条件当下已经满足

`estimated_scale` 是证据，不是否决权。高估的规模不能单独阻止完本。

### 写作者

系统提示词分成协议和文风。协议文件保留执行顺序、断点续跑、重写与打磨、章节契约、字数要求，中间用 `{{VOICE}}` 占位。文风在占位处填回。用户可以覆盖文风，覆盖坏了也不能弄坏状态机，因为不变量在工具层。

工具：`novel_context`、`read_chapter`、`plan_chapter`、`draft_chapter`、`edit_chapter`、`check_consistency`、`commit_chapter`。

`commit_chapter` 成功即停。新章必须整章起草；已入队的旧章才允许定点编辑。

### 审阅者

从设定一致、角色行为、节奏、叙事连贯、伏笔、钩子、审美七个方面阅读原文。审美再分描写质感、叙事手法、对话区分度、用词、情感打动力。每一项引用原文，不打空泛分数。

工具：`novel_context`、`read_chapter`、`save_review`、`save_arc_summary`、`save_volume_summary`。

被派写摘要时，只调用 `save_review` 不算完成。被派审阅时，只写摘要不算完成。护栏按本轮任务要求的步骤名检查。

## 提示词资产

提示词放在 `assets/`，文件名固定：

```text
assets/prompts/   architect-short.md、architect-long.md、writer.md、editor.md
                  arbiter-plan-start.md、arbiter-intervention.md、arbiter-failure.md
assets/voice.md
assets/styles/    default、fantasy、romance、suspense
assets/references/ 写作参考、体裁模板、去 AI 腔
```

导入和仿写提示词留到后置阶段，不进第一轮装配。

缓存能命中的前提是请求前缀稳定：工具的说明和参数模式每次生成时键要排序；历史只追加，压缩是一次明确的整段失效；动态指令放在尾部，不改写早期消息。缓存是否断裂只观察、不自动修复，计数进用量记录。
