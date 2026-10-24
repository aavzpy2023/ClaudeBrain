---
description: Check ClaudeBrain and apply the recommended settings (transcript retention, no-prompt recall)
allowed-tools: Bash(claude-brain *)
---

If `claude-brain` is not found (the plugin was installed during this session, before its folder joined the PATH), run `"${CLAUDE_PLUGIN_ROOT}/bin/claude-brain"` instead — same arguments.

Check the user's ClaudeBrain install and offer the recommended settings.

1. Run `claude-brain status` and summarize it in a few lines: what is archived, from which
   sources, and whether the cloud mirror is on. Archiving needs no setup — it starts with the
   next reply and backfills the history Claude Code still has on disk.
2. Retention. If `cleanupPeriodDays` is unset or below 365, explain that Claude Code deletes
   transcripts after that many days (30 by default). The brain keeps its own copy of every
   conversation either way, but `claude --resume` of an old session needs the original. Offer
   to set it to 3650.
3. Permission. Offer to add `Bash(claude-brain *)` to `permissions.allow`, so recall never
   asks for approval (the skill only pre-approves it for the turn that invokes it).

Apply only what the user accepts, by editing `~/.claude/settings.json` (or
`$CLAUDE_CONFIG_DIR/settings.json`): read it first and merge — never drop or reorder other keys.
If the edit is refused, show the exact JSON to add so the user can do it.

Finish by mentioning, in one line, the optional cloud mirror: `/brain:cloud` lets them query
their history from claude.ai on the web and phone.
