# MySQL 字段设计

建表语句在 `docs/mysql-schema.sql`。

MySQL 8，存储引擎 InnoDB，字符集 `utf8mb4`，排序规则 `utf8mb4_0900_ai_ci`。时间用 `DATETIME(6)`，存 UTC。

网页新建的书不选目录。`books.root_path` 写成 `db:<书籍 id>`，章节、草稿、设定和审阅的文件字节写在 `book_files`。收藏星标留在浏览器，不建表。登录失败次数留在进程内存，不建表。

命令行和网页可以共用这些表。区别只在写入时的 `user_id`：网页用登录账号，命令行用它自己的账号行。

## 约定

- 主键能自增的用 `BIGINT UNSIGNED`。用户 `id` 沿用现在的 16 位十六进制，不改成自增。
- 布尔用 `TINYINT(1)`，`0` 为否，`1` 为是。
- 可变结构用 `JSON`。空对象和空数组写 `NULL`，不写 `{}` 或 `[]`。
- 外键都 `ON DELETE CASCADE`，删用户会带走他的配置和书行。书目录里的文件不随外键删除。
- 密钥列只给服务端读。接口继续只回密钥是否已设置，以及末四位提示。

## 枚举

| 名字 | 允许值 | 现在的来源 |
| --- | --- | --- |
| 阶段 `phase` | `init` `premise` `outline` `writing` `complete` | `meta/progress.json` |
| 流程 `flow` | `writing` `reviewing` `rewriting` `polishing` `steering` | 同上，空则 `NULL` |
| 书架 `shelf_state` | `shelf` `trash` | `library.json` 的两个数组 |
| 规划级别 `planning_tier` | `short` `mid` `long` | `meta/run.json`，未落盘为 `NULL` |
| 推进方式 `advance_mode` | `auto` `review` | 同上。未知值拒绝进入可写 |
| 暂停条件 `hold_after` | `boundary` `rewrites_drained` `chapter` | `advance_hold.after` |
| 检查点范围 `scope_kind` | `chapter` `arc` `volume` `global` | `checkpoints.jsonl` 的 `scope.kind` |
| 信号种类 `signal_kind` | `timeline` `foreshadow` `relation` `state_change` `outline_feedback` | 对应的 jsonl |

## users

对应 `~/.ainovel/users.json` 里的一条用户。密码只存 scrypt 摘要。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `CHAR(16)` | 否 | 主键 | 现有 `token_hex(8)` |
| `username` | `VARCHAR(40)` | 否 | 唯一 | 登录名，1–40 字 |
| `salt` | `VARBINARY(16)` | 否 | | scrypt 盐 |
| `password_hash` | `VARBINARY(32)` | 否 | | scrypt 摘要。列名不用 `hash`，避开保留词 |
| `scrypt_n` | `INT UNSIGNED` | 否 | | 现在文件里的 `n`，生产为 `16384` |
| `generation` | `INT UNSIGNED` | 否 | | 初始 `1`。退出或改密码加一，旧令牌失效 |
| `refresh_jti` | `VARCHAR(64)` | 是 | | 当前刷新令牌的 `jti`。空表示没有有效刷新链 |
| `created_at` | `DATETIME(6)` | 否 | | 登记时间 |
| `updated_at` | `DATETIME(6)` | 否 | | 改密码或轮换刷新令牌时更新 |

## model_configs

对应每个账号的 `config.json`。一个用户一行。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `user_id` | `CHAR(16)` | 否 | 主键，外键 → `users.id` | |
| `provider` | `VARCHAR(64)` | 否 | | 如 `deepseek` |
| `model` | `VARCHAR(128)` | 否 | | 如 `deepseek-v4-pro` |
| `api_key` | `VARCHAR(512)` | 否 | | 默认空字符串。空密钥表示尚未接入 |
| `api_base` | `VARCHAR(512)` | 否 | | 默认空字符串。空则用该提供方默认地址 |
| `style` | `VARCHAR(64)` | 否 | | 文风预设名。空表示不附加 |
| `roles` | `JSON` | 是 | | 分角色覆盖。形状与现在文件里的 `roles` 相同 |
| `updated_at` | `DATETIME(6)` | 否 | | |

`roles` 里每个角色对象的字段：`provider`、`model`、`api_key`、`api_base`、`fallbacks`。`fallbacks` 是对象数组。

## books

一本书一行。书架成员、废纸篓、书名和进度都在这里。正文目录仍是 `root_path`。

对应 `library.json` 的路径，加上 `meta/book.json`、`meta/progress.json`。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED` | 否 | 主键 | 自增 |
| `user_id` | `CHAR(16)` | 否 | 外键 → `users.id`，索引 `(user_id, shelf_state)` | 这本书属于谁 |
| `root_path` | `VARCHAR(1024)` | 否 | | 书目录绝对路径。不进唯一索引，避免 utf8mb4 索引超长 |
| `root_path_hash` | `CHAR(64)` | 否 | 唯一 `(user_id, root_path_hash)` | `root_path` 规范化后的 SHA-256 十六进制 |
| `shelf_state` | `VARCHAR(16)` | 否 | | `shelf` 或 `trash`。默认 `shelf` |
| `title` | `VARCHAR(200)` | 否 | | 默认空字符串。来源 `meta/book.json` |
| `synopsis` | `TEXT` | 否 | | 默认空字符串 |
| `phase` | `VARCHAR(16)` | 否 | | 默认 `init` |
| `flow` | `VARCHAR(16)` | 是 | | 写作期流程。未进入写作为 `NULL` |
| `current_chapter` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `total_chapters` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `in_progress_chapter` | `INT UNSIGNED` | 否 | | 默认 `0`。`0` 表示没有正在写的章 |
| `total_word_count` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `current_volume` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `current_arc` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `layered` | `TINYINT(1)` | 否 | | 默认 `0` |
| `reopened_from_complete` | `TINYINT(1)` | 否 | | 默认 `0` |
| `reopen_count` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `rewrite_reason` | `VARCHAR(500)` | 否 | | 默认空字符串 |
| `completed_chapters` | `JSON` | 是 | | 整数数组，如 `[1,2,3]` |
| `completed_scenes` | `JSON` | 是 | | 当前章已完成场景号 |
| `chapter_word_counts` | `JSON` | 是 | | 对象，键是章号字符串，值是字数 |
| `pending_rewrites` | `JSON` | 是 | | 待返工章号，队首优先 |
| `strand_history` | `JSON` | 是 | | 按章的主导情节线 |
| `hook_history` | `JSON` | 是 | | 按章的章末钩子类型 |
| `created_at` | `DATETIME(6)` | 否 | | 首次登记到书架 |
| `updated_at` | `DATETIME(6)` | 否 | | 进度或书名变化时更新 |
| `trashed_at` | `DATETIME(6)` | 是 | | 放进废纸篓的时间。拣回书架后清空 |

放进废纸篓把 `shelf_state` 改成 `trash`，并写下 `trashed_at`。这本书不再出现在书架上。满三天，或手动清空废纸篓，会删除这些行；文件行随外键一起删掉。拣回书架会清掉 `trashed_at`。

## book_runs

对应 `meta/run.json`。一本书一行，记这次运行的意图，不是创作事实。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `book_id` | `BIGINT UNSIGNED` | 否 | 主键，外键 → `books.id` | |
| `started_at` | `DATETIME(6)` | 是 | | 对应 `started_at` |
| `provider` | `VARCHAR(64)` | 否 | | 默认空字符串 |
| `model` | `VARCHAR(128)` | 否 | | 默认空字符串 |
| `style` | `VARCHAR(64)` | 否 | | 默认空字符串 |
| `planning_tier` | `VARCHAR(16)` | 是 | | `short` / `mid` / `long` |
| `start_prompt` | `TEXT` | 否 | | 用户原始需求。默认空字符串 |
| `plan_start` | `JSON` | 是 | | `raw_prompt`、`planner`、`planner_task`、`decision_id` |
| `pending_steer` | `TEXT` | 否 | | 尚未处理完的干预。默认空字符串 |
| `advance_mode` | `VARCHAR(16)` | 否 | | `auto` 或 `review`。默认 `auto` |
| `advance_permit_chapter` | `INT UNSIGNED` | 否 | | 默认 `0`。`auto` 时必须为 `0` |
| `hold_after` | `VARCHAR(32)` | 是 | | 没有暂停时为 `NULL` |
| `hold_target_chapter` | `INT UNSIGNED` | 否 | | 默认 `0`。只有 `hold_after = chapter` 时大于 `0` |
| `hold_reason` | `VARCHAR(500)` | 否 | | 默认空字符串 |
| `updated_at` | `DATETIME(6)` | 否 | | |

## book_documents

整份覆盖写的 JSON 设定。一种文档一行。对应这些文件：

| `kind` | 现有文件 |
| --- | --- |
| `outline` | `outline.json` |
| `layered_outline` | `layered_outline.json` |
| `characters` | `characters.json` |
| `world_rules` | `world_rules.json` |
| `compass` | `meta/compass.json` |
| `foundation_audit` | `meta/foundation_audit.json` |
| `outline_feedback_resolution` | `meta/outline_feedback_resolution.json` |
| `last_commit` | `meta/last_commit.json` |
| `last_review` | `meta/last_review.json` |
| `user_rules` | `meta/user_rules.json` |
| `pending_commit` | `meta/pending_commit.json` |

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED` | 否 | 主键 | |
| `book_id` | `BIGINT UNSIGNED` | 否 | 外键 → `books.id` | |
| `kind` | `VARCHAR(64)` | 否 | 唯一 `(book_id, kind)` | 上表中的一种 |
| `body` | `JSON` | 否 | | 文件原文解析后的值。数组或对象都允许 |
| `updated_at` | `DATETIME(6)` | 否 | | |

`pending_commit` 提交完成后删除该行，与现在删掉 `meta/pending_commit.json` 相同。

## chapters

已提交章节的索引。正文仍是 `chapters/01.md` 这种文件。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED` | 否 | 主键 | |
| `book_id` | `BIGINT UNSIGNED` | 否 | 外键 → `books.id` | |
| `chapter_no` | `INT UNSIGNED` | 否 | 唯一 `(book_id, chapter_no)` | 从 `1` 起 |
| `relative_path` | `VARCHAR(255)` | 否 | | 如 `chapters/01.md`。1–9 补零，100 以上不补 |
| `word_count` | `INT UNSIGNED` | 否 | | 默认 `0` |
| `summary_path` | `VARCHAR(255)` | 否 | | 如 `summaries/01.json`。没有则空字符串 |
| `committed_at` | `DATETIME(6)` | 是 | | 最近一次提交 |

草稿不进这张表。草稿路径按章号可推：`drafts/01.draft.md`、`drafts/01.plan.json`。计划 JSON 若要入库，用 `book_documents`，`kind` 取 `chapter_plan`，并在 `body` 里带 `chapter_no`。首版不建这一行，计划文件继续留在书目录。

## checkpoints

对应 `meta/checkpoints.jsonl`。只插入，不更新旧行。同一本书里 `seq` 单调增加。相同 `scope_kind`、范围号、`step`、`digest` 再写时不插入。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED` | 否 | 主键 | |
| `book_id` | `BIGINT UNSIGNED` | 否 | 外键 → `books.id` | |
| `seq` | `INT UNSIGNED` | 否 | 唯一 `(book_id, seq)` | 从 `1` 起 |
| `scope_kind` | `VARCHAR(16)` | 否 | 索引 `(book_id, scope_kind, scope_chapter, scope_volume, scope_arc, step)` | |
| `scope_chapter` | `INT UNSIGNED` | 否 | | `chapter` 范围使用。其余为 `0` |
| `scope_volume` | `INT UNSIGNED` | 否 | | `arc` 或 `volume` 范围使用 |
| `scope_arc` | `INT UNSIGNED` | 否 | | 仅 `arc` 范围使用 |
| `step` | `VARCHAR(64)` | 否 | | 如 `draft`、`commit`、`outline` |
| `artifact` | `VARCHAR(255)` | 否 | | 相对路径。没有则空字符串 |
| `digest` | `VARCHAR(80)` | 否 | | 如 `sha256:` 加十六进制。没有则空字符串 |
| `occurred_at` | `DATETIME(6)` | 否 | | |

重置检查点时删除这本书的全部行。文件损坏在库里表现为缺行或序号中断，打开可写书时仍要拒绝继续写。

## decisions

对应 `meta/decisions.jsonl`。审计日志，不作为恢复进度的依据。只插入。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `CHAR(32)` | 否 | 主键 | 现有 uuid 十六进制。不自增 |
| `book_id` | `BIGINT UNSIGNED` | 否 | 外键 → `books.id`，索引 `(book_id, occurred_at)` | |
| `schema_version` | `SMALLINT UNSIGNED` | 否 | | 现在固定为 `1` |
| `occurred_at` | `DATETIME(6)` | 否 | | 对应 `at` |
| `kind` | `VARCHAR(64)` | 否 | | |
| `decider` | `VARCHAR(64)` | 否 | | 默认 `arbiter` |
| `input_text` | `TEXT` | 否 | | 最长约 8KB。默认空字符串 |
| `input_truncated` | `TINYINT(1)` | 否 | | 默认 `0` |
| `facts` | `JSON` | 是 | | |
| `decision` | `JSON` | 是 | | |
| `reason` | `TEXT` | 否 | | 默认空字符串 |
| `error` | `TEXT` | 否 | | 默认空字符串 |

## book_signals

对应追加日志：`timeline.jsonl`、`meta/foreshadow.jsonl`、`meta/relations.jsonl`、`meta/state_changes.jsonl`、`meta/outline_feedback.jsonl`。

重写某一章时，删掉该书该章该 `kind` 的旧行，再插入新行。`outline_feedback` 被消费后按决议删除对应行。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT UNSIGNED` | 否 | 主键 | |
| `book_id` | `BIGINT UNSIGNED` | 否 | 外键 → `books.id` | |
| `kind` | `VARCHAR(32)` | 否 | 唯一 `(book_id, kind, chapter_no, seq)` | 见枚举 |
| `chapter_no` | `INT UNSIGNED` | 否 | | 不属于某一章时为 `0` |
| `seq` | `INT UNSIGNED` | 否 | | 同一书、同一种类、同一章内从 `1` 起 |
| `body` | `JSON` | 否 | | 原来 jsonl 的那一行对象 |
| `created_at` | `DATETIME(6)` | 否 | | |

## book_files

网页新建的书，原来会落在书目录里的文件改存在这里。一行一个相对路径，正文和草稿都算。

| 字段 | 类型 | 空 | 键 | 说明 |
| --- | --- | --- | --- | --- |
| `book_id` | `BIGINT UNSIGNED` | 否 | 主键，外键 → `books.id` | |
| `relative_path` | `VARCHAR(512)` | 否 | 主键 | 如 `chapters/01.md`、`meta/progress.json` |
| `body` | `LONGBLOB` | 否 | | 文件字节 |
| `updated_at` | `DATETIME(6)` | 否 | | |

`.ainovel.lock` 不入库。废纸篓里的书满三天，或手动清空时，会删掉 `books` 行，文件行随外键一起删掉。

## 命令行仍可使用书目录

命令行打开的仍是本机目录，不经过 `book_files`。`chapters.relative_path` 和检查点的 `artifact` 继续记相对路径，网页上的那份字节在 `book_files.body`。
