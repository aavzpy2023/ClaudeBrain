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
- **Integration.** Skill symlinked as `~/.claude/skills/claude-brain` → `skill/`; `SessionEnd`
  hook in `~/.claude/settings.json` runs `/usr/bin/python3 brain/ingest.py --quiet` (errors to
  `~/.local/share/claude-brain/ingest.log`); `cleanupPeriodDays: 3650` there keeps transcripts.
  Files: `skill/SKILL.md`
- **README is the living doc.** Every user-visible change updates its Roadmap checkboxes and adds
  a Changelog entry in the same commit.
  Files: `README.md`
- **Phase 2 (not built):** MCP server over `brain/query.py` for Claude Desktop/claude.ai chat;
  importer for the claude.ai data export (`conversations.json`).
