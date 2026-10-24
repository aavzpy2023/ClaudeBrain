---
description: Check ClaudeBrain and apply the recommended settings (transcript retention, no-prompt recall)
allowed-tools: Bash(claude-brain *)
---

If `claude-brain` is not found (the plugin was installed during this session, before its folder joined the PATH), run `"${CLAUDE_PLUGIN_ROOT}/bin/claude-brain"` instead — same arguments.

Check the user's ClaudeBrain install and offer the recommended settings.

1. Run `claude-brain status` and summarize it in a few lines: what is archived, from which
   sources, and whether the cloud mirror is on. Archiving needs no setup — it runs when a
   session starts and after every reply, and backfills the history Claude Code still has on disk.
2. Retention. If `cleanupPeriodDays` is unset or below 365, explain that Claude Code deletes
   transcripts after that many days (30 by default). The brain keeps its own copy of every
   conversation either way, but `claude --resume` of an old session needs the original. Offer
   to set it to 3650.
3. Permission. Offer to add `Bash(claude-brain *)` to `permissions.allow`, so recall never
   asks for approval (the skill only pre-approves it for the turn that invokes it).

Apply only what the user accepts, by editing `~/.claude/settings.json` (or
`$CLAUDE_CONFIG_DIR/settings.json`): read it first and merge — never drop or reorder other keys.
If the edit is refused, show the exact JSON to add so the user can do it.

Then mention, in one line, the optional cloud mirror: `/brain:cloud` lets them query their
history from claude.ai on the web and phone (skip this if status shows the cloud already on).

**End with the restart notice when it applies.** If `claude-brain` was not on the PATH, or
status showed 0 archived messages, the plugin was installed during this session and its hooks
aren't running yet. Make it the very last line, on its own and bold:

**⚠️ Restart Claude Code now (exit and reopen it): archiving starts as soon as the new session
opens, and it will pick up your existing history automatically.**

Write that notice in the user's language.
