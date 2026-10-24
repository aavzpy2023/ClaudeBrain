# claude_brain — project memory

Archives every Claude Code session (CLI, VSCode, Desktop-Code) from `~/.claude/projects/**/*.jsonl`
into SQLite (`~/.local/share/claude-brain/brain.db`, override with `CLAUDE_BRAIN_DB`) so later
sessions can recall and report on past work. Stdlib-only Python so the hook needs no venv;
`uv run pytest` for tests.

- **Project naming (machine-independent on purpose).** Precedence in `project_for`: alias on the
  session's git remote → alias on any cwd folder name (deepest first) → repo name (remote's last
  segment, else repo root folder; looked up in aliases too) → `tmp` for temp dirs → cwd's last
  folder. Names are normalized (casefolded, accents stripped, letters/digits of any script
  kept, leading year dropped). `folder_aliases`
  keys are normalized folder names OR remotes like `github.com/owner/repo` (contain `/`).
  `sessions.repo`/`repo_root` are resolved once per session after each ingest (`resolve_repos`,
  reading .git files; `repo_root=''` = checked, not a repo) and kept even if the folder vanishes.
  POSIX and Windows paths both parsed. Legacy `project_aliases` (≤0.3) is copied forward on connect.
  Files: `brain/db.py::project_for`, `brain/db.py::set_alias`, `brain/db.py::resolve_repos`, `brain/gitrepo.py::find_repo`, `brain/gitrepo.py::normalize_remote`
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
- **Two install paths, never both.** (1) Plugin (default): repo root = plugin root = its own
  marketplace (`.claude-plugin/plugin.json` name `brain` — `claude-*` plugin names are reserved;
  `marketplace.json` name `aavzpy2023`, source `./`). `hooks/hooks.json` runs
  `python3 ${CLAUDE_PLUGIN_ROOT}/brain/hook.py [--sync]` (exec form) on SessionStart + Stop (async,
  --sync) and SessionEnd; `bin/claude-brain` is on
  Claude's PATH; `skills/recall/SKILL.md` calls bare `claude-brain` and pre-approves it via
  `allowed-tools`; `commands/setup.md` and `commands/cloud.md` do what a plugin can't (edit
  settings, guide cloud setup). Local-only until NEON_URL exists. (2) `install.py` for Windows /
  no plugins: renders the same skill replacing bare `claude-brain` with this machine's
  `python bin/claude-brain`, merges exec-form hooks + permission + retention into settings.json
  (recognized by `brain/ingest.py`|`brain/hook.py` / `brain/query.py`|`bin/claude-brain`),
  `--uninstall` reverses it. `hook.py` logs to `~/.local/share/claude-brain/ingest.log`, exits 0.
  Files: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `skills/recall/SKILL.md`, `bin/claude-brain`, `brain/cli.py`, `brain/install.py::render_skill`, `brain/install.py::merge_settings`
- **Cloud mirror (optional).** `sync.py` pushes SQLite → Neon after each ingest (Stop hook only,
  async): messages/digests by rowid/id watermark in `sync_state`, sessions fully upserted; offline
  = no-op. Text is redacted before upload. psycopg is the only dependency and only sync needs it.
  claude.ai reads via the Neon MCP connector as `brain_reader` (SELECT-only, created in SQL,
  needs a password). Several machines may push to one mirror: remote digests are keyed by
  `origin` = `<hostname>:<local id>`; folder aliases sync both ways (`sync_aliases`, last write
  wins by `updated_at`) before sessions are pushed.
  Sync runs as `uv run --no-project --with psycopg sync.py` (`sync.uv_command`) — never a venv in
  the repo/plugin folder. `remote/claude_ai_instructions.md` is a template (`{{NEON_PROJECT_ID}}`)
  rendered by `sync.py --claude-ai`; no personal ids in the repo.
  Files: `brain/sync.py::redact`, `brain/sync.py::uv_command`, `brain/sync.py::main`, `remote/schema.sql`, `remote/claude_ai_instructions.md`
- **Cloud schema is versioned and only moves forward.** `remote/schema.sql` declares
  `-- schema_version: N`; every sync runs `ensure_schema` first: applies the file under
  `pg_advisory_xact_lock` when Neon's `brain_meta.schema_version` is lower (or absent), never when
  it is higher — an outdated machine keeps pushing but must not roll functions back. So schema
  changes must bump N and stay additive. `brain_meta` also holds `reader_password` (set by
  `set_reader_password`; `assumed` for mirrors from before versioning) and `synced:<host>`.
  `cloud setup` sets the connector password only when `reader_password` is absent — rotating it
  breaks the claude.ai connector, so only explicit `cloud reader-password` does that.
  Credentials: `cloud connect` (cli.py, getpass, refuses without a TTY) → `sync.write_env` (0600);
  `env_problems` only warns, never blocks.
  Files: `brain/sync.py::ensure_schema`, `brain/sync.py::schema_plan`, `brain/sync.py::remote_status`, `brain/sync.py::write_env`, `brain/cli.py::cloud_connect`, `remote/schema.sql`
- **Reads go to Neon when the cloud is on.** `query.main` sends `READ_COMMANDS` to
  `brain/remote.py` (uv + psycopg, direct endpoint, read-only connection), which implements the
  same read API with Postgres SQL and reuses `query._run` for identical output plus `@host`.
  Exit code `REMOTE_OFFLINE` (75) → local fallback with a note; `--local` skips it; writes
  (`save-digest`, `alias`) are always local and reach Neon by sync. `sessions.host` exists only
  in Neon (filled by `push_sessions`). Tests are isolated from any real Neon by an autouse
  fixture in `tests/conftest.py`.
  Files: `brain/query.py::main`, `brain/query.py::_run`, `brain/remote.py`, `tests/conftest.py::no_real_cloud`
- **Search syntax is implemented twice and must stay identical.** Local `fts_query` (FTS5) and
  Neon `brain_tsquery` (plpgsql): words ANDed, last word of each term stemmed (`STEM_SUFFIXES`,
  remainder ≥ `STEM_MIN`) and prefix-matched (≥ `PREFIX_MIN` letters), `OR`, "phrase", -exclude.
  Neon indexes `brain_plain(text)` (unaccent + lower + paths/URLs/hyphens split) so its tokens
  match unicode61's. Verify parity by comparing hit counts on real data after any change.
  Diagnostics against Neon must use `SET LOCAL ROLE` inside a transaction — the pooled endpoint
  leaks session `SET ROLE` to other clients (sync itself uses the direct endpoint).
  Files: `brain/query.py::fts_query`, `brain/query.py::stem`, `remote/schema.sql`, `brain/sync.py::direct_url`
- **MCP server is opt-in per client.** `mcp_server.py` (MCPServer from the `mcp` 2.x SDK, run
  via uv) exposes the read commands as read-only tools whose output is `query.render()` text,
  redacted unless `--no-redact`; Neon when configured, local fallback. Clients point at
  `~/.local/share/claude-brain/mcp-launch.py` (copy of `brain/mcp_launch.py`, stdlib only), which
  reads the current ClaudeBrain path from `root` — written by `hook.py` via
  `mcp_setup.record_root()` on every hook run, so plugin updates don't break client configs.
  `mcp_setup` edits only the `claude-brain` entry of Claude Desktop's config (backup kept).
  Files: `brain/mcp_server.py`, `brain/mcp_launch.py`, `brain/mcp_setup.py::enable`, `brain/mcp_setup.py::record_root`
- **Session briefing is opt-in and must stay cheap.** A synchronous SessionStart hook
  (`context.py --hook`, timeout 10 s) emits `additionalContext` listing the latest N sessions of
  the cwd's project (same naming as ingest: `find_repo` + `project_for`). Off unless
  `<state dir>/context` holds N; only for `source` startup/clear; local DB only, no ingest or
  network, swallows every error. Titles only — never message text.
  Files: `brain/context.py::briefing`, `brain/context.py::run_hook`, `brain/db.py::project_of_cwd`, `hooks/hooks.json`, `brain/install.py::commands`
- **`blame` matches files by repo-relative path, anchored to the session's folder.** `blame.py`
  runs over any read API (primitives `file_mentions` / `sessions_meta` / `user_prompts` in
  `query.py` and `remote.py`): candidates by substring (`instr`/`strpos`, both separator
  styles), then per line: Edit/Write/MultiEdit/NotebookEdit JSON path → edit; `[tool:Bash]`
  naming the file → shell; anything else → mention. `is_same_file` requires the part before the
  relative path to be the session's cwd or a parent of it (so `lib/src/x.py` ≠ `src/x.py`).
  "Why" = last user message before each change. Commits (`git log --follow`, local repo) go to
  the changing session active at commit time (+30 min). Project defaults to `project_of_cwd`.
  Files: `brain/blame.py::blame`, `brain/blame.py::is_same_file`, `brain/query.py::file_mentions`, `brain/remote.py::file_mentions`, `brain/db.py::project_of_cwd`
- **`stats` aggregates in the database, shapes in Python.** Primitive `stats_data` (in
  `query.py` and `remote.py`, same SQL apart from `instr`/`strpos` and placeholders) returns
  counts per UTC hour × role × project × source (+ word estimate), tool calls by name (first
  tool per message), and sessions in range; `stats.compute` turns hours into local days,
  streaks and the hour profile. Subagent messages excluded.
  Output encoding: entry points call `brain.utf8_output()` (Windows pipes default to cp1252).
  Files: `brain/stats.py::compute`, `brain/query.py::stats_data`, `brain/remote.py::stats_data`, `brain/__init__.py::utf8_output`
- **Forgetting is tombstoned and synced.** `forget` deletes locally and records
  `forgotten(session_id, synced)`; `ingest_file` and `import_export` skip tombstoned ids (so
  `ingest --full` can't resurrect them). Cloud work goes through the next sync:
  `sync_forgotten` runs before any push — deletes pending tombstones' rows in Neon, applies
  `pending_remote` ops (`redact` text → `[REDACTED:manual]`, `project_digests`), then pulls
  Neon's `forgotten` and drops those sessions locally. Neon schema v2 adds `forgotten`.
  Claude Code transcripts are only deleted with `--transcripts`.
  Files: `brain/forget.py::forget_sessions`, `brain/forget.py::redact_text`, `brain/sync.py::sync_forgotten`, `brain/ingest.py::ingest_file`, `remote/schema.sql`
- **Markdown export** works over any read API (`query` or `remote`), so with the cloud on it
  exports every device. Note names `<date>_<slug>_<id8>.md`, index `<project>.md`; writes only
  changed files and never deletes; redacts with `sync.redact` unless `--no-redact`.
  Files: `brain/export.py::export_project`, `brain/export.py::render_session`
- **claude.ai importer.** Official export → sessions with entrypoint `claude-ai`, session id =
  conversation uuid, message uuid kept (`<conv>:<i>` if missing), `INSERT OR IGNORE` so re-imports
  only add. Pseudo cwd `claude.ai/<Project name>` (or `claude.ai`) + `repo_root=''` lets
  `project_for`/aliases name it and keeps the repo resolver off. Format is undocumented and the
  conversation→project link IS absent in the real 2026 export (manifest of zips:
  conversations-000.zip, projects-000.zip with projects/<uuid>.json, frames = artifacts,
  light_metadata = login history — never read). `load_export` only opens zips named
  conversations*/projects*, dedups by uuid; `--inspect` shows structure, not content.
  Files: `brain/importer.py::import_export`, `brain/importer.py::message_text`, `brain/importer.py::load_export`
- **README is the living doc.** Every user-visible change updates its Roadmap checkboxes and adds
  a Changelog entry in the same commit.
  Files: `README.md`

