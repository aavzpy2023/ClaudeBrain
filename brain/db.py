import os
import re
import sqlite3
import tempfile
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

-- Keyed by normalized folder name, not path, so one alias holds on every machine (and syncs).
CREATE TABLE IF NOT EXISTS folder_aliases (
    folder     TEXT PRIMARY KEY,
    project    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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
    _migrate_path_aliases(conn)
    return conn


def _migrate_path_aliases(conn: sqlite3.Connection) -> None:
    # 0.3.x stored aliases by absolute path prefix (project_aliases); keep the table, copy forward.
    if conn.execute("SELECT 1 FROM folder_aliases LIMIT 1").fetchone():
        return
    rows = conn.execute("SELECT path_prefix, project FROM project_aliases").fetchall()
    for prefix, project in rows:
        folder = folder_key(prefix)
        if folder:
            conn.execute("INSERT OR IGNORE INTO folder_aliases(folder, project) VALUES (?, ?)",
                         (folder, project))
    if rows:
        conn.commit()


def normalize_name(name: str) -> str:
    """Lowercase ASCII alphanumerics only, so 'ML-vs-GNN' and 'MLvsGNN' collide on purpose.

    A leading year ('2026-ML vs GNN') is dropped too, so dated research folders join
    their undated code repos.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    flat = re.sub(r"[^a-z0-9]", "", ascii_name.lower())
    return re.sub(r"^(19|20)\d{2}(?=[a-z])", "", flat) or flat


def path_parts(path: str) -> list[str]:
    """Folder names of a POSIX or Windows path, whatever OS recorded or reads it."""
    return [p for p in re.split(r"[\\/]+", path) if p and not re.fullmatch(r"[A-Za-z]:", p)]


def folder_key(path_or_name: str) -> str:
    """Alias key: the normalized last folder name of a path, or of a bare folder name."""
    parts = path_parts(path_or_name)
    return normalize_name(parts[-1]) if parts else ""


def project_for(cwd: str | None, aliases: dict[str, str]) -> str:
    """Project for a cwd: the deepest folder with an alias, else the last folder's normalized name."""
    if not cwd:
        return "unknown"
    parts = path_parts(cwd)
    for part in reversed(parts):
        project = aliases.get(normalize_name(part))
        if project:
            return project
    # Headless runs in throwaway temp dirs would otherwise each become a "project".
    temp = path_parts(tempfile.gettempdir())
    if (parts[:1] == ["tmp"] and cwd.startswith("/")) or (temp and parts[: len(temp)] == temp):
        return "tmp"
    return normalize_name(parts[-1]) if parts else "root"


def load_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT folder, project FROM folder_aliases")}


def set_alias(conn: sqlite3.Connection, folder_or_path: str, project: str) -> int:
    """Map a folder name (any depth, any machine) to a project; returns sessions relabelled."""
    folder = folder_key(folder_or_path)
    if not folder:
        raise ValueError(f"no folder name in {folder_or_path!r}")
    conn.execute(
        """INSERT INTO folder_aliases(folder, project) VALUES (?, ?)
           ON CONFLICT(folder) DO UPDATE SET project = excluded.project,
             updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        (folder, normalize_name(project)),
    )
    return relabel_sessions(conn)


def relabel_sessions(conn: sqlite3.Connection) -> int:
    aliases = load_aliases(conn)
    changed = 0
    for sid, cwd, current in conn.execute(
        "SELECT session_id, project_cwd, project FROM sessions WHERE project_cwd IS NOT NULL"
    ).fetchall():
        new = project_for(cwd, aliases)
        if new != current:
            conn.execute("UPDATE sessions SET project = ? WHERE session_id = ?", (new, sid))
            changed += 1
    conn.commit()
    return changed
