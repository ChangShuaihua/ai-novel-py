# ainovel-py

全自动长篇小说创作引擎的 Python 实现规格。确定性引擎按文件里的事实调度规划、写作、审阅；模型只在开放创作和少量语义裁定处被调用。从一句话需求写到完整小说，崩溃后从最近一步继续。

业务代码按 [docs/08-roadmap.md](docs/08-roadmap.md) 分阶段落地，不要跳步。

## 和 Go 版的关系

规格来源是同级目录的 [ainovel-cli](../ainovel-cli)。Python 版遵守同一套控制面：事实层确定，语义层自主。

- 一本书的目录、文件名和 JSON 字段与 Go 版对齐。同一本书两边都能读，Python 版不改已有书的格式。
- 调度、阶段、幂等、提交恢复这些不变量照 Go 版执行。
- 通用 Agent 运行时不移植 Go 的 `agentcore`。Python 侧自带一个薄循环：工具调用、写完即停、事实护栏、上下文压缩。小说业务模型不进这层。
- 模型经 LiteLLM 接入。规划、写作、审阅可以各用各的模型；语义裁定用默认模型。

## 技术约定

- Python 3.12
- 领域模型和裁定结果用 `pydantic`
- 命令行用 `typer`
- 第一版入口是无界面持续运行；终端界面用 Textual，放在后置阶段

## 文档

按这个顺序读：

1. [架构与铁律](docs/01-architecture.md)
2. [领域模型与书籍目录](docs/02-domain-store.md)
3. [工具契约](docs/03-tools.md)
4. [路由与引擎循环](docs/04-flow-engine.md)
5. [裁定与三个创作代理](docs/05-arbiter-workers.md)
6. [上下文、文风与宿主](docs/06-context-host.md)
7. [后置能力与测试](docs/07-later-and-tests.md)
8. [实现顺序](docs/08-roadmap.md)

## 当前状态

阶段 1 已实现。`ainovel.domain` 与 `ainovel.store` 负责书籍目录。路由、工具和模型循环还没有。
