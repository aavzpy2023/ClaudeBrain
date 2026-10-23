# claude_brain — project memory

Archives every Claude Code session (CLI, VSCode, Desktop-Code) from `~/.claude/projects/**/*.jsonl`
into SQLite (`~/.local/share/claude-brain/brain.db`, override with `CLAUDE_BRAIN_DB`) so later
sessions can recall and report on past work. Stdlib-only Python so the hook needs no venv;
`uv run pytest` for tests.

- **Schema, connection, project naming.** Project = cwd folder name normalized (lowercase ASCII
  alnum, leading year dropped); `project_aliases` (longest prefix wins) overrides it; anything
  under `/tmp` is `tmp`.
  Files: `brain/db.py::SCHEMA`, `brain/db.py::normalize_name`, `brain/db.py::project_for`
- **Ingestion is incremental and idempotent.** Per-file byte offset in `files`; partial last line
  left for next run; `INSERT OR IGNORE` on message `uuid`. Lines starting `{"type":"` are skipped
  unparsed (bookkeeping, multi-MB blobs) except `ai-title`/`custom-title`; a custom title
  (`/rename`) is never overwritten by an AI title.
  Files: `brain/ingest.py::ingest`, `brain/ingest.py::ingest_file`
- **What is stored.** Roles: `user`, `assistant` (prose), `tool` (tool calls and results, truncated),
  `summary` (compaction summaries + `away_summary` recaps). Dropped: thinking, `isMeta`, task
  notifications, injected tags (`system-reminder`, `ide_selection`…). Subagent messages kept with
  `is_sidechain=1`, hidden by default in queries.
  Files: `brain/ingest.py::extract`
- **Query API** (pure functions over a connection, meant to be reused by a future MCP server):
  search (FTS5, accent-insensitive, terms quoted), recent, session (paged via `--after`),
  projects, project (timeline + latest digest), save_digest, alias.
  Files: `brain/query.py`
- **Digests = lazy cache of distilled summaries.** Written by Claude after reading a project;
  `covers_until_ts` marks what is covered so the next report only reads newer sessions.
  Files: `brain/query.py::save_digest`, `brain/query.py::project`
- **Integration is done by the installer, never by hand.** `install.py` renders the skill
  template (`{{BRAIN_QUERY}}` → this machine's quoted python + query.py) into
  `~/.claude/skills/claude-brain/` (replacing old symlinks), and merges into settings.json an async
  `Stop` hook (ingest, then sync if NEON_URL) + `SessionEnd` hook (ingest only), the query
  permission rule and `cleanupPeriodDays` 3650. Its own hooks/rules are recognized by the
  substrings `brain/ingest.py` / `brain/query.py` and replaced, so re-runs are idempotent.
  Honors `CLAUDE_CONFIG_DIR`. Errors go to `~/.local/share/claude-brain/ingest.log`.
  Files: `brain/install.py::merge_settings`, `brain/install.py::install_skill`, `skill/SKILL.md`
- **Cloud mirror (optional).** `sync.py` pushes SQLite → Neon after each ingest (Stop hook only,
  async): messages/digests by rowid/id watermark in `sync_state`, sessions fully upserted; offline
  = no-op. Text is redacted before upload. psycopg is the only dependency and only sync needs it.
  claude.ai reads via the Neon MCP connector as `brain_reader` (SELECT-only, created in SQL,
  needs a password). Several machines may push to one mirror: remote digests are keyed by
  `origin` = `<hostname>:<local id>`; aliases stay per machine.
  Files: `brain/sync.py::redact`, `brain/sync.py::main`, `remote/schema.sql`, `remote/claude_ai_instructions.md`
- **README is the living doc.** Every user-visible change updates its Roadmap checkboxes and adds
  a Changelog entry in the same commit.
  Files: `README.md`
- **Not built yet:** importer for the claude.ai data export (`conversations.json`).
