-- ainovel 建表。字段说明见 docs/mysql-字段设计.md
-- MySQL 8.0.16 及以上。InnoDB，utf8mb4。时间存 UTC。

CREATE DATABASE IF NOT EXISTS ainovel
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE ainovel;

CREATE TABLE users (
  id CHAR(16) NOT NULL COMMENT 'token_hex(8)',
  username VARCHAR(40) NOT NULL,
  salt VARBINARY(16) NOT NULL,
  password_hash VARBINARY(32) NOT NULL,
  scrypt_n INT UNSIGNED NOT NULL,
  generation INT UNSIGNED NOT NULL DEFAULT 1,
  refresh_jti VARCHAR(64) NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_username (username),
  CONSTRAINT chk_users_generation CHECK (generation >= 1)
) ENGINE=InnoDB COMMENT='账号。对应 users.json';

CREATE TABLE model_configs (
  user_id CHAR(16) NOT NULL,
  provider VARCHAR(64) NOT NULL,
  model VARCHAR(128) NOT NULL,
  api_key VARCHAR(512) NOT NULL DEFAULT '',
  api_base VARCHAR(512) NOT NULL DEFAULT '',
  style VARCHAR(64) NOT NULL DEFAULT '',
  roles JSON NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (user_id),
  CONSTRAINT fk_model_configs_user
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='账号模型配置。对应 accounts/<id>/config.json';

CREATE TABLE books (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id CHAR(16) NOT NULL,
  root_path VARCHAR(1024) NOT NULL COMMENT '书目录绝对路径',
  root_path_hash CHAR(64) NOT NULL COMMENT '规范化路径的 SHA-256 十六进制',
  shelf_state VARCHAR(16) NOT NULL DEFAULT 'shelf',
  title VARCHAR(200) NOT NULL DEFAULT '',
  synopsis TEXT NOT NULL,
  phase VARCHAR(16) NOT NULL DEFAULT 'init',
  flow VARCHAR(16) NULL,
  current_chapter INT UNSIGNED NOT NULL DEFAULT 0,
  total_chapters INT UNSIGNED NOT NULL DEFAULT 0,
  in_progress_chapter INT UNSIGNED NOT NULL DEFAULT 0,
  total_word_count INT UNSIGNED NOT NULL DEFAULT 0,
  current_volume INT UNSIGNED NOT NULL DEFAULT 0,
  current_arc INT UNSIGNED NOT NULL DEFAULT 0,
  layered TINYINT(1) NOT NULL DEFAULT 0,
  reopened_from_complete TINYINT(1) NOT NULL DEFAULT 0,
  reopen_count INT UNSIGNED NOT NULL DEFAULT 0,
  rewrite_reason VARCHAR(500) NOT NULL DEFAULT '',
  completed_chapters JSON NULL,
  completed_scenes JSON NULL,
  chapter_word_counts JSON NULL,
  pending_rewrites JSON NULL,
  strand_history JSON NULL,
  hook_history JSON NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  trashed_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_books_user_path (user_id, root_path_hash),
  KEY idx_books_shelf (user_id, shelf_state),
  CONSTRAINT fk_books_user
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  CONSTRAINT chk_books_shelf CHECK (shelf_state IN ('shelf', 'trash')),
  CONSTRAINT chk_books_phase CHECK (phase IN ('init', 'premise', 'outline', 'writing', 'complete')),
  CONSTRAINT chk_books_flow CHECK (flow IS NULL OR flow IN ('writing', 'reviewing', 'rewriting', 'polishing', 'steering')),
  CONSTRAINT chk_books_flags CHECK (layered IN (0, 1) AND reopened_from_complete IN (0, 1))
) ENGINE=InnoDB COMMENT='书架、废纸篓和进度。正文仍在 root_path';

CREATE TABLE book_runs (
  book_id BIGINT UNSIGNED NOT NULL,
  started_at DATETIME(6) NULL,
  provider VARCHAR(64) NOT NULL DEFAULT '',
  model VARCHAR(128) NOT NULL DEFAULT '',
  style VARCHAR(64) NOT NULL DEFAULT '',
  planning_tier VARCHAR(16) NULL,
  start_prompt TEXT NOT NULL,
  plan_start JSON NULL,
  pending_steer TEXT NOT NULL,
  advance_mode VARCHAR(16) NOT NULL DEFAULT 'auto',
  advance_permit_chapter INT UNSIGNED NOT NULL DEFAULT 0,
  hold_after VARCHAR(32) NULL,
  hold_target_chapter INT UNSIGNED NOT NULL DEFAULT 0,
  hold_reason VARCHAR(500) NOT NULL DEFAULT '',
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (book_id),
  CONSTRAINT fk_book_runs_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_book_runs_tier CHECK (planning_tier IS NULL OR planning_tier IN ('short', 'mid', 'long')),
  CONSTRAINT chk_book_runs_hold CHECK (
    hold_after IS NULL OR hold_after IN ('boundary', 'rewrites_drained', 'chapter')
  )
) ENGINE=InnoDB COMMENT='运行意图。对应 meta/run.json。advance_mode 不设枚举约束，未知值由程序拒绝写入';

CREATE TABLE book_documents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_id BIGINT UNSIGNED NOT NULL,
  kind VARCHAR(64) NOT NULL,
  body JSON NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_book_documents_kind (book_id, kind),
  CONSTRAINT fk_book_documents_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_book_documents_kind CHECK (kind IN (
    'outline',
    'layered_outline',
    'characters',
    'world_rules',
    'compass',
    'foundation_audit',
    'outline_feedback_resolution',
    'last_commit',
    'last_review',
    'user_rules',
    'pending_commit'
  ))
) ENGINE=InnoDB COMMENT='整份覆盖的 JSON 设定';

CREATE TABLE chapters (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_id BIGINT UNSIGNED NOT NULL,
  chapter_no INT UNSIGNED NOT NULL,
  relative_path VARCHAR(255) NOT NULL,
  word_count INT UNSIGNED NOT NULL DEFAULT 0,
  summary_path VARCHAR(255) NOT NULL DEFAULT '',
  committed_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_chapters_no (book_id, chapter_no),
  CONSTRAINT fk_chapters_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_chapters_no CHECK (chapter_no >= 1)
) ENGINE=InnoDB COMMENT='已提交章节索引。正文文件仍在书目录';

CREATE TABLE checkpoints (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_id BIGINT UNSIGNED NOT NULL,
  seq INT UNSIGNED NOT NULL,
  scope_kind VARCHAR(16) NOT NULL,
  scope_chapter INT UNSIGNED NOT NULL DEFAULT 0,
  scope_volume INT UNSIGNED NOT NULL DEFAULT 0,
  scope_arc INT UNSIGNED NOT NULL DEFAULT 0,
  step VARCHAR(64) NOT NULL,
  artifact VARCHAR(255) NOT NULL DEFAULT '',
  digest VARCHAR(80) NOT NULL DEFAULT '',
  occurred_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_checkpoints_seq (book_id, seq),
  KEY idx_checkpoints_scope (book_id, scope_kind, scope_chapter, scope_volume, scope_arc, step),
  CONSTRAINT fk_checkpoints_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_checkpoints_scope CHECK (scope_kind IN ('chapter', 'arc', 'volume', 'global')),
  CONSTRAINT chk_checkpoints_seq CHECK (seq >= 1)
) ENGINE=InnoDB COMMENT='检查点。只插入。对应 meta/checkpoints.jsonl';

CREATE TABLE decisions (
  id CHAR(32) NOT NULL,
  book_id BIGINT UNSIGNED NOT NULL,
  schema_version SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  occurred_at DATETIME(6) NOT NULL,
  kind VARCHAR(64) NOT NULL,
  decider VARCHAR(64) NOT NULL DEFAULT 'arbiter',
  input_text TEXT NOT NULL,
  input_truncated TINYINT(1) NOT NULL DEFAULT 0,
  facts JSON NULL,
  decision JSON NULL,
  reason TEXT NOT NULL,
  error TEXT NOT NULL,
  PRIMARY KEY (id),
  KEY idx_decisions_book_time (book_id, occurred_at),
  CONSTRAINT fk_decisions_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_decisions_truncated CHECK (input_truncated IN (0, 1))
) ENGINE=InnoDB COMMENT='裁定审计。只插入。对应 meta/decisions.jsonl';

CREATE TABLE book_signals (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  book_id BIGINT UNSIGNED NOT NULL,
  kind VARCHAR(32) NOT NULL,
  chapter_no INT UNSIGNED NOT NULL DEFAULT 0,
  seq INT UNSIGNED NOT NULL,
  body JSON NOT NULL,
  created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_book_signals (book_id, kind, chapter_no, seq),
  CONSTRAINT fk_book_signals_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
  CONSTRAINT chk_book_signals_kind CHECK (kind IN (
    'timeline',
    'foreshadow',
    'relation',
    'state_change',
    'outline_feedback'
  )),
  CONSTRAINT chk_book_signals_seq CHECK (seq >= 1)
) ENGINE=InnoDB COMMENT='时间线、伏笔、关系、状态变化、大纲反馈';

CREATE TABLE IF NOT EXISTS book_files (
  book_id BIGINT UNSIGNED NOT NULL,
  relative_path VARCHAR(512) NOT NULL,
  body LONGBLOB NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (book_id, relative_path),
  CONSTRAINT fk_book_files_book
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='书里的文件。网页新建的书整本存在这里';
