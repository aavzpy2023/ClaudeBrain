<div align="center">

# 🧠 ClaudeBrain

**Long-term memory for Claude Code.**
Every conversation you have in the terminal or VS Code — archived, searchable and resumable,
in one small SQLite file.

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-FTS5-003B57?logo=sqlite&logoColor=white)
![Dependencies](https://img.shields.io/badge/core%20deps-0-brightgreen)
![Neon](https://img.shields.io/badge/cloud-Neon%20Postgres-00E599?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-yellow)

</div>

---

## The problem

Claude Code keeps each session as a JSONL transcript under `~/.claude/projects/` — and then:

- 🗑️ **deletes them after 30 days** (`cleanupPeriodDays` default),
- 🗜️ **compacts** long conversations, so the live context loses the early details,
- 🧩 **scatters** them per folder, per surface (CLI, VS Code, Desktop), with no way to search across them.

Months of decisions, experiments and dead ends simply vanish.

## The idea

> Work with Claude exactly as always. In the background, every message is saved.
> Whenever you need it — *"what did we decide about X?"*, *"resume the session about Y"*,
> *"write me a report of project Z"* — Claude looks it up.

No extra app, no UI to learn: **you ask Claude in plain language, Claude queries the database
and shows you the result.**

---

## ✨ Features

| | |
|---|---|
| ⚡ **Automatic & invisible** | A `Stop` hook archives new messages after every Claude reply, asynchronously (~0.1 s). Nothing to remember. |
| 🖥️ **Every Claude Code surface** | CLI, VS Code extension and Claude Desktop's Code tab all land in the same database, tagged by origin. |
| 📥 **claude.ai chats too** | Import the official data export (web, Desktop and mobile chats); chats in a claude.ai Project join the Claude Code project of the same name. |
| 🔍 **Full-text search** | SQLite FTS5, accent-insensitive (`regresion` finds `regresión`), ranked with BM25, with highlighted snippets. |
| 📁 **Organized by project** | Git repos are identified by their remote (`github.com/owner/repo`), so every clone and every subfolder lands in one project; other folders by their normalized name — `2026-ML vs GNN` and `MLvsGNN` merge into `mlvsgnn`. Aliases (by folder name or remote) handle the exceptions and are shared by all your computers. |
| 🪟 **Linux, macOS, Windows** | Hooks run Python directly (no shell syntax), paths are handled in both styles. |
| ♻️ **Resumable** | Finds the session and hands you the exact `claude --resume` command — or continues from the archive if the original transcript is gone. |
| 📝 **Lazy digests** | When Claude summarizes a project for you, it caches the summary; the next report only reads what happened since. Zero cost up front. |
| 🪶 **Tiny & dependency-free** | Pure Python stdlib. 1.5 GB of raw transcripts → **18 MB** database, full backfill in **7 s**. |
| ☁️ **Ask from your phone** | Optional mirror to Neon Postgres, queried from claude.ai (web, mobile, Desktop chat) through Neon's official connector — read-only, secrets redacted. |
| 📴 **Offline-first** | The local SQLite is the source of truth; sync just catches up whenever there is internet. |

---

## 🏗️ How it works

```mermaid
flowchart LR
    subgraph Surfaces["Claude Code"]
        CLI["🖥️ CLI"]
        VS["🧩 VS Code"]
        DK["💻 Desktop (Code)"]
    end

    CLI & VS & DK -->|write| JSONL[("~/.claude/projects/**/*.jsonl")]

    JSONL -->|"Stop hook (async, every reply)<br/>SessionEnd hook (fallback)"| ING["brain/hook.py → ingest.py<br/>incremental · idempotent · git-aware"]
    ING --> DB[("🧠 brain.db<br/>SQLite + FTS5")]
    EXPORT(["📦 claude.ai data export"]) -->|"brain/importer.py (by hand)"| DB

    YOU(["🙋 You: '¿qué decidimos sobre X?'"]) --> SKILL["claude-brain skill"]
    SKILL -->|"brain/query.py"| DB
    DB --> ANS(["📄 Answer · report · resume command"])
    SKILL -.->|save-digest| DB

    DB <-->|"brain/sync.py (after each ingest, when online)<br/>secrets redacted · aliases both ways"| NEON[("☁️ Neon Postgres")]
    PHONE(["📱 claude.ai web / mobile"]) -->|"Neon MCP connector<br/>read-only · brain_reader"| NEON
```

**Ingestion** reads each transcript from the last byte offset it saw, so a run with nothing new
costs ~0.1 s. Partial lines (a reply still being written) are left for the next run, and every
message is keyed by its UUID, so concurrent runs and re-runs never duplicate anything.

**Querying** is done by Claude itself through the `claude-brain` skill, which knows the commands
and the workflows (search → read, project → digest → report, find → resume).

### What gets stored

| Role | Content | Shown by default |
|---|---|:---:|
| `user` | Your messages, minus injected noise (`<system-reminder>`, IDE selections…) | ✅ |
| `assistant` | Claude's prose replies, in full | ✅ |
| `summary` | Claude Code's own compaction summaries and "while you were away" recaps — dense gold | ✅ |
| `tool` | Tool calls (input truncated to 300 chars) and results (truncated to 200 chars) | `--tools` |

Dropped entirely: thinking blocks, meta messages, task notifications, API bookkeeping, images.
Imported claude.ai chats use the same roles (their conversation `summary`, when present, as `summary`).
Subagent messages are kept but flagged (`--sidechain` to include them).

### Data model

```mermaid
erDiagram
    PROJECT ||--o{ SESSION : "git remote, folder name or alias"
    SESSION ||--o{ MESSAGE : contains
    PROJECT ||--o{ DIGEST : "summarized by"
    SESSION ||--o{ DIGEST : "summarized by"
    ALIAS }o--|| PROJECT : "renames"

    SESSION {
        text session_id PK
        text project
        text project_cwd
        text entrypoint "cli | claude-vscode | claude-desktop | claude-ai"
        text title "AI title, or your /rename"
        text first_ts
        text last_ts
        int  msg_count
        text repo "normalized git remote, if any"
    }
    ALIAS {
        text folder PK "folder name or git remote"
        text project
        text updated_at "last write wins across machines"
    }
    MESSAGE {
        text uuid PK
        text session_id FK
        text ts
        text role "user | assistant | summary | tool"
        int  is_sidechain
        text text "FTS5-indexed"
    }
    DIGEST {
        int  id PK
        text scope "project | session"
        text key
        text covers_until_ts
        text content
    }
```

---

## 🚀 Installation

> Requirements: Python 3.10+ with SQLite FTS5 (any python.org / distro build), Claude Code.
> For the cloud mirror also [uv](https://docs.astral.sh/uv/). Linux and macOS are tested;
> Windows is supported (see below) but not yet tested on a real machine.

```bash
git clone git@github.com:aavzpy2023/ClaudeBrain.git ~/Projects/ClaudeBrain
cd ~/Projects/ClaudeBrain

# optional — only for the cloud mirror (see below): owner connection string of your Neon DB
mkdir -p ~/.config/claude-brain
printf 'NEON_URL=%s\n' 'postgresql://…' > ~/.config/claude-brain/.env
chmod 600 ~/.config/claude-brain/.env

python3 brain/install.py
```

The installer, safe to re-run at any time:

| Step | What it does |
|---|---|
| Skill | Renders `skill/SKILL.md` with this machine's paths into `~/.claude/skills/claude-brain/` |
| Hooks | Adds an async `Stop` hook (ingest, then sync if Neon is configured) and a `SessionEnd` hook (ingest) |
| Permission | Allows the skill's exact `query.py` command, so queries never prompt |
| Retention | Raises `cleanupPeriodDays` to 3650 so Claude Code stops deleting transcripts |
| Backfill | Archives everything Claude Code still has on disk (`ingest.py --full`) |
| Cloud | With `NEON_URL`: creates/upgrades the remote schema and pushes everything (`sync.py --init`) |

It merges into `~/.claude/settings.json` without touching your other settings, replaces its own
previous hooks instead of duplicating them, and leaves a backup in
`settings.json.bak-claudebrain`. Honors `CLAUDE_CONFIG_DIR`. Then open `/hooks` once (or restart
Claude Code) so running sessions pick up the hooks.

<details>
<summary><b>🪟 Windows</b> (PowerShell)</summary>

```powershell
git clone git@github.com:aavzpy2023/ClaudeBrain.git $HOME\Projects\ClaudeBrain
cd $HOME\Projects\ClaudeBrain

# optional — cloud mirror
New-Item -ItemType Directory -Force $HOME\.config\claude-brain | Out-Null
Set-Content $HOME\.config\claude-brain\.env 'NEON_URL=postgresql://…'

py -3 brain\install.py
```

Same files as on Linux, under your user folder: `%USERPROFILE%\.claude\` for Claude Code,
`%USERPROFILE%\.local\share\claude-brain\brain.db` for the database. Hooks are written in
exec form (`"command": "C:/…/python.exe", "args": ["…/brain/hook.py", …]`), so they don't
depend on Git Bash or PowerShell; Claude's own queries go through its Bash tool (Git Bash),
hence the forward-slash paths in the skill.

</details>

### ☁️ Cloud mirror + claude.ai access (optional)

1. Create a Neon project and put its **owner** connection string in `~/.config/claude-brain/.env`
   (above). Never commit it, never paste it into a chat — it would end up archived.
2. Run the installer (or `uv run brain/sync.py --init`): tables, search functions and the
   read-only role `brain_reader` are created.
3. Give `brain_reader` a password and add the connector and the "Brain" project on claude.ai,
   following [`remote/claude_ai_instructions.md`](remote/claude_ai_instructions.md).

What reaches the cloud is redacted first: API keys, GitHub/AWS/Google/Slack tokens, JWTs,
private keys, passwords in URLs and `password=`/`token:`-style assignments become
`[REDACTED:…]`. The connector runs as `brain_reader`, a role created with SQL that can only
`SELECT` (Console-created Neon roles join `neon_superuser` and could read everything), inside
read-only transactions (`readonly=true`) and with only Neon's SQL tools exposed
(`category=querying`).

### 🔄 Who updates what

**Only your computers write; claude.ai only reads.**

```
every Claude reply (Stop hook → hook.py, background)
   ├─ ingest.py → local brain.db          always, offline too
   └─ sync.py   ⇄ Neon                    new rows up, aliases both ways; only when online
closing a session (SessionEnd hook → hook.py)
   └─ ingest.py → local brain.db          (its last messages reach Neon with the next reply)
you, from time to time
   └─ importer.py → local brain.db        claude.ai chats; reach Neon with the next sync
```

- `sync.py` connects with the owner string in `~/.config/claude-brain/.env` — the only
  credential that can write, and it never leaves the machine.
- Offline? Archiving keeps working locally; the next reply with internet uploads the backlog.
- Computer off? Neon stays as of the last synced reply; claude.ai keeps answering from that.
- Chats in claude.ai / the mobile app are **not** written automatically (no hooks there) —
  bring them in from time to time with the importer (see Usage).
- Force a sync by hand: `uv run --project <repo> <repo>/brain/sync.py`

### 💻 Several computers

Install the same way on each machine, pointing every `.env` at the **same** Neon database.
Each computer keeps its own local `brain.db` (its own sessions) and pushes into the shared
mirror, so claude.ai sees the union of all of them.

- No collisions: messages and sessions use Claude Code's global UUIDs; digests are keyed by
  `<hostname>:<local id>`.
- The first install on a new machine backfills that machine's existing transcripts (whatever
  Claude Code hasn't deleted yet) and uploads them.
- **The same project adds up across machines.** A session's project is decided, most specific
  first, by: an alias on its git remote → an alias on any folder of its cwd (deepest first) →
  the repo's name (from the remote, else the repo root folder) → the cwd's last folder. The
  remote is read from `.git/config` (worktrees and submodules included, no `git` binary needed)
  the first time a session is seen and then kept, even if the folder is deleted later. So a
  clone named differently, or a session opened in `repo/src/deep`, still lands in the repo's
  project. Aliases are keyed by folder name or remote (`leai-cli` → `devleaicli` wherever it
  lives). Aliases sync both ways through Neon (last write wins), so one created at home
  relabels the work PC's sessions on its next sync — and vice versa.
- A *session* belongs to one machine (Claude Code gives each conversation its own id); it's the
  *project* that collects sessions from every computer.
- Locally, each machine only searches its own sessions; the union lives in Neon (claude.ai).
- On a machine you don't fully trust (e.g. a work laptop), consider a dedicated Neon role with
  only `INSERT/UPDATE/SELECT` on the three tables instead of the owner string.

---

## 💬 Usage

### Just ask Claude

The skill triggers on requests about past work, in English or Spanish:

```text
> ¿qué decidimos sobre la arquitectura del paper downloader?
> busca en mi historial cómo configuré el túnel SSH
> retoma la sesión de las gráficas de papers.sqlite
> hazme un informe de todo el proyecto meta-análisis
> ¿qué sesiones tengo de la tesis?
```

Behind the scenes Claude runs the CLI below, reads the results and answers, writes the
document you asked for, or gives you the exact command to resume.

### Or use the CLI directly

```bash
Q="/usr/bin/python3 $BRAIN/brain/query.py"

$Q projects                                   # all projects, sessions, last activity
$Q recent --project thesis --limit 5          # latest sessions (partial names work)
$Q search "graphsage regresión" --since 2026-10-01
$Q session f1c3077a --max-chars 8000          # condensed transcript (id prefix works)
$Q session f1c3077a --after 2026-10-19T12:12:45Z   # next page
$Q project mlvsgnn                            # timeline + latest digest
$Q save-digest project mlvsgnn <<'EOF'        # cache a distilled summary
Goal… decisions… results… open issues…
EOF
$Q alias "Tareas asignaturas" tareasstats   # folder name → project, any depth, all machines
$Q alias git@github.com:me/leai-cli.git devleaicli   # git remote, any URL form
$Q alias ~/Projects/leai-cli devleaicli       # existing path: its folder name + its repo's remote
```

```text
$ query.py project phdthesis
# project phdthesis

(no digest yet)

## sessions (* = not covered by the digest)
* 1df0b0ad  2026-10-15 20:10 → 2026-10-19 12:10  claude-vscode  788 msgs  Paper_downloader para ScienceDirect
* 81b0deaa  2026-10-16 11:52 → 2026-10-16 20:23  claude-vscode  654 msgs  Migración PaperDownloader de Flask a FastAPI
* 44705308  2026-10-17 13:56 → 2026-10-17 17:43  cli            78 msgs  Carpetas remotas por SSH en VS Code
…
```

### Importing your claude.ai chats

Chats in claude.ai (web, Desktop app, mobile) have no hooks, so they come in through the official
export: **Settings → Privacy → Export data**. You get a `manifest-….json` with one link per file
(each link expires in 24 h and may work only once — open each in the browser where you're
logged in, let it finish):

| File | Contains | Imported |
|---|---|:---:|
| `conversations-000.zip` | `conversations.json` — every chat | ✅ |
| `projects-000.zip` | `projects/<uuid>.json` — one per claude.ai Project | names only |
| `frames-000.zip` | artifacts (HTML versions, pages) | — |
| `light_metadata-000.zip` | user and **login history** | never read |

Put the zips (extracted or not) in one folder and point the importer at it, or at any one of them:

```bash
python3 brain/importer.py ~/Downloads --inspect   # look first: counts, fields, block types
python3 brain/importer.py ~/Downloads             # import; only the export's zips are opened
```

- Each chat becomes a session with origin `claude-ai` (`--source claude-ai` in searches).
- A chat inside a claude.ai Project goes to the project of that name, so the claude.ai Project
  "PhD Thesis" and the Claude Code folder `PhD Thesis` add up in `phdthesis`; aliases apply.
  **Currently the export doesn't say which Project a chat belongs to** (checked on a real
  export, Oct 2026), so for now every chat goes to `claudeai`; the code picks the link up as
  soon as the export includes it.
- Messages keep their text, tool calls (truncated like Claude Code's), attachment names plus the
  start of their extracted text, document titles and file names. Dropped: thinking, images'
  bytes, and claude.ai's injected instructions (`injected_prompt_block`). Messages that are
  empty in the export itself (interrupted replies, edit branches) are skipped.
- Re-import a newer export whenever you like: only new messages are added. The next sync (the
  next Claude Code reply, or `sync.py`) uploads them to Neon.
- The export format is undocumented and may change; `--inspect` shows what yours contains.
- After importing you can delete the downloaded files — especially `light_metadata` (login
  history) and the manifest (download links).

### Resuming an old conversation

| Situation | What happens |
|---|---|
| Original `.jsonl` still on disk | Full-fidelity native resume: `cd "<project folder>" && claude --resume <session-id>` (in VS Code: open the folder, pick it from session history). |
| Transcript already deleted | Claude continues **from the archive**: reads the condensed session plus its compaction summaries, restates where things stood, and carries on. |

---

## ⚙️ Configuration

| Variable / file | Default | Purpose |
|---|---|---|
| `CLAUDE_BRAIN_DB` | `~/.local/share/claude-brain/brain.db` | Database location |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude Code's folder: transcripts, settings, skills |
| `NEON_URL` (env or `~/.config/claude-brain/.env`) | — | Owner connection string; enables the cloud mirror |
| `ingest.py --root` | `~/.claude/projects` | Where transcripts are read from |
| `ingest.py --full` | off | Re-read every file from the start (safe: deduplicated) |
| `~/.local/share/claude-brain/ingest.log` | — | Hook errors end up here |

**Backups:** the database is a single file. Snapshot it safely, even while it is in use:

```bash
sqlite3 ~/.local/share/claude-brain/brain.db ".backup '/path/to/backup/brain.db'"
```

Don't put the *live* database in a synced folder (Dropbox, Drive…) — sync can corrupt a SQLite
file mid-write. Back it up there instead.

---

## 🧪 Development

```bash
uv run pytest            # 56 tests, in-memory fixtures, < 1 s
```

```
brain/
  db.py        schema, connection, project naming rules
  ingest.py    incremental JSONL → SQLite archiver
  hook.py      what the hooks run: ingest, then sync; logs errors, never fails
  gitrepo.py   repo root + normalized remote of a folder, straight from .git files
  importer.py  claude.ai data export → sessions with origin claude-ai
  query.py     search / sessions / projects / digests — library + CLI
  sync.py      push to Neon (watermarks, redaction, offline-safe) — needs psycopg
  install.py   per-machine installer: skill, hooks, permission, backfill, first sync
remote/
  schema.sql   Postgres mirror, brain_* query functions, read-only role
  claude_ai_instructions.md   connector URL + claude.ai project instructions
skill/
  SKILL.md     the claude-brain skill template ({{BRAIN_QUERY}} filled in by install.py)
tests/         synthetic transcripts, temp databases
context.md     index for Claude: where each rule lives
```

The query layer is plain functions over a `sqlite3.Connection`, so the planned MCP server can
reuse it as is.

---

## ❓ FAQ

<details>
<summary><b>Do I have to open each project for it to be archived / synced?</b></summary>

No. The hooks live in your **user** settings (`~/.claude/settings.json`), so they run in every
project you open, and each run scans **all** of `~/.claude/projects/`, not just the current
project: whichever session triggers it, new messages from every project are archived and
pushed. Only what changed since the last run is read (~0.1 s). The installer's backfill is
global too.

Example — a computer with 5 projects:

- `install.py` archives and uploads the existing sessions of **all 5** right away, before you
  open Claude Code at all.
- Afterwards you work in project A while a session of project B is still running in another
  window: B's new messages go up with the next Claude reply, whether that reply is in A or in B.
  No project waits for you to open it.

</details>

<details>
<summary><b>What happens when I install it on another computer?</b></summary>

Running `python3 brain/install.py` there (with `NEON_URL` already in its `.env`):

1. archives every Claude Code session that computer still has, all projects, into its own
   local `brain.db`, and detects each session's git repo (the project folders must exist there;
   missing ones fall back to the folder name — re-check later with `ingest.py --full`);
2. downloads the aliases from Neon and relabels those sessions with them (`leai` or
   `leai-cli/src` → `devleaicli`);
3. uploads messages and sessions to Neon, already under the right project names;
4. installs the hooks, so from then on every reply there is archived and pushed.

In claude.ai, sessions from both computers then appear together under the same project. Keep in
mind:

- Only what that computer still has can be recovered: until the installer raises
  `cleanupPeriodDays`, Claude Code there was deleting sessions older than 30 days.
- Forgot the `.env`? Everything works locally; add it and re-run the installer to upload.
- Each machine's local `brain.db` holds only its own sessions — the union lives in Neon, so
  query claude.ai to see both. Local Claude Code searches see that machine only.
- The first sync takes seconds to a couple of minutes depending on volume; later ones only send
  what's new.

</details>

<details>
<summary><b>Does a session merge with "the same session" on another computer?</b></summary>

There is no such thing: Claude Code gives every conversation its own id on the machine where it
happens. What merges is the **project** — sessions from all computers that belong to the same
repo (same remote) or the same aliased folder end up under one project name.

</details>

## 🗺️ Roadmap

- [x] Incremental, idempotent archiver for all Claude Code surfaces
- [x] Full-text search, projects, sessions, lazy digests, aliases
- [x] Real-time archiving (async `Stop` hook)
- [x] Resume workflow (native `--resume` or from the archive)
- [x] **claude.ai access** — Neon mirror + official Neon MCP connector, read-only
- [ ] Save digests from claude.ai (write grant on `digests` only, pulled back to local)
- [x] **claude.ai importer** — the official data export (`conversations.json`) for non-Code chats
- [x] Importer validated against a real export (Oct 2026: 51 chats, 924 messages)
- [ ] Assign imported claude.ai chats to projects (the export has no chat→project link)
- [ ] Topics inside a project (`phdthesis → paperdownloader / writing / tooling`), assigned while summarizing
- [x] Installer (paths, skill, settings merge, backfill, first sync)
- [x] Several computers feeding one cloud mirror
- [x] Share aliases across machines through Neon
- [x] Windows support (exec-form hooks, both path styles) — awaiting a real-machine test
- [x] Git-aware projects: same remote = same project, on any machine and in any subfolder

## 📜 Changelog

### 0.6.1 — 2026-10-23
- Importer adapted to the real 2026 export: a manifest of per-category zips, projects as one file
  each; reads only `conversations*`/`projects*` zips from a folder, deduplicates zip + extracted
  copies, keeps document titles and the conversation `summary`, drops injected prompt blocks.

### 0.6.0 — 2026-10-23
- `brain/importer.py`: imports the claude.ai data export (zip, folder or `conversations.json`),
  idempotently; `--inspect` describes an export without importing. Chats in a claude.ai Project
  join the project of that name; others go to `claudeai`. New origin `claude-ai`.

### 0.5.0 — 2026-10-23
- Projects follow git: sessions store their repo (`sessions.repo`, normalized remote) and the
  repo's name becomes the default project, so subfolders and differently named clones merge.
- Aliases can target a git remote (any URL form); aliasing an existing repo path covers both its
  folder name and its remote. Remote credentials are never stored.
- `ingest.py --full` re-checks folders that previously looked like non-repos.

### 0.4.0 — 2026-10-23
- Aliases are keyed by **folder name** instead of absolute path (deepest matching folder wins),
  so they hold on every machine; old path aliases migrate automatically.
- Aliases sync both ways through Neon (`aliases` table, last write wins) and relabel sessions.
- Windows support: hooks call `brain/hook.py` in exec form (no shell), POSIX and Windows paths
  both understood, forward-slash paths in the skill and permission rule.

### 0.3.0 — 2026-10-23
- `brain/install.py`: one-command, idempotent installer (skill rendered with local paths,
  hooks + permission merged into settings.json with backup, backfill, first sync).
- Several computers can share one Neon mirror; remote digests keyed by `<hostname>:<id>`
  (schema auto-upgrades with `sync.py --init`).
- `CLAUDE_CONFIG_DIR` honored for transcripts and settings.
- README: who updates Neon, multi-computer setup.

### 0.2.1 — 2026-10-23
- `brain_reader` needs a password: the Neon connector logs in as that role (documented in `remote/`).
- claude.ai connector URL now adds `category=querying`: 5 SQL tools instead of ~46 Neon
  management tools, so "my projects" is answered from the archive, not with Neon projects.

### 0.2.0 — 2026-10-23
- Neon Postgres mirror: incremental push (`brain/sync.py`), offline-safe, secret redaction.
- `remote/schema.sql`: accent-insensitive FTS, `brain_*` SQL functions, read-only `brain_reader` role.
- claude.ai connector + project instructions to query the brain from web and mobile.

### 0.1.0 — 2026-10-23
- First release: archiver, query CLI, `claude-brain` skill, `Stop` + `SessionEnd` hooks.
- Projects from normalized folder names (leading year dropped), aliases for exceptions.
- Custom `/rename` titles take precedence over AI-generated ones.
- Compaction summaries and away-recaps stored as first-class `summary` messages.

---

## ⚠️ Limitations

- Only what Claude Code still had on disk when ClaudeBrain was installed can be backfilled;
  transcripts already removed by the 30-day cleanup are gone.
- Claude Desktop / claude.ai **chat** conversations (non-Code) only arrive when you import an
  export; there is no automatic capture for them.
- Tool outputs are truncated by design; the archive preserves the conversation, not every
  byte of every command output.
- Transcripts may contain secrets you pasted into a session. The local database keeps them
  as is; the cloud mirror gets a redacted copy, but redaction is pattern-based — an unusual
  secret format can slip through.
- From claude.ai the brain is read-only for now: summaries can only be saved from Claude Code.

## License

[MIT](LICENSE) © 2026 Andrey
