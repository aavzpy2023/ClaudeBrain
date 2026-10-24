import os
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path

from brain.gitrepo import find_repo, normalize_remote

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
    msg_count   INTEGER NOT NULL DEFAULT 0,
    repo        TEXT,  -- normalized git remote, e.g. github.com/owner/repo
    repo_root   TEXT   -- NULL = not checked yet, '' = not a git repo (or folder gone)
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

-- Keyed by normalized folder name or git remote (never a path), so one alias holds on every
-- machine and syncs. Column name predates remote keys.
CREATE TABLE IF NOT EXISTS folder_aliases (
    folder     TEXT PRIMARY KEY,
    project    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Sessions the user asked to forget (tombstones): ingest and import skip them; sync removes
-- them from the cloud (synced = 1 once done) and pulls other machines' tombstones.
CREATE TABLE IF NOT EXISTS forgotten (
    session_id   TEXT PRIMARY KEY,
    forgotten_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    synced       INTEGER NOT NULL DEFAULT 0
);

-- Cloud work `forget` leaves for the next sync: ('redact', text) or ('project_digests', name).
CREATE TABLE IF NOT EXISTS pending_remote (
    op  TEXT NOT NULL,
    arg TEXT NOT NULL,
    PRIMARY KEY (op, arg)
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
    _migrate_repo_columns(conn)
    conn.executescript(SCHEMA)
    _migrate_path_aliases(conn)
    return conn


def _migrate_repo_columns(conn: sqlite3.Connection) -> None:
    # Databases from ≤0.4 have sessions without repo/repo_root; CREATE IF NOT EXISTS won't add them.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    if cols:
        for col in ("repo", "repo_root"):
            if col not in cols:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")


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
    """Lowercase letters and digits only, so 'ML-vs-GNN' and 'MLvsGNN' collide on purpose.

    Accents are stripped ('Tésis' → 'tesis', 'Straße' → 'strasse') but letters of any script are
    kept ('项目', 'проект'), so non-Latin folder names still get a name. A leading year
    ('2026-ML vs GNN') is dropped too, so dated research folders join their undated code repos.
    """
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    base = "".join(c for c in decomposed if not unicodedata.combining(c))
    flat = re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", base))
    return re.sub(r"^(19|20)\d{2}(?=[^\W\d_])", "", flat) or flat


def path_parts(path: str) -> list[str]:
    """Folder names of a POSIX or Windows path, whatever OS recorded or reads it."""
    return [p for p in re.split(r"[\\/]+", path) if p and not re.fullmatch(r"[A-Za-z]:", p)]


def folder_key(path_or_name: str) -> str:
    """Alias key: the normalized last folder name of a path, or of a bare folder name."""
    parts = path_parts(path_or_name)
    return normalize_name(parts[-1]) if parts else ""


def project_for(cwd: str | None, aliases: dict[str, str],
                repo: str | None = None, repo_root: str | None = None) -> str:
    """Project for a session, most specific rule first:

    1. an alias on its git remote (github.com/owner/repo);
    2. an alias on any folder of its cwd, deepest first;
    3. the repo's name (from the remote, else the repo root folder), through its alias if any;
    4. `tmp` for throwaway temp dirs;
    5. the cwd's last folder name.
    """
    if repo and repo in aliases:
        return aliases[repo]
    if not cwd:
        return "unknown"
    parts = path_parts(cwd)
    for part in reversed(parts):
        project = aliases.get(normalize_name(part))
        if project:
            return project
    if repo_root:
        name = normalize_name(repo.rsplit("/", 1)[-1]) if repo else folder_key(repo_root)
        if name:
            return aliases.get(name, name)
    # Headless runs in throwaway temp dirs would otherwise each become a "project".
    temp = path_parts(tempfile.gettempdir())
    if (parts[:1] == ["tmp"] and cwd.startswith("/")) or (temp and parts[: len(temp)] == temp):
        return "tmp"
    return normalize_name(parts[-1]) if parts else "root"


def forgotten_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT session_id FROM forgotten")}


def project_of_cwd(conn: sqlite3.Connection, cwd: str) -> str:
    """The project a session opened in `cwd` would get (same rules as ingest)."""
    repo, root = find_repo(cwd)
    return project_for(cwd, load_aliases(conn), repo, root)


def load_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT folder, project FROM folder_aliases")}


def repo_key(text: str) -> str | None:
    """A git remote in any spelling, or an already-normalized 'host.tld/owner/repo'."""
    remote = normalize_remote(text)
    if remote:
        return remote
    text = text.strip().lower()
    if re.fullmatch(r"[\w.-]+\.[a-z]{2,}(?:/[\w.-]+){2,}/?", text):
        return re.sub(r"\.git$", "", text.strip("/"))
    return None


def set_alias(conn: sqlite3.Connection, target: str, project: str) -> int:
    """Alias a folder name, a git remote, or an existing folder path (its name, plus its repo's
    remote if it is in one) to a project, on every machine once synced. Returns sessions relabelled."""
    expanded = os.path.expanduser(target)
    if os.path.isdir(expanded):
        keys = [folder_key(expanded), find_repo(expanded)[0]]
    else:
        remote = repo_key(target)
        keys = [remote] if remote else [folder_key(target)]
    keys = [k for k in keys if k]
    if not keys:
        raise ValueError(f"nothing to alias in {target!r}")
    conn.executemany(
        """INSERT INTO folder_aliases(folder, project) VALUES (?, ?)
           ON CONFLICT(folder) DO UPDATE SET project = excluded.project,
             updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        [(k, normalize_name(project)) for k in keys],
    )
    return relabel_sessions(conn)


def relabel_sessions(conn: sqlite3.Connection) -> int:
    aliases = load_aliases(conn)
    changed = 0
    for sid, cwd, repo, root, current in conn.execute(
        """SELECT session_id, project_cwd, repo, repo_root, project
           FROM sessions WHERE project_cwd IS NOT NULL"""
    ).fetchall():
        new = project_for(cwd, aliases, repo, root)
        if new != current:
            conn.execute("UPDATE sessions SET project = ? WHERE session_id = ?", (new, sid))
            changed += 1
    conn.commit()
    return changed


def resolve_repos(conn: sqlite3.Connection) -> int:
    """Record the git repo of sessions not checked yet (once: the folder may vanish later),
    then relabel. Returns how many sessions were checked."""
    rows = conn.execute(
        "SELECT session_id, project_cwd FROM sessions WHERE repo_root IS NULL AND project_cwd IS NOT NULL"
    ).fetchall()
    cache: dict[str, tuple] = {}
    for sid, cwd in rows:
        if cwd not in cache:
            cache[cwd] = find_repo(cwd)
        repo, root = cache[cwd]
        conn.execute("UPDATE sessions SET repo = ?, repo_root = ? WHERE session_id = ?",
                     (repo, root or "", sid))
    if rows:
        relabel_sessions(conn)
    return len(rows)
