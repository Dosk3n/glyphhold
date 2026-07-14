from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import settings
from app.storage.db import connect


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="initial_schema",
        sql="""
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS dashboard_users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    actor TEXT NOT NULL,
    description TEXT,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_categories (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    allow_auto_prefetch INTEGER NOT NULL DEFAULT 1,
    agent_can_create INTEGER NOT NULL DEFAULT 1,
    agent_can_write INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    confidence INTEGER NOT NULL DEFAULT 3,
    auto_prefetch_level TEXT NOT NULL DEFAULT 'normal',
    archived INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(category_id) REFERENCES memory_categories(id),
    FOREIGN KEY(superseded_by) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS secrets (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    encrypted_value BLOB NOT NULL,
    encryption_version INTEGER NOT NULL DEFAULT 1,
    encryption_key_id TEXT,
    value_type TEXT NOT NULL DEFAULT 'text',
    service TEXT,
    host TEXT,
    scope TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    allowed_agents_json TEXT NOT NULL DEFAULT '[]',
    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_revealed_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_revisions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    confidence INTEGER NOT NULL,
    auto_prefetch_level TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    changed_by TEXT,
    change_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS event_log (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT,
    tool TEXT,
    target_type TEXT,
    target_id TEXT,
    action TEXT,
    success INTEGER NOT NULL,
    message TEXT,
    query TEXT,
    result_count INTEGER,
    estimated_tokens INTEGER,
    duration_ms INTEGER,
    purpose TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    title,
    summary,
    body,
    tags,
    content='memories',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, title, summary, body, tags)
    VALUES (new.rowid, new.title, coalesce(new.summary, ''), new.body, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, summary, body, tags)
    VALUES ('delete', old.rowid, old.title, coalesce(old.summary, ''), old.body, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, summary, body, tags)
    VALUES ('delete', old.rowid, old.title, coalesce(old.summary, ''), old.body, old.tags_json);
    INSERT INTO memories_fts(rowid, title, summary, body, tags)
    VALUES (new.rowid, new.title, coalesce(new.summary, ''), new.body, new.tags_json);
END;

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category_id);
CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories(confidence);
CREATE INDEX IF NOT EXISTS idx_memories_prefetch ON memories(auto_prefetch_level);
CREATE INDEX IF NOT EXISTS idx_memories_archived ON memories(archived);
CREATE INDEX IF NOT EXISTS idx_secrets_name ON secrets(name);
CREATE INDEX IF NOT EXISTS idx_secrets_service_host ON secrets(service, host);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_events_actor ON event_log(actor);
CREATE INDEX IF NOT EXISTS idx_events_type ON event_log(event_type);
""",
    ),
    Migration(
        version=2,
        name="app_settings",
        sql="""
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
""",
    ),
    Migration(
        version=3,
        name="seed_default_categories",
        sql="""
INSERT OR IGNORE INTO memory_categories (
    id, name, description, allow_auto_prefetch, agent_can_create, agent_can_write,
    created_at, updated_at
)
VALUES
    ('cat_people', 'people', 'People and identity context.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_servers', 'servers', 'Servers, machines, hosts, and infrastructure.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_services', 'services', 'Services, apps, ports, and operational details.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_projects', 'projects', 'Project notes, goals, and implementation context.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_procedures', 'procedures', 'Repeatable procedures and runbooks.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_preferences', 'preferences', 'User preferences and working style.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_decisions', 'decisions', 'Decisions and rationale.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_facts', 'facts', 'General confirmed facts.', 1, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('cat_temporary', 'temporary', 'Temporary or short-lived context.', 0, 1, 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
""",
    ),
    Migration(
        version=4,
        name="memory_revision_restore_fields",
        sql="""
ALTER TABLE memory_revisions ADD COLUMN category_id TEXT;
ALTER TABLE memory_revisions ADD COLUMN source TEXT;
""",
    ),
    Migration(
        version=5,
        name="dashboard_session_version",
        sql="""
ALTER TABLE dashboard_users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1;
""",
    ),
)


def apply_migrations() -> None:
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        applied = {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        conn.commit()


def current_schema_version() -> int:
    with connect(settings.db_path) as conn:
        try:
            row = conn.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["version"] or 0)
