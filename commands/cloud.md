---
description: Optional — mirror the brain to your own Neon Postgres and query it from claude.ai (web, mobile)
allowed-tools: Bash(claude-brain *)
---

Guide the user through ClaudeBrain's optional cloud mirror, one step at a time, confirming each
step worked before the next.

First explain it in a few sentences: the local database stays the source of truth; after every
reply the hook pushes new rows to the user's own Neon Postgres (free tier is enough), with
secrets redacted; claude.ai reads it through Neon's connector as a read-only role. Only their
computers write. Several computers can feed the same database.

1. **Prerequisites.** Run `claude-brain status`: uv must be found (otherwise point to
   https://docs.astral.sh/uv/). They need a Neon account and a new, empty project.
2. **Credentials — the user does this, not you.** They create
   `~/.config/claude-brain/.env` containing
   `NEON_URL=<owner connection string, from Neon → Connect>` and
   `NEON_PROJECT_ID=<project id, from Neon → Settings → General>`, then `chmod 600` it.
   Tell them never to paste the connection string into this chat: conversations are archived.
   Do not open or print that file yourself.
3. `claude-brain cloud init` — creates tables, search functions and the read-only role, and
   uploads everything archived so far.
4. `claude-brain cloud reader-password` — the connector logs in as the read-only role.
5. `claude-brain cloud instructions` — show the output and walk them through adding the
   custom connector and the "Brain" project on claude.ai, exactly as printed.
6. Verify with `claude-brain status` (cloud on, nothing pending), then suggest asking, inside
   the claude.ai "Brain" project, "which projects do I have in my history?".
