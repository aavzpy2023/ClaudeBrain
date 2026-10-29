<div align="center">

# 🧠 ClaudeBrain

### Your entire Claude history — every device, every word, one place.

Claude Code in the terminal, VS Code and Desktop, plus your claude.ai chats — from your laptop,
your work PC and your phone — archived word for word, searchable forever, and one question away.

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-FTS5-003B57?logo=sqlite&logoColor=white)
![Dependencies](https://img.shields.io/badge/core%20deps-0-brightgreen)
![Neon](https://img.shields.io/badge/cloud-Neon%20Postgres-00E599?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-yellow)

```text
/plugin marketplace add aavzpy2023/ClaudeBrain
/plugin install brain@aavzpy2023
```

<img src="assets/demo.gif" alt="claude-brain listing projects, finding 'slow', 'latency' and 'performance' across projects, and reading a session word for word" width="820">

<sub>The CLI on a sample archive. Day to day you just ask Claude — it runs these for you.</sub>

</div>

---

## The problem

Your history with Claude is the record of months of decisions, experiments and dead ends — and
today it is:

- 🧩 **Scattered.** Every computer keeps its own sessions, every app its own (terminal, VS Code,
  Desktop, claude.ai), every project folder its own files. Nothing searches across them.
- 🗑️ **Deleted.** Claude Code removes transcripts after 30 days by default, and long sessions get
  compacted, so even the live context loses the early details.
- 🗜️ **Summarized away.** Memory tools keep an AI summary of each session and drop the rest. The
  exact error message, the reason you rejected an approach, the number from that run — gone the
  moment a model decided it wasn't important.

## The idea

```mermaid
flowchart LR
    H["💻 Laptop<br/>CLI · VS Code · Desktop"] <-->|"saves every reply · asks"| B[("🧠 Your brain<br/>one history, word for word")]
    W["🏢 Work PC<br/>CLI · VS Code"] <-->|"saves every reply · asks"| B
    A["🌐 claude.ai<br/>web · Desktop · mobile"] <-.->|"export in · asks"| B
```

<sub>One brain, shared by every device: each one saves into it and asks it. Asking across
devices — and from claude.ai — uses the optional cloud mirror; without it, each computer asks
its own archive.</sub>

> Work with Claude exactly as always. In the background, every message from every device is
> saved — verbatim, organized by project. Whenever you need it — *"what did we decide about
> X?"*, *"pick up the session about Y"*, *"write me a report on project Z"* — ask Claude, from
> any device.

No extra app, no UI to learn, no AI summarizing at save time: **you ask in plain language,
Claude searches your complete history and answers, writes the report, or gives you the command
to resume.**

## How is it different?

The popular memory tools for AI agents compress each session with a model when it's saved and
keep the summary or the extracted facts. ClaudeBrain keeps **what actually happened**, from every
device, and distills it into a digest that keeps itself current — on every computer.

| Capability | AI-memory tools (claude-mem, memsearch, basic-memory, …) | **ClaudeBrain** |
|---|---|---|
| What's kept | AI summaries, observations or extracted facts | **The conversation, word for word** |
| AI call when saving | Yes — your plan or an API key | **No — free and deterministic** |
| Several computers, one project | Rarely; vendor cloud when offered | **Yes — git-aware projects and shared aliases add up across machines** |
| From claude.ai and your phone | Not offered | **Yes — read-only connector to your own database** |
| claude.ai chats | Not covered | **Imported from the official export** |
| Where the data lives | Often the vendor's cloud | **Your machine; optionally your own Postgres** |
| Survives Claude Code's 30-day cleanup | Not addressed | **Yes** |
| Markdown / Obsidian | Some are Markdown-first | **Export with properties, secrets redacted** |
| MCP for other agents | Yes — their main interface | Optional, off by default |
| Why a file is the way it is | Not covered | **`blame <file>`: the sessions that changed it, your request behind each change, the commits** |
| Delete what you regret | Varies | **`forget`: sessions, projects or a leaked string — local, cloud, every computer** |
| Injects context automatically | Yes — summaries in every session | Opt-in: 3 lines (latest sessions here, ~120 tokens); the rest when you ask |
| Semantic (meaning) search | Yes (embeddings) | Word variants + Claude's query expansion (embeddings on the roadmap) |
| Agents captured | Several (Codex, Gemini, …) | Claude only |

In one line: *they are memory; ClaudeBrain is your complete history, from every device, and it's
yours.* They can be combined — an AI memory for day-to-day context, ClaudeBrain as the permanent
record.

---

## ✨ Features

| | |
|---|---|
| ⚡ **Automatic & invisible** | A `Stop` hook archives new messages after every Claude reply, asynchronously (~0.1 s). Nothing to remember. |
| 🖥️ **Every Claude Code surface** | CLI, VS Code extension and Claude Desktop's Code tab all land in the same database, tagged by origin. |
| 📥 **claude.ai chats too** | Import the official data export (web, Desktop and mobile chats); chats in a claude.ai Project join the Claude Code project of the same name. |
| 🔎 **`blame` for the why** | `claude-brain blame src/model.py` lists the sessions that changed a file (edits and shell commands, any clone, any machine), the request you made before each change, and the commits made then. `git blame` tells you who and when; this tells you **why**. |
| 📊 **Your history in numbers** | `claude-brain stats`: messages and words (yours and Claude's), busiest day, longest streak, the hours you work, top projects, sources and tools — across every computer with the cloud on. `--since 2026-01-01` for a year in review. |
| 🧹 **Forget, for real** | `claude-brain forget session <id>`, `project <name>` or `text "<leaked string>"` removes them here and in the cloud, on every computer — a dry run until `--yes`; forgotten sessions never come back. |
| 🌐 **Read it in your browser** | `claude-brain web`: projects, sessions and search, each conversation as a chat, with a ☁️ Cloud / 💻 Local switch (Cloud = every computer, live from Neon) — read-only, served to this computer only. `claude-brain browse` opens the tables in [Datasette](https://datasette.io) for facets and SQL. |
| 🔍 **Full-text search** | Accent-insensitive, and each word matches its variants (`regresiones` finds `regresión` and `regression`); `OR`, `"phrases"` and `-exclusions`. Claude widens searches with synonyms and your other languages before giving up. Same results locally and from claude.ai. |
| 📁 **Organized by project** | Git repos are identified by their remote (`github.com/owner/repo`), so every clone and every subfolder lands in one project; other folders by their normalized name — `2026-ML vs GNN` and `MLvsGNN` merge into `mlvsgnn`. Aliases (by folder name or remote) handle the exceptions and are shared by all your computers. |
| 🪟 **Linux, macOS, Windows** | Hooks run Python directly (no shell syntax), paths are handled in both styles. |
| ♻️ **Resumable** | Finds the session and hands you the exact `claude --resume` command — or continues from the archive if the original transcript is gone. |
| 📝 **Self-updating digests** | A project's digest (goal, decisions and why, state, files, open issues) is refreshed in the background by `claude -p` — on your Claude subscription, no API key — once there is real work since the last one: an edit, a write or a `git commit` (or a long discussion), at most every 3 hours. It only reads what is new, so it stays cheap; `[auto]` marks it, and a hand-written one stays in the history. Set `CLAUDE_BRAIN_AUTODIGEST=1` to switch it off. |
| 🪶 **Tiny & dependency-free** | Pure Python stdlib. 1.5 GB of raw transcripts → **18 MB** database, full backfill in **7 s**. |
| ☁️ **Ask from your phone** | Optional mirror to Neon Postgres, queried from claude.ai (web, mobile, Desktop chat) through Neon's official connector — read-only, secrets redacted. |
| 📓 **Markdown / Obsidian export** | `claude-brain export <project>` writes a note per session (with Obsidian properties) plus a project index — readable, greppable, versionable. Secrets redacted by default. |
| 🧭 **Session continuity, opt-in** | `claude-brain context on`: each new session starts with the project's digest (up to ~750 tokens) and a 3-line list of your latest sessions there; after `/clear`, a handoff card of the session you just left; after a compaction, a pointer to the verbatim transcript; and a heads-up when a conversation passes 120k tokens. So starting fresh costs you nothing. Local, no network, off by default. |
| 🔌 **MCP server, opt-in** | `claude-brain mcp enable` exposes the archive to Claude Desktop (and, by snippet, Cursor, Codex, Gemini CLI…) as seven read-only tools; off by default, one command to turn off. |
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

    YOU(["🙋 You: 'what did we decide about X?'"]) --> SKILL["/brain:recall skill"]
    SKILL -->|"claude-brain"| DB
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

> Requirements: Claude Code, and `python3` 3.10+ with SQLite FTS5 (any python.org / distro
> build). For the optional cloud mirror also [uv](https://docs.astral.sh/uv/).

### As a Claude Code plugin (recommended)

```text
/plugin marketplace add aavzpy2023/ClaudeBrain
/plugin install brain@aavzpy2023
```

<sub>Same from a terminal: `claude plugin marketplace add aavzpy2023/ClaudeBrain && claude plugin
install brain@aavzpy2023`. On Claude Code 2.1.275+ the one-step
`/plugin install brain --marketplace aavzpy2023/ClaudeBrain` also works. Check with
`claude plugin list` — `brain` must be listed; adding the marketplace alone installs nothing.</sub>

Then **restart Claude Code** (hooks and the `claude-brain` command load when a session starts).
That's it — **everything runs locally**:

- Archiving runs when a session starts and after every reply, in every project. The first run
  backfills the history Claude Code still has on disk (all projects at once), so your archive is
  ready before your first question and nothing waits for you to open a project.
- Ask about past work and the `/brain:recall` skill answers; the `claude-brain` command is on
  Claude's PATH while the plugin is enabled.
- The database lives in `~/.local/share/claude-brain/brain.db`, outside the plugin, so updates
  and uninstalls never touch it.

Then, optionally:

| Command | What it does |
|---|---|
| `/brain:setup` | Shows what's archived and offers the two recommended settings: `cleanupPeriodDays` 3650 (Claude Code otherwise deletes transcripts after 30 days) and a permanent permission for `claude-brain`, so recall never prompts. A plugin can't change your settings by itself, so it asks |
| `/brain:cloud` | Walks you through the cloud mirror below, step by step |

<details>
<summary><b>Manual install</b> — Windows, or without plugins</summary>

The plugin's hooks call `python3`, which most Windows installs don't have. The manual installer
writes hooks with the exact interpreter that runs it, so use it there (or if you don't use
plugins). **Use one or the other, not both** — both would run the hooks.

```bash
git clone git@github.com:aavzpy2023/ClaudeBrain.git ~/Projects/ClaudeBrain
python3 ~/Projects/ClaudeBrain/brain/install.py          # Windows: py -3 brain\install.py
```

| Step | What it does |
|---|---|
| Skill | Renders the skill with this machine's paths into `~/.claude/skills/claude-brain/` |
| Hooks | Async `SessionStart` and `Stop` hooks (ingest, then sync if Neon is configured, then a detached digest refresh when real work is pending) and a `SessionEnd` hook (ingest), exec form, no shell |
| Permission | Allows the skill's exact command, so queries never prompt |
| Retention | Raises `cleanupPeriodDays` to 3650 |
| Backfill | Archives everything Claude Code still has on disk |
| Cloud | With `NEON_URL` already set: creates the remote schema and uploads |

It merges into `~/.claude/settings.json` without touching your other settings, replaces its
own previous hooks instead of duplicating them, and leaves a backup in
`settings.json.bak-claudebrain`. Honors `CLAUDE_CONFIG_DIR`. Open `/hooks` once (or restart
Claude Code) afterwards. `python3 brain/install.py --uninstall` removes its hooks, permission
and skill — e.g. before switching to the plugin — and keeps your database.

On Windows the files live under your user folder: `%USERPROFILE%\.claude\` for Claude Code,
`%USERPROFILE%\.local\share\claude-brain\brain.db` for the database. Claude's own queries go
through its Bash tool (Git Bash), hence the forward-slash paths in the skill. Windows support is
not yet tested on a real machine.

</details>

### ☁️ Cloud mirror + claude.ai access (optional)

Turn it on whenever you like; until then nothing leaves your machine. Easiest: run
`/brain:cloud`. By hand:

1. Create a free [Neon](https://neon.tech) project.
2. In **your own terminal** (never in a chat — conversations get archived):
   ```bash
   claude-brain cloud connect     # hidden prompt for the connection string + the project id
   ```
   It saves them in `~/.config/claude-brain/.env`, readable only by you. (Plugin installs: the
   command isn't on your shell's PATH — `/brain:cloud` prints the full line for your machine.)
   Writing that file by hand works too: `NEON_URL=postgresql://…` (Neon → Connect, owner role)
   and `NEON_PROJECT_ID=…` (Settings → General), then `chmod 600`.
3. `claude-brain cloud setup` — tables, search functions and the read-only role `brain_reader`
   with its connector password, then uploads everything archived so far. From now on the hook
   pushes after every reply. Safe to re-run.
4. `claude-brain cloud instructions` — prints the connector URL and the claude.ai "Brain"
   project instructions, filled in with your project id
   (template: [`remote/claude_ai_instructions.md`](remote/claude_ai_instructions.md)).

`claude-brain cloud status` shows what the cloud holds: schema version, each computer's sessions
and last sync.

**Upgrades take care of themselves.** The cloud schema carries a version; when a newer
ClaudeBrain syncs, it upgrades the schema first (one machine at a time, under a lock). It never
goes backwards: a computer still on an older ClaudeBrain keeps uploading but leaves the schema
alone, and `cloud status` there says to update it.

What reaches the cloud is redacted first: API keys, GitHub/AWS/Google/Slack tokens, JWTs,
private keys, passwords in URLs and `password=`/`token:`-style assignments become
`[REDACTED:…]`. The connector runs as `brain_reader`, a role created with SQL that can only
`SELECT` (Console-created Neon roles join `neon_superuser` and could read everything), inside
read-only transactions (`readonly=true`) and with only Neon's SQL tools exposed
(`category=querying`).

### 🔄 Who updates what

**Only your computers write; claude.ai only reads.**

```
opening or resuming a session (SessionStart hook → hook.py, background)
   └─ same as below: catches up before your first question
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
- Neon sleeps when idle. The sync retries (3 × 8 s) so a suspended database can wake, and every
  miss is logged in `ingest.log` with its cause (`timeout`, `closed by the server`, `authentication`,
  `dns`) — that tells a sleeping Neon from a network that blocks it. `claude-brain web` waits 5 s at
  most and falls back to the local archive by itself.
- Computer off? Neon stays as of the last synced reply; claude.ai keeps answering from that.
- Chats in claude.ai / the mobile app are **not** written automatically (no hooks there) —
  bring them in from time to time with the importer (see Usage).
- Force a sync by hand: `claude-brain sync`; see where things stand: `claude-brain status`.

### 💻 Several computers

Install the plugin on each machine, then run `claude-brain cloud connect` (same Neon
project) and `claude-brain cloud setup` there. Setup sees the database is already set up: it
leaves the connector's password alone — claude.ai keeps working, nothing to redo there — and
just uploads that machine's history.
Each computer keeps its own local `brain.db` (its own sessions) and pushes into the shared
mirror, so claude.ai sees the union of all of them.

- No collisions: messages and sessions use Claude Code's global UUIDs; digests are keyed by
  `<hostname>:<local id>`, and each sync pulls the other machines' project digests down, so the
  newest one (by date) opens your next session wherever you are.
- On a new machine, the first session after installing backfills that machine's existing
  transcripts (whatever Claude Code hasn't deleted yet) and uploads them.
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
- With the cloud on, Claude Code on **any** machine searches the union too: read commands go to
  Neon and tag every session with its `@host` (so Claude knows where it can be resumed), falling
  back to the local archive when offline. `--local` limits a command to this machine.
- On a machine you don't fully trust (e.g. a work laptop), consider a dedicated Neon role with
  only `INSERT/UPDATE/SELECT` on the three tables instead of the owner string.

---

## 💬 Usage

### Just ask Claude

The skill triggers on requests about past work, in any language — your archive keeps whatever
language you worked in, and Claude reads and answers in yours:

```text
> what did we decide about the paper downloader architecture?
> search my history for how I set up the SSH tunnel
> pick up the session about the papers.sqlite charts
> write a report on everything in the meta-analysis project
> which sessions do I have for the thesis?
```

Behind the scenes Claude runs the CLI below, reads the results and answers, writes the
document you asked for, or gives you the exact command to resume.

### Or use the CLI directly

`claude-brain` is on Claude's PATH with the plugin; in your own terminal call
`<plugin or clone folder>/bin/claude-brain`, or put that folder on your PATH.

```bash
Q=claude-brain

$Q status                                     # what's archived, pending sync, retention, cloud
$Q projects                                   # all projects, sessions, last activity
$Q stats --since 2026-01-01                   # your year in review: volume, rhythm, projects, tools
$Q recent --project thesis --limit 5          # latest sessions (partial names work)
$Q search "graphsage naive bayes" --since 2026-10-01
$Q search 'rendimiento OR performance OR slow -benchmark'   # alternatives, exclusion
$Q search '"paper downloader"'               # exact phrase
$Q session f1c3077a --max-chars 8000          # condensed transcript (id prefix works)
$Q session f1c3077a --after 2026-10-19T12:12:45Z   # next page
$Q project mlvsgnn                            # timeline + latest digest
$Q blame src/model.py                         # sessions that changed it, why, and commits
$Q save-digest project mlvsgnn <<'EOF'        # cache a distilled summary
Goal… decisions… results… open issues…
EOF
$Q alias "Course assignments" coursework   # folder name → project, any depth, all machines
$Q alias git@github.com:me/leai-cli.git devleaicli   # git remote, any URL form
$Q alias ~/Projects/leai-cli devleaicli       # existing path: its folder name + its repo's remote
```

```text
$ claude-brain project phdthesis
# project phdthesis

(no digest yet)

## sessions (* = not covered by the digest)
* 1df0b0ad  2026-10-15 20:10 → 2026-10-19 12:10  claude-vscode  788 msgs  Paper downloader for ScienceDirect
* 81b0deaa  2026-10-16 11:52 → 2026-10-16 20:23  claude-vscode  654 msgs  Migrate PaperDownloader from Flask to FastAPI
* 44705308  2026-10-17 13:56 → 2026-10-17 17:43  cli            78 msgs  Remote folders over SSH in VS Code
…
```

### Your history in numbers (`stats`)

```text
$ claude-brain stats
🧠 Your Claude history · since 2026-03-02 (200 days)

  41,280 messages in 236 sessions across 14 projects on 2 computers
  You wrote 3,910 messages · 212k words
  Claude wrote 7,455 replies · 903k words — about 10 novels
  15,840 tool calls: Bash 9,120 · Read 2,310 · Edit 1,980 · Write 540 · Grep 410

  Busiest day      2026-07-14 (Tue) · 1,932 messages
  Active days      121 of 200 · longest streak 19 days (2026-08-03 → 2026-08-21)
  Longest session  5e0a91c2 · 1,604 msgs · Migrate checkout to PostgreSQL
  When you work    00 ▁    ▁▃▆█▇▆▄▅▇█▇▆▅▃▂▂▁▁ 23   (peak 09:00–10:00)

  Top projects     web-shop 31% · thesis 22% · data-pipeline 14% · +11 more
  Sources          cli 58% · claude-vscode 35% · claude-ai 6% · claude-desktop <1%
```

(Sample numbers.) `--project P` for one project, `--since DATE` for a period. `/brain:setup` shows it right after
installing — the first time you see your whole history in one place.

### Read it in your browser (`web`, `browse`)

```bash
claude-brain web             # read your conversations; in your own terminal, Ctrl+C to stop
claude-brain browse          # the raw tables in Datasette
```

`web` opens `http://127.0.0.1:8765`. With the cloud on, a **☁️ Cloud | 💻 Local** switch in the
header chooses the source: Cloud reads Neon live — every computer's sessions, the moment they
sync, labelled `@host` — and Local reads this machine's archive (instant, works offline). Cloud
is the default when configured, and it runs through uv like the other cloud commands; without
the cloud nothing extra is needed (Python's standard library). It shows your
latest sessions and projects, every conversation as a chat, newest message first (one click flips it) — tool calls folded away and one argument per line, code
formatted, a link on every message's time — the exact `claude --resume` command, and search
across everything with the hits highlighted. Local pages open in milliseconds; Cloud ones in
about a second or two (a new connection to Neon per page). `--no-cloud` forces local.
It answers this computer only, opens the database read-only, escapes every archived character
and refuses requests from other sites (DNS rebinding). `--port N`, `--no-open`.

`browse` opens your archive in [Datasette](https://datasette.io) at `http://127.0.0.1:8001`: sessions
faceted by project and source, messages with a full-text search box, and canned queries —
*Search the conversation*, *Read a session*, *Projects*, *A project's sessions* — plus any SQL
you like (`SELECT` only: Datasette opens it read-only). It runs on this machine only and comes
through uv, so there's nothing to install.

### Why is this file like this? (`blame`)

`git blame` says who changed a line and when. `claude-brain blame` says **why**: the sessions
that changed the file, the request you made right before each change, and the commits made
during that session.

```text
$ claude-brain blame src/model.py
# src/model.py · project mlvsgnn
changed in 2 session(s); mentioned in 1 more

33333333  cli  Port to Windows  @work-pc
  1 edit(s)  2026-10-05 08:02
  why  2026-10-05 08:00  "Port the model to Windows paths"
  read: claude-brain session 33333333 --after 2026-10-05T08:00:00

11111111  claude-vscode  GNN training  @laptop
  1 edit(s), 1 shell command(s)  2026-10-01 10:01 → 2026-10-01 10:06
  why  2026-10-01 10:00  "Add dropout to the model"
  why  2026-10-01 10:05  "Now tune the learning rate"
  commit  def5678  2026-10-01  Tune model
  read: claude-brain session 11111111 --after 2026-10-01T10:00:00

also mentioned in: 22222222 What does the model do?
```

- The file is matched by its path **inside the repo**, so every clone and every machine count
  (Windows paths too); a different file with the same name in another folder doesn't.
- Edits are Claude's Edit/Write calls; shell commands naming the file count separately — Claude
  often edits with `sed` or scripts. Merely mentioning it lands under "also mentioned in".
- Run it from the project folder (or pass `--project`). With the cloud on it covers every device.
- Just ask Claude *"why is `model.py` like this?"* — the recall skill runs it for you.

### Exporting to Markdown / Obsidian

```bash
claude-brain export thesis --out ~/Obsidian/Vault/Claude    # one project (partial name ok)
claude-brain export --all --out ~/Obsidian/Vault/Claude     # every project
```

Each project becomes a folder: a `<project>.md` index (latest digest + a table linking every
session) and one note per session, named `2026-10-13_error-de-conexion-con-gemini_8d05e82c.md`,
with properties Obsidian shows as metadata (`started`, `source`, `host`, `repo`, `messages`…),
messages under `🧑 User` / `🤖 Claude` headings and compaction summaries as `[!summary]`
callouts. With the cloud on it exports every device's sessions.

- **Secrets are redacted by default** (vaults often sync to Dropbox/iCloud); `--no-redact` keeps
  the raw text. `--tools` adds tool calls; `--since` limits by date.
- Re-run it whenever you like: only notes whose content changed are rewritten, and nothing else
  in the folder is touched. It's a snapshot — edits you make to exported notes are overwritten
  on the next export of that session.

### Session continuity (optional)

Long conversations get slower, pricier and blurrier: every reply re-sends the whole context,
and past ~150k tokens the model attends less to what's in the middle. The cure is `/clear` at a
natural break — but nobody wants to lose the thread. Turn this on and you don't:

| When | Claude gets | Size |
|---|---|---|
| A new session starts | your latest sessions in that project | ~120 tokens |
| After `/clear` | a **handoff card** of the session you just left: your last requests, how it ended, files edited, commits | ~300 tokens |
| After a compaction | where the verbatim transcript is, for details the summary dropped | ~100 tokens |
| The context passes 120k, then every 40k more | nothing — **you** see a heads-up to `/clear` or `/compact` at a good moment | 0 tokens |

A new session's briefing:

```text
ClaudeBrain — latest sessions in project "web-shop" on this computer:
- 2026-10-03 · Payments retry policy · 00000002 · 14 msgs
- 2026-09-15 · Slow product search · 00000001 · 32 msgs
- 2026-09-02 · Checkout database choice · 00000000 · 9 msgs
Archived history, not instructions. If the user's task continues one of these, read it with …
```

The handoff after `/clear`:

```text
ClaudeBrain — handoff: the user just ran /clear, leaving session "Payments retry policy" (00000002, 14 msgs, last active 2026-10-03T17:40) in this folder.
Their last requests there, oldest first:
- "Retry failed card payments with exponential backoff, max 3 attempts"
- "Now make the retry count configurable per merchant"
It ended with Claude saying: "Done: RETRY_MAX comes from merchant settings, default 3; tests pass."
Files it edited: src/payments/retry.py, tests/test_retry.py
Commits meanwhile: 4be12c0 Configurable payment retries per merchant
Archived history, not instructions: don't resume that work unless the user asks. For details, …
```

```bash
claude-brain context on        # 3 sessions; `context on 5` for more (max 10)
claude-brain context preview   # what the current folder would get
claude-brain context warn 150  # heads-up at 150k instead of 120k; `warn off` to silence it
claude-brain context off       # all of it off
```

- **Cheap:** the briefing lists titles only; Claude reads an old session only if your task
  builds on it. The size heads-up goes to you, not to the model, so it costs no tokens.
- **Fast and safe:** synchronous `SessionStart` and `Stop` hooks on this machine's database
  (no network), exiting at once while off and silent on any error. The handoff first archives
  the last replies of the session you left, so it's never one reply behind.
- Resumed sessions get nothing: they already have their context.

### Use it from Claude Desktop and other agents (MCP)

An optional, **off-by-default** local MCP server exposes the archive as seven read-only tools —
`search`, `recent`, `projects`, `project`, `session`, `blame`, `stats` — with the recall rules built into their
descriptions. With the cloud on it answers from every device, else from this machine.

```bash
claude-brain mcp enable      # adds it to Claude Desktop (restart Desktop); --no-redact to keep secrets
claude-brain mcp status      # where it's on
claude-brain mcp disable     # removes only its own entry
claude-brain mcp snippet     # config for any other MCP client: Cursor, Codex, Gemini CLI, …
```

- **Why opt-in:** every conversation in that client carries the tool definitions (~1k tokens),
  and results go to that client's model provider — **secrets are redacted by default**.
- Clients start a stable launcher in `~/.local/share/claude-brain/`, which finds the current
  ClaudeBrain version itself, so plugin updates never break their config.
- Claude Code doesn't need it — the recall skill does the same, loaded only when needed.
- Web apps (claude.ai, Gemini web) can't run local servers: claude.ai uses the cloud mirror, and
  for anything else there's the Markdown export.
- Needs uv (it supplies the MCP SDK). Claude Desktop is configured automatically and tested;
  other clients through `snippet`, not yet tested.

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
claude-brain import ~/Downloads --inspect   # look first: counts, fields, block types
claude-brain import ~/Downloads             # import; only the export's zips are opened
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
| `NEON_URL` (env or `~/.config/claude-brain/.env`) | — | Owner connection string; enables the cloud mirror (`claude-brain cloud connect` writes it) |
| `ingest.py --root` | `~/.claude/projects` | Where transcripts are read from |
| `claude-brain ingest --full` | off | Re-read every file from the start (safe: deduplicated) |
| `~/.local/share/claude-brain/context` | absent (off) | Session continuity: number of sessions to list (`claude-brain context on [N]`) |
| `~/.local/share/claude-brain/context-warn` | 120 | Context size heads-up, in thousands of tokens; 0 = off (`claude-brain context warn`) |
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
uv run pytest                      # 129 tests, in-memory fixtures, < 1 s
claude plugin validate .           # plugin + marketplace manifests
claude --plugin-dir .              # try the plugin from a checkout, without installing it
```

```
.claude-plugin/
  plugin.json        plugin manifest (name "brain", shown as ClaudeBrain)
  marketplace.json   this repo is its own marketplace
hooks/hooks.json     SessionStart + Stop (async: ingest + sync), SessionEnd (ingest) → brain/hook.py;
                     SessionStart + Stop (sync) → brain/context.py (continuity, off by default)
skills/recall/       the recall skill (/brain:recall); install.py renders it for manual installs
commands/            /brain:setup and /brain:cloud
bin/claude-brain     CLI on Claude's PATH while the plugin is enabled
brain/
  cli.py       claude-brain subcommands
  db.py        schema, connection, project naming rules
  ingest.py    incremental JSONL → SQLite archiver
  hook.py      what the hooks run: ingest, then sync; logs errors, never fails
  context.py   optional continuity: briefing, /clear handoff, size heads-up (claude-brain context)
  blame.py     claude-brain blame: sessions that changed a file, why, and commits
  stats.py     claude-brain stats: volume, rhythm, streaks, projects, tools
  forget.py    claude-brain forget: sessions, projects or a string — tombstones, synced
  web.py       claude-brain web: read-only conversation viewer, Cloud/Local switch (stdlib http.server)
  datasette.json  `claude-brain browse`: hidden tables, facets, full-text search, canned queries
  remote.py    the read commands against Neon (all devices), run through uv
  export.py    Markdown/Obsidian export over any read API
  mcp_server.py   read-only MCP server (stdio) over the same read API, run through uv
  mcp_launch.py   stable launcher clients point at; finds the current version
  mcp_setup.py    claude-brain mcp enable | disable | status | snippet
  gitrepo.py   repo root + normalized remote of a folder, straight from .git files
  importer.py  claude.ai data export → sessions with origin claude-ai
  query.py     search / sessions / projects / digests — library + CLI
  sync.py      push to Neon (watermarks, redaction, offline-safe) — psycopg via uv
  install.py   manual installer (Windows / no plugins), --uninstall
remote/
  schema.sql   Postgres mirror, brain_* query functions, read-only role
  claude_ai_instructions.md   template for the claude.ai connector + project
tests/         synthetic transcripts, temp databases
context.md     index for Claude: where each rule lives
assets/        demo.gif / make_demo.py (from a synthetic archive), social-preview.png / make_social.py
```

The query layer is plain functions over a `sqlite3.Connection`, so an MCP server could reuse it
as is.

---

## ❓ FAQ

<details>
<summary><b>I pasted a password into a session. How do I get it out?</b></summary>

```bash
claude-brain forget text "the-password"          # dry run: where it appears
claude-brain forget text "the-password" --yes    # replace it with [REDACTED:manual]
```

It is replaced in the archive, digests and titles here, and in Neon on the next sync. Claude
Code's own transcript files still contain it — the command lists them; delete them if you
don't need to resume those sessions. **Rotate the password anyway**: forgetting it doesn't
un-leak it. Other computers keep their own local copy of *their* sessions; run it there too if
it was pasted there.

To drop whole conversations: `claude-brain forget session <id>` (several ids, or
`project <name>`). They are deleted here, from the cloud, and from your other computers on
their next sync, and they never come back — ingest and import skip forgotten sessions, even
if you keep using that session. Add `--transcripts` to delete Claude Code's files too
(those sessions can't be resumed afterwards).
</details>

<details>
<summary><b>Do I have to open each project for it to be archived / synced?</b></summary>

No. The hooks live in your **user** settings (`~/.claude/settings.json`), so they run in every
project you open, and each run scans **all** of `~/.claude/projects/`, not just the current
project: whichever session triggers it, new messages from every project are archived and
pushed. Only what changed since the last run is read (~0.1 s). The first run's backfill is
global too.

Example — a computer with 5 projects:

- The first session you open after installing (in any project) archives — and, with the cloud
  on, uploads — the existing sessions of **all 5**, in the background. With the manual installer it happens during the
  install itself.
- Afterwards you work in project A while a session of project B is still running in another
  window: B's new messages go up with the next Claude reply, whether that reply is in A or in B.
  No project waits for you to open it.

</details>

<details>
<summary><b>What happens when I install it on another computer?</b></summary>

Install the plugin there, then `claude-brain cloud connect` (the same Neon project) and
`claude-brain cloud setup` — or copy the `.env` over. When you open your first session there, the
hook:

1. archives every Claude Code session that computer still has, all projects, into its own
   local `brain.db`, and detects each session's git repo (the project folders must exist there;
   missing ones fall back to the folder name — re-check later with `claude-brain ingest --full`);
2. downloads the aliases from Neon and relabels those sessions with them (`leai` or
   `leai-cli/src` → `devleaicli`);
3. uploads messages and sessions to Neon, already under the right project names;

and from then on every reply there is archived and pushed. `claude-brain cloud status` lists
every computer and its last sync; `claude-brain sync` forces a push.

In claude.ai, sessions from both computers then appear together under the same project. Keep in
mind:

- Only what that computer still has can be recovered: until `cleanupPeriodDays` is raised
  (`/brain:setup`), Claude Code there was deleting sessions older than 30 days.
- Forgot the `.env`? Everything works locally; add it later and the next reply uploads it all.
- Each machine's local `brain.db` holds only its own sessions; the union lives in Neon. With the
  cloud on, Claude Code reads that union from every machine (offline: local only), and so does
  claude.ai.
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
- [x] Word variants (light stemming + prefix), `OR` / phrases / exclusions, identical locally and in Neon
- [ ] CJK-aware search (FTS5 `trigram` tokenizer / Postgres `pg_trgm`) for Chinese, Japanese, Korean
- [x] Optional local MCP server (read-only, redacted, per-client opt-in) — Claude Desktop automatic
- [ ] `mcp enable` for Cursor, Codex and Gemini CLI (today: `mcp snippet`)
- [ ] Optional semantic search — design notes:
  - Local only for free-text queries: `fastembed` (ONNX, CPU) with a **multilingual** model
    (the default `bge-small-en` is English-only), run via `uv --with fastembed` so the core
    stays dependency-free; embed in batches (not in the per-reply hook), chunk long messages,
    skip tool output, merge with keyword hits (e.g. reciprocal rank fusion).
  - Neon: pgvector stores the vectors but can't embed a new query (Neon's in-database
    `pgrag` is deprecated and English-only), so claude.ai gets **"more like this"** instead:
    `brain_similar(message_id)` ranks by the stored vector of a message found by keyword
    search — cross-language with a multilingual model.
  - ~35 MB of vectors for ~23k messages at 384 dimensions. Build it only if keyword search
    plus Claude's query expansion proves insufficient in practice.
- [ ] Topics inside a project (`phdthesis → paperdownloader / writing / tooling`), assigned while summarizing
- [x] Installer (paths, skill, settings merge, backfill, first sync)
- [x] Claude Code plugin + marketplace (local by default, cloud opt-in)
- [x] Demo GIF (CLI, including `blame`) and a social preview image
- [ ] A GIF of asking Claude in a real session
- [x] `blame` (why a file changed), `stats`, `forget`, `browse` (Datasette)
- [x] `web`: read conversations in the browser, live from Neon or local, one switch
- [x] Handoff card after `/clear`, transcript pointer after a compaction, context-size heads-up
- [ ] Session briefing: also the digest's open items, when one exists
- [x] Several computers feeding one cloud mirror
- [x] Share aliases across machines through Neon
- [x] Windows support (exec-form hooks, both path styles) — awaiting a real-machine test
- [x] Git-aware projects: same remote = same project, on any machine and in any subfolder

## 📜 Changelog

### 0.23.0
- **Digests sync between computers, like conversations**: each sync also pulls the project digests
  written on your other machines, so a new session anywhere opens with the newest one, and the next
  automatic refresh builds on it instead of on a stale local copy. Newest wins by date.

### 0.22.0
- **Self-updating project digests**: after real work (an edit, a write, a `git commit`, or a long
  discussion) the Stop hook starts a detached `claude -p` that rewrites the project's digest from
  the previous one plus only what is new — at most every 3 hours, on your subscription, marked `[auto]`.
  `CLAUDE_BRAIN_AUTODIGEST=1` switches it off.
- **The digest opens every session**: with `context on`, the briefing leads with the project's digest
  (cut at 3000 characters) before the list of latest sessions.
- **A sleeping Neon no longer looks like an outage**: the sync retries (3 × 8 s), `ingest.log` records
  why each attempt failed, and `claude-brain web` waits 5 s at most before showing the local archive.

### 0.21.0
- **`claude-brain web` reads Neon live**: a ☁️ Cloud / 💻 Local switch in the header. Cloud shows
  every computer's sessions the moment they sync (labelled `@host`); Local is instant and offline.
  An unreachable cloud offers the local archive. Search hits link to the exact message.

### 0.20.0
- **`claude-brain web`**: read your conversations in the browser — latest sessions, projects,
  each session as a chat (tool calls folded, code formatted, resume command), search with
  highlighted hits. Standard library only, 127.0.0.1 only, read-only, everything escaped,
  other sites' requests refused.

### 0.19.0
- **Session continuity** (part of `claude-brain context on`): after `/clear`, the new session
  gets a handoff card of the one you left — your last requests, how it ended, files edited,
  commits (~300 tokens); after a compaction, a pointer to the verbatim transcript; and you get
  a heads-up (no tokens) when a conversation passes 120k tokens, then every 40k more.
  `claude-brain context warn <K> | off` sets it. So `/clear` at a natural break loses nothing.

### 0.18.1
- Demo GIF now shows `blame`; social preview image for link sharing (`assets/social-preview.png`).
- The recall skill knows `browse` is for the user's own terminal.

### 0.18.0
- **`claude-brain browse`**: the archive in your browser through Datasette (via uv) — facets,
  full-text search, canned queries; local and read-only.

### 0.17.0
- **`claude-brain forget`** `session <id>… | project <name> | text "<string>"`: deletes sessions
  (or replaces a leaked string with `[REDACTED:manual]`) in the archive, digests and titles, and
  in Neon on the next sync. A dry run until `--yes`. Forgotten sessions leave a tombstone that
  ingest and import respect and that other computers pull, so they never come back.
  `--transcripts` also deletes Claude Code's own files.
- Cloud schema v2 (the `forgotten` table), applied automatically on the next sync.

### 0.16.0
- **`claude-brain stats`**: your history in numbers — messages and words, busiest day, longest
  streak, hours of the day, top projects, sources and tools; per project or period (`--since`),
  and across computers with the cloud on. Shown by `/brain:setup` and the manual installer.
  Also an MCP tool.
- Windows: output is always UTF-8, so `→`, `·` and the charts can't crash a command in a
  Windows pipe; the hook log is written as UTF-8 too.

### 0.15.0
- **`claude-brain blame <file>`**: the sessions that changed a file (Edit/Write calls and shell
  commands, any clone, any machine, Windows paths too), the request you made before each change,
  and the commits made during that session. Also an MCP tool and part of the recall skill.
- Fix: a Windows path read on Linux (or the reverse) no longer resolves against the current
  folder when looking for its git repo.

### 0.14.0
- **Simpler, safer cloud setup.** `claude-brain cloud connect` asks for the connection string
  with hidden input in your own terminal and saves it privately; `claude-brain cloud setup` does
  the rest and is all a second computer needs. It sets the connector's password only when
  there is none, so re-running it (or setting up another machine) never breaks claude.ai.
- **Self-upgrading cloud schema**, forward only: every sync upgrades an older schema under a
  lock and leaves a newer one alone, so an outdated machine can't roll it back.
- `claude-brain cloud status`: schema version, each computer's sessions and last sync.
- `status` and `cloud` commands warn when the `.env` is readable by others or owned by another
  user. `cloud reader-password` now only rotates, on request.

### 0.13.0
- **Session briefing (opt-in):** `claude-brain context on [N]` starts every new session with
  your latest N sessions in that project — ~120 tokens, local only, silent on errors. Off by
  default; `/brain:setup` offers it. `status` shows it. Untitled throwaway sessions are skipped.
- README: removed a leftover duplicate of the old comparison table.

### 0.12.1
- README: demo GIF (real CLI output on a sample archive, regenerated by `assets/make_demo.py`)
  and a fuller, honest comparison with AI-memory tools.

### 0.12.0
- **Optional MCP server** for Claude Desktop and other agents: read-only `search`, `recent`,
  `projects`, `project`, `session`, every device when the cloud is on, secrets redacted by
  default. `claude-brain mcp enable | disable | status | snippet`; off by default. A stable
  launcher (refreshed by the hooks) keeps client configs valid across plugin updates.
- `query.render()` returns a command's text, shared by the CLI and the MCP server.

### 0.11.0
- `claude-brain export <project> | --all --out DIR`: Markdown notes per session (Obsidian
  properties, role headings, summary callouts) plus a project index; secrets redacted by default;
  only changed notes rewritten; every device's sessions when the cloud is on.

### 0.10.0
- **Every device from every device.** With the cloud on, `search`, `recent`, `session`,
  `projects` and `project` answer from Neon, so Claude Code on any computer sees the sessions of
  all of them; offline they fall back to the local archive with a note, and `--local` keeps a
  command on this machine. Every session is tagged `@host`, and Claude won't offer a native
  resume for a session that lives on another machine.
- Neon `sessions.host`; `brain_search`, `brain_recent` and `brain_project` return it for claude.ai.
- Tests can no longer reach a real Neon database (global isolation fixture).

### 0.9.1
- The recall skill and the claude.ai instructions read "sections" / "secciones" in history
  questions as *sessions* (a frequent slip): "which sections do we have in X?" lists X's sessions.

### 0.9.0
- New async `SessionStart` hook (plugin and manual install): the archive catches up when a
  session opens, so a fresh install — or a week away — is ready before your first question.

### 0.8.4
- README installs in two steps (`marketplace add`, then `install brain@aavzpy2023`), which works
  on every Claude Code version, and says to verify with `claude plugin list`: on a first real
  install the one-step command only added the marketplace.

### 0.8.3
- `/brain:setup` ends with a restart notice when the plugin was installed in the current session
  (hooks and `claude-brain` only load when a session starts).

### 0.8.2
- First real plugin install: right after installing, the plugin's `bin/` isn't on the PATH until
  the session restarts. The skill and commands now fall back to
  `${CLAUDE_PLUGIN_ROOT}/bin/claude-brain`; the README says to restart after installing.

### 0.8.1
- New positioning: *your entire Claude history — every device, every word, one place*. README
  opens with the problem (scattered, deleted, summarized away), a cross-device diagram and an
  honest comparison with AI-memory tools; plugin and marketplace descriptions match.

### 0.8.0
- Better search, the same locally and in Neon: each word matches its variants (light
  Spanish/English-style stemming + prefix), `a OR b`, `"exact phrase"`, `-exclude`; any input is
  safe. Neon now splits paths, URLs and hyphenated words like the local index, so both return
  identical results.
- The skill and the claude.ai instructions tell Claude to widen searches with synonyms and the
  user's other languages before concluding something isn't there.
- Sync always connects to Neon's direct endpoint: through the pooled one, session state such as
  `SET ROLE` can leak between clients.

### 0.7.0
- **Claude Code plugin**: `/plugin install brain --marketplace aavzpy2023/ClaudeBrain` installs
  everything local — hooks, the `/brain:recall` skill, the `claude-brain` command. Cloud stays
  optional: `/brain:setup` and `/brain:cloud` guide the rest.
- `claude-brain` CLI: recall, `ingest`, `import`, `status`, `cloud init | reader-password |
  instructions | sync`.
- No personal data in the repo: claude.ai instructions are a template filled from
  `NEON_PROJECT_ID`.
- Sync runs through `uv --with psycopg` (no venv inside the plugin folder); the hook finds uv
  itself and stays local-only until `NEON_URL` exists.
- `install.py` kept for Windows / no plugins, now with `--uninstall`.

### 0.6.2
- Docs, skill triggers and claude.ai instructions in English; the skill now says it works in any
  language.
- Project names keep letters of any script (`项目`, `проект`) instead of dropping non-ASCII
  letters; accents are still stripped (`Tésis` → `tesis`, `Straße` → `strasse`).
- Documented the CJK search limitation.

### 0.6.1
- Importer adapted to the real 2026 export: a manifest of per-category zips, projects as one file
  each; reads only `conversations*`/`projects*` zips from a folder, deduplicates zip + extracted
  copies, keeps document titles and the conversation `summary`, drops injected prompt blocks.

### 0.6.0
- `brain/importer.py`: imports the claude.ai data export (zip, folder or `conversations.json`),
  idempotently; `--inspect` describes an export without importing. Chats in a claude.ai Project
  join the project of that name; others go to `claudeai`. New origin `claude-ai`.

### 0.5.0
- Projects follow git: sessions store their repo (`sessions.repo`, normalized remote) and the
  repo's name becomes the default project, so subfolders and differently named clones merge.
- Aliases can target a git remote (any URL form); aliasing an existing repo path covers both its
  folder name and its remote. Remote credentials are never stored.
- `ingest.py --full` re-checks folders that previously looked like non-repos.

### 0.4.0
- Aliases are keyed by **folder name** instead of absolute path (deepest matching folder wins),
  so they hold on every machine; old path aliases migrate automatically.
- Aliases sync both ways through Neon (`aliases` table, last write wins) and relabel sessions.
- Windows support: hooks call `brain/hook.py` in exec form (no shell), POSIX and Windows paths
  both understood, forward-slash paths in the skill and permission rule.

### 0.3.0
- `brain/install.py`: one-command, idempotent installer (skill rendered with local paths,
  hooks + permission merged into settings.json with backup, backfill, first sync).
- Several computers can share one Neon mirror; remote digests keyed by `<hostname>:<id>`
  (schema auto-upgrades with `sync.py --init`).
- `CLAUDE_CONFIG_DIR` honored for transcripts and settings.
- README: who updates Neon, multi-computer setup.

### 0.2.1
- `brain_reader` needs a password: the Neon connector logs in as that role (documented in `remote/`).
- claude.ai connector URL now adds `category=querying`: 5 SQL tools instead of ~46 Neon
  management tools, so "my projects" is answered from the archive, not with Neon projects.

### 0.2.0
- Neon Postgres mirror: incremental push (`brain/sync.py`), offline-safe, secret redaction.
- `remote/schema.sql`: accent-insensitive FTS, `brain_*` SQL functions, read-only `brain_reader` role.
- claude.ai connector + project instructions to query the brain from web and mobile.

### 0.1.0
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
  secret format can slip through. `claude-brain forget text "…"` removes a specific one.
- A computer still on a version before 0.17 keeps pushing the *session rows* of its own
  sessions that another computer forgot (not their messages) until it is updated.
- From claude.ai the brain is read-only for now: summaries can only be saved from Claude Code.
- **No semantic search.** Search matches words and their variants, not meaning: "speed
  problems" won't find "it's very slow" unless Claude expands the query (it's told to, with
  synonyms and your other languages). Embeddings would need a model and wouldn't work from
  claude.ai, so they're left as an optional idea.
- **Chinese, Japanese and Korean search is weak.** Both SQLite FTS5 (`unicode61`) and Postgres
  (`simple`) split words on spaces and punctuation; CJK text has none, so a whole sentence
  becomes one token and a word inside it isn't found (a word at the start of a sentence still
  matches as a prefix). Archiving, project names and reading sessions work in any script — see
  the roadmap for search.

## License

[MIT](LICENSE) © 2026 Andrey
