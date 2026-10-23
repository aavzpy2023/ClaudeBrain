import os
import re
import sqlite3
import unicodedata
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "claude-brain" / "brain.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,
    size   INTEGER NOT NULL,
    mtime  REAL NOT NULL,
    offset INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    project     TEXT,
    project_cwd TEXT,
    entrypoint  TEXT,
    git_branch  TEXT,
    title       TEXT,
    title_is_custom INTEGER NOT NULL DEFAULT 0,
    first_ts    TEXT,
    last_ts     TEXT,
    msg_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessions_project ON sessions(project, last_ts);

CREATE TABLE IF NOT EXISTS messages (
    uuid         TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    ts           TEXT,
    role         TEXT NOT NULL,
    entrypoint   TEXT,
    cwd          TEXT,
    is_sidechain INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, ts);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TABLE IF NOT EXISTS project_aliases (
    path_prefix TEXT PRIMARY KEY,
    project     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scope           TEXT NOT NULL CHECK (scope IN ('project', 'session')),
    key             TEXT NOT NULL,
    covers_until_ts TEXT,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS digests_key ON digests(scope, key, id);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("CLAUDE_BRAIN_DB") or DEFAULT_DB).expanduser()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def normalize_name(name: str) -> str:
    """Lowercase ASCII alphanumerics only, so 'ML-vs-GNN' and 'MLvsGNN' collide on purpose.

    A leading year ('2026-ML vs GNN') is dropped too, so dated research folders join
    their undated code repos.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    flat = re.sub(r"[^a-z0-9]", "", ascii_name.lower())
    return re.sub(r"^(19|20)\d{2}(?=[a-z])", "", flat) or flat


def project_for(cwd: str | None, aliases: list[tuple[str, str]]) -> str:
    """Project name for a cwd: longest matching alias prefix, else the folder's normalized name.

    `aliases` must be sorted by prefix length, longest first.
    """
    if not cwd:
        return "unknown"
    cwd = cwd.rstrip("/") or "/"
    for prefix, project in aliases:
        if cwd == prefix or cwd.startswith(prefix + "/"):
            return project
    # Headless runs in throwaway temp dirs would otherwise each become a "project".
    if cwd == "/tmp" or cwd.startswith("/tmp/"):
        return "tmp"
    return normalize_name(Path(cwd).name) or "root"


def load_aliases(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT path_prefix, project FROM project_aliases").fetchall()
    return sorted(((r[0], r[1]) for r in rows), key=lambda a: len(a[0]), reverse=True)
