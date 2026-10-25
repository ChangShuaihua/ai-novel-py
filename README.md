# ainovel-py

全自动长篇小说创作引擎。确定性引擎按书目录里的事实调度规划、写作和审阅；模型只在开放创作和少量语义裁定处被调用。从一句话需求写到完整小说，进程结束后从最近落盘的一步继续。

阶段 1 到阶段 8 已落地，见 [实现顺序](.cursor/docs/08-roadmap.md)。规格见 [文档](.cursor/docs/01-architecture.md)。

## 安装

需要 Python 3.12 或更高版本。

```bash
pip install -e ".[llm]"
```

只跑测试、不接真实模型时：

```bash
pip install -e ".[dev]"
python -m pytest
```

终端界面另外安装 `textual`。无界面入口不依赖它。

## 配置

在用户目录放置 `~/.ainovel/config.json`（Windows 为 `%USERPROFILE%\.ainovel\config.json`）。写作控制室的「接入模型」从列表选择提供方和模型，并写入同一份文件。没有这个文件时，启动、恢复、干预和导入会失败。页面不回显完整密钥；密钥留空表示保持已保存的值。

```json
{
  "provider": "openai",
  "model": "gpt-4.1",
  "api_key": "",
  "api_base": "",
  "style": ""
}
```

`provider` 和 `model` 必填。传给 LiteLLM 的模型名是 `provider/model`；`model` 本身已带 `/` 时原样使用。`api_key`、`api_base` 留空则不传入，由 LiteLLM 按该提供方的常规方式取密钥。

`style` 选用内置风格预设：`default`、`fantasy`、`romance`、`suspense`。留空则不附加风格预设。文风正文的覆盖顺序是：本书 `<书目录>/style/`，然后 `~/.ainovel/style/`，再然后包内 `ainovel/assets/`。

规划、写作、审阅和裁定共用这份默认模型。调用超时会在同一提供方上重试。

## 写一本书

```bash
python -m ainovel.entry.headless start books/demo "一个在雨夜醒来的人"
```

`start` 用于新书。它把进度写成 `init`，并清空检查点，然后由启动裁定选定规划师，再进入规划与写作。同一目录已有进度时，用 `resume` 继续，不要再次 `start`。

一本书同时只能有一个可写进程。占用中会提示 `.ainovel.lock`。结束进程后执行：

```bash
python -m ainovel.entry.headless resume books/demo
```

已提交的章节不会重写。停机前没处理完的干预会在恢复时重放。

逐章验收：

```bash
python -m ainovel.entry.headless review books/demo on
python -m ainovel.entry.headless next books/demo
```

`review on` 之后，没有 `next` 就不会派新章。返工和提交中断后的恢复不消耗这张许可。`review off` 恢复自动推进。

导入已有文本。切分、分析和合成都写在 `meta/import/`，发布是唯一写入 `chapters/` 的步骤。不加 `--yes` 时停在切分确认，命令打印 `await_confirmation`。确认后带 `--yes` 再执行同一条命令，继续后续阶段。发布后默认停在边界，用 `resume` 才进入正常写作。

```bash
python -m ainovel.entry.headless import books/demo novel.txt
python -m ainovel.entry.headless import books/demo novel.txt --yes
```

## 命令

入口是 `python -m ainovel.entry.headless`。`diag`、`export`、`eval` 只读打开书目录，不需要模型配置。

| 命令 | 作用 |
|---|---|
| `start DIRECTORY REQUIREMENT` | 新书。重置进度与检查点，写入需求并开始跑 |
| `resume DIRECTORY` | 从最近落盘的事实继续；重放未完成的干预 |
| `continue DIRECTORY` | 与 `resume` 相同的续跑 |
| `steer DIRECTORY TEXT` | 注入修改意见。裁定先落盘，再按决定派发或暂停 |
| `abort DIRECTORY` | 把本次打开的引擎标为取消 |
| `review DIRECTORY on\|off` | 切换逐章验收与自动推进 |
| `next DIRECTORY` | 在逐章验收下放行下一个新章 |
| `import DIRECTORY SOURCE [--yes]` | 在导入工作区编译外部文本，确认后发布章节 |
| `export DIRECTORY DEST` | 按 `completed_chapters` 的顺序导出 TXT |
| `diag DIRECTORY` | 只读检查缺章和规则问题，并输出检查点骨架 |
| `eval DIRECTORY --right STYLE [--left STYLE]` | 用生产文风组装比较两套风格，打印 `same` 或 `different` |
| `tui DIRECTORY` | 订阅宿主事件。需要已安装 `textual`，并且存在模型配置 |
| `web [--host 127.0.0.1] [--port 8765]` | 本机写作控制室。界面在 `web/`，先构建再打开。浏览器要先登记或登录 |

正在运行的写作，结束那个进程后再 `resume`。`abort` 只作用于本次打开的引擎。

## 引擎在做什么

一个串行引擎，一条纯函数路由，四类裁定，三个创作代理。代理循环只负责工具调用、写完即停、检查点护栏和写作者上下文压缩。

1. 启动裁定选择短篇或长篇规划师，并把结果写入 `meta/run.json`。记录还在时，恢复不会重新问模型。
2. 规划师把书名、前提、大纲、角色和世界规则写在书目录根上。
3. 写作者按计划、草稿、一致性检查、提交的顺序完成一章。提交用 Saga：中断后从冻结的草稿恢复，不采用新的模型参数。
4. 审阅者在弧末给出结论、弧摘要，需要时写卷摘要。规划师再展开下一弧。
5. 路由只读已经装入内存的事实，决定下一步派谁。完本报告用已有字数和结构渲染，不再调用模型。完本后再次运行不会自己续写。

超过 50 章时，上下文改为卷摘要、本卷弧摘要和最近章节摘要。写作者对话超窗时会压缩，并重新放回当前章计划和角色快照。

## 书籍目录

章节文件 `chapters/01.md` 起，第 100 章是 `chapters/100.md`。

```text
书目录/
  premise.md
  outline.json
  characters.json
  world_rules.json
  chapters/01.md
  drafts/01.plan.json
  drafts/01.draft.md
  summaries/01.json
  reviews/01.json
  meta/progress.json
  meta/checkpoints.jsonl
  meta/run.json
  meta/pending_commit.json
```

分层书另有 `layered_outline.json` 和 `meta/compass.json`。完整清单见 [领域模型与书籍目录](.cursor/docs/02-domain-store.md)。

## 文档

1. [架构与铁律](.cursor/docs/01-architecture.md)
2. [领域模型与书籍目录](.cursor/docs/02-domain-store.md)
3. [工具契约](.cursor/docs/03-tools.md)
4. [路由与引擎循环](.cursor/docs/04-flow-engine.md)
5. [裁定与三个创作代理](.cursor/docs/05-arbiter-workers.md)
6. [上下文、文风与宿主](.cursor/docs/06-context-host.md)
7. [后置能力与测试](.cursor/docs/07-later-and-tests.md)
8. [实现顺序](.cursor/docs/08-roadmap.md)
9. [界面](.cursor/docs/09-ui.md)

## 写作控制室

界面只读宿主快照，按钮对应已有的启动、继续、干预、暂停、逐章验收、导入确认、导出和诊断。

页面和接口分开跑。接口只回答 `/api`，不托管页面。

```bash
python -m ainovel.entry.headless web
```

另开一个终端：

```bash
cd web
npm install
npm run dev
```

接口在 <http://127.0.0.1:8765>，页面在 <http://127.0.0.1:5173>。地址写在根目录 `.env` 和 `web/.env`，样例是 `.env.example`、`web/.env.example`。两边都用 `127.0.0.1`，刷新令牌的 cookie 才能带上。先登记或登录再进自己的书架。账号写在 `~/.ainovel/users.json`，密码只存散列。登录发出一对 JWT：访问令牌大约 15 分钟，放在内存里，请求带 `Authorization: Bearer`；刷新令牌大约 7 天，放在 HttpOnly cookie 里，也写在登录响应中。访问令牌过期后用刷新令牌换一对新的，旧的刷新令牌立即作废。改密码或离开会使已发出的令牌失效。每个人的书架和模型配置在 `~/.ainovel/accounts/` 下分开。命令行的 `start`、`resume` 仍由本机直接执行，不经过这道登录。

`npm run build` 把页面写到 `web/dist`，由前端自己的静态服务托管，不放进 Python 包。
