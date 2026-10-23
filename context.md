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
  `python3 ${CLAUDE_PLUGIN_ROOT}/brain/hook.py [--sync]` (exec form); `bin/claude-brain` is on
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
- **Search syntax is implemented twice and must stay identical.** Local `fts_query` (FTS5) and
  Neon `brain_tsquery` (plpgsql): words ANDed, last word of each term stemmed (`STEM_SUFFIXES`,
  remainder ≥ `STEM_MIN`) and prefix-matched (≥ `PREFIX_MIN` letters), `OR`, "phrase", -exclude.
  Neon indexes `brain_plain(text)` (unaccent + lower + paths/URLs/hyphens split) so its tokens
  match unicode61's. Verify parity by comparing hit counts on real data after any change.
  Diagnostics against Neon must use `SET LOCAL ROLE` inside a transaction — the pooled endpoint
  leaks session `SET ROLE` to other clients (sync itself uses the direct endpoint).
  Files: `brain/query.py::fts_query`, `brain/query.py::stem`, `remote/schema.sql`, `brain/sync.py::direct_url`
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

