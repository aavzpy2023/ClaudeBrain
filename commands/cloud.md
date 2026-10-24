---
description: Optional — mirror the brain to your own Neon Postgres and query it from claude.ai (web, mobile)
allowed-tools: Bash(claude-brain *)
---

If `claude-brain` is not found (the plugin was installed during this session, before its folder joined the PATH), run `"${CLAUDE_PLUGIN_ROOT}/bin/claude-brain"` instead — same arguments.

Guide the user through ClaudeBrain's optional cloud mirror, one step at a time, confirming each
step worked before the next.

First explain it in a few sentences: the local database stays the source of truth; after every
reply the hook pushes new rows to the user's own Neon Postgres (free tier is enough), with
secrets redacted; claude.ai reads it through Neon's connector as a read-only role. Only their
computers write. Several computers feed the same database, and a second computer needs only
steps 2 and 3.

1. **Prerequisites.** Run `claude-brain status`: uv must be found (otherwise point to
   https://docs.astral.sh/uv/). If the cloud already shows as on, skip to step 3. Otherwise they
   need a Neon account and a project (a new, empty one; on a second computer, the same one).
2. **Credentials — the user does this, not you.** Ask them to open **their own terminal**
   (not this chat) and run the command printed by `claude-brain cloud connect` — run that
   command yourself first: it refuses to read input here and prints the exact line for their
   machine. It asks, with hidden input, for the connection string (Neon → Connect, owner role)
   and the project id (Neon → Settings → General), and saves them privately in
   `~/.config/claude-brain/.env`. Tell them never to paste the connection string into this
   chat: conversations are archived. Do not open or print that file yourself. Writing the
   `.env` by hand (`NEON_URL=…`, `NEON_PROJECT_ID=…`, `chmod 600`) works too.
3. `claude-brain cloud setup` — creates or upgrades the schema, gives the read-only role its
   password only if it has none (so an existing claude.ai connector never breaks), and uploads
   everything archived so far. Safe to re-run. Relay any `warning:` lines (e.g. a `.env` owned
   by root or readable by others) with the fix they print.
4. Only if setup said `next: claude-brain cloud instructions`: run it, show the output and walk
   them through adding the custom connector and the "Brain" project on claude.ai, exactly as
   printed. On a second computer setup says claude.ai needs nothing more — skip this.
5. Verify with `claude-brain cloud status` (schema current, this computer listed with a recent
   sync), then suggest asking, inside the claude.ai "Brain" project, "which projects do I have
   in my history?".

Never run `claude-brain cloud reader-password` unless the user asks to rotate the connector's
password: it breaks the claude.ai connector until they reconnect it.
