# ainovel-py

AI 长篇小说创作与管理工具。项目提供浏览器写作工作台和命令行入口：从创意与前提开始，生成并维护大纲、人物和世界设定，按章节规划、写作、检查和提交；也可以导入已有文本、逐章审阅、恢复中断的创作流程，并导出 TXT。

写作流程以本地书籍文件和检查点为依据，便于恢复和追踪；模型负责创作与有限的语义判断，应用代码负责流程调度、数据校验和持久化。Web 版支持账号、个人书架和模型配置。每个账号的数据存放在应用数据目录中，用户密码以哈希形式保存。

## 快速开始：Docker

需要安装 Docker Desktop（或 Docker Engine）及 Docker Compose v2。克隆仓库后，在项目根目录运行：

```bash
docker compose up -d --build
```

打开 <http://127.0.0.1:8080>，注册账号后即可使用。默认 Compose 配置会一并启动 Web 前端、Python API、MySQL 和 Redis。首次构建需要下载镜像和依赖。

常用命令：

```bash
docker compose ps
docker compose logs -f api
docker compose down
```

`docker compose down` 会停止并移除容器，但不会删除数据库卷。不要运行 `docker compose down -v`，除非你确实要删除本地数据库数据。账号、书架、模型配置和作品数据保存在 Docker 数据卷中。

## 本地源码开发

源码开发模式需要 Python 3.12+、Node.js 22+、npm，以及可连接的 MySQL 8。Redis 可选；没有 Redis 时应用会直接读取数据库。先准备数据库并导入初始表结构：

```bash
mysql -u root -p -e "CREATE DATABASE ainovel CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p ainovel < docs/mysql-schema.sql
```

创建 Python 环境并安装项目依赖：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[llm]"
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install -e ".[llm]"
```

复制 `.env.example` 为 `.env`，设置数据库密码及本地服务地址。默认 API 监听 `127.0.0.1:8765`，Vite 前端监听 `127.0.0.1:5173`；如果修改端口或前端来源，也要相应更新 `AINOVEL_CORS_ORIGINS` 和 `web/.env` 中的 `VITE_API_BASE`。不要把包含真实密码或密钥的 `.env` 提交到 Git。

启动 API 和前端（使用两个终端）：

```bash
python -m ainovel.entry.headless web
```

```bash
cd web
npm ci
npm run dev
```

访问 <http://127.0.0.1:5173>。开发模式下，API 和前端分别运行；若只想运行完整容器化环境，请使用前面的 Docker 快速开始。

## 模型配置与写作

进入 Web 工作台后，在“接入模型”页面填写 LiteLLM 支持的提供方、模型名称和 API 凭据。模型配置按账号隔离。模型服务的可用性和费用取决于你所配置的提供方。

项目也提供命令行创作入口。先安装 `.[llm]` 并按项目配置要求准备模型配置，然后可以新建作品并在中断后续写：

```bash
python -m ainovel.entry.headless start books/demo "一个在雨夜醒来的人"
python -m ainovel.entry.headless resume books/demo
```

`start` 用于新作品；已有进度时用 `resume`，不要再次 `start`。CLI 使用本机用户目录下的配置和作品目录，与 Web 账号书架相互独立。更多命令可运行：

```bash
python -m ainovel.entry.headless --help
```

## 更新服务器

当前服务器部署使用 `/opt/ainovel`、GitHub `main` 分支和两份 Compose 配置。先在本地提交并推送要发布的变更：

```bash
git add <要提交的文件>
git commit -m "描述本次变更"
git push origin main
```

然后 SSH 登录服务器，在项目目录拉取并重建：

```bash
ssh root@47.97.166.61
cd /opt/ainovel
git -c http.version=HTTP/1.1 pull origin main
docker compose -p ainovel -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

只改前端时，可以在最后一条命令末尾指定 `web`；只改 Python 后端时指定 `api`。如果公共 Python 依赖或构建配置有变化，建议重建全部服务。

确认服务状态和日志：

```bash
docker compose -p ainovel -f docker-compose.yml -f docker-compose.server.yml ps
docker compose -p ainovel -f docker-compose.yml -f docker-compose.server.yml logs --tail=100 api web
```

服务器页面地址为 <http://47.97.166.61:443>。部署使用持久化 Docker 卷保存 MySQL 和用户数据；普通 `up -d --build` 会重建镜像和容器，不会清空这些卷。切勿在日常更新时添加 `-v`。`.env` 等本机敏感配置不会随 Git 更新；部署前也不要提交密钥、密码或临时文件。

## 测试

安装开发依赖后运行 Python 测试：

```bash
python -m pip install -e ".[dev,llm]"
python -m pytest
```

运行前端测试和生产构建：

```bash
cd web
npm test
npm run build
```

## 项目结构

```text
src/ainovel/       Python 引擎、领域模型、存储、API 与 CLI
web/               React + Vite 写作工作台
docs/              数据库初始化脚本及项目文档
tests/             Python 测试
docker-compose.yml 本地容器编排
docker-compose.server.yml 服务器部署覆盖配置
```

架构与实现说明位于 `.cursor/docs/`：

- [架构与边界](.cursor/docs/01-architecture.md)
- [领域模型与书籍目录](.cursor/docs/02-domain-store.md)
- [工具契约](.cursor/docs/03-tools.md)
- [路由与引擎循环](.cursor/docs/04-flow-engine.md)
- [裁定与创作代理](.cursor/docs/05-arbiter-workers.md)
- [上下文、文风与宿主](.cursor/docs/06-context-host.md)
- [后置能力与测试](.cursor/docs/07-later-and-tests.md)
- [实现路线图](.cursor/docs/08-roadmap.md)
- [界面说明](.cursor/docs/09-ui.md)
