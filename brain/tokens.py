"""`claude-brain tokens`: what the archived replies cost, and what opening a session costs."""
from collections import Counter
from datetime import datetime

from brain.stats import TOP, _n, _plural, _share

RECENT_WEEKS = 6


def _quantile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _week(ts: str) -> str:
    year, week, _ = datetime.fromisoformat(ts.replace("Z", "+00:00")).isocalendar()
    return f"{year}-W{week:02d}"


def compute(rows: list) -> dict:
    """Totals over every reply; `openings` is the context the first main-chain reply of each session saw."""
    totals, models, projects = Counter(), Counter(), Counter()
    first: dict[str, tuple] = {}
    sessions = set()
    for r in rows:
        spent = r["input"] + r["cache_write"] + r["cache_read"] + r["output"]
        for key in ("input", "cache_write", "cache_read", "output"):
            totals[key] += r[key]
        models[r["model"] or "unknown"] += spent
        projects[r["project"]] += spent
        sessions.add(r["session_id"])
        if not r["is_sidechain"] and r["ts"] and (r["session_id"] not in first or r["ts"] < first[r["session_id"]][0]):
            first[r["session_id"]] = (r["ts"], r["input"] + r["cache_write"] + r["cache_read"])
    weeks: dict[str, list[int]] = {}
    for ts, size in first.values():
        weeks.setdefault(_week(ts), []).append(size)
    openings = [size for _, size in first.values()]
    return {"replies": len(rows), "sessions": len(sessions), "totals": totals, "models": models,
            "projects": projects, "openings": openings, "weeks": weeks}


def run(conn, api, args, say=print) -> None:
    where, params = ["1 = 1"], []
    if args.project:
        where.append("s.project = ?")
        params.append(api.resolve_project(conn, args.project))
    if args.since:
        where.append("u.ts >= ?")
        params.append(args.since)
    rows = conn.execute(
        f"""SELECT u.session_id, u.ts, u.model, u.is_sidechain, u.input, u.cache_write, u.cache_read,
                   u.output, s.project FROM usage u JOIN sessions s USING (session_id)
            WHERE {' AND '.join(where)}""", params).fetchall()
    scope = f"project {params[0]}" if args.project else "All projects"
    if not rows:
        say(f"{scope}: no token usage archived yet (run an ingest: it backfills from the transcripts)")
        return
    st = compute(rows)
    t = st["totals"]
    say(f"🔢 {scope} · this computer\n")
    say(f"  {st['replies']:,} {'reply' if st['replies'] == 1 else 'replies'} in {_plural(st['sessions'], 'session')}")
    say(f"  Output {_n(t['output'])} · fresh input {_n(t['input'])} · "
        f"cache written {_n(t['cache_write'])} · cache read {_n(t['cache_read'])}")
    say(f"  Models           {_share(st['models'], sum(st['models'].values()))}")
    if not args.project:
        say(f"  Top projects     {_share(st['projects'], sum(st['projects'].values()), TOP)}")
    openings = st["openings"]
    if openings:
        say("")
        say(f"  Opening a session (context of its first reply, {_plural(len(openings), 'session')}): "
            f"median {_n(_quantile(openings, 0.5))} · p90 {_n(_quantile(openings, 0.9))}")
        recent = sorted(st["weeks"])[-RECENT_WEEKS:]
        say("  Median by week   " + " · ".join(
            f"{w} {_n(_quantile(st['weeks'][w], 0.5))}" for w in recent))
        say("  (a resumed session opens with its whole history, which lifts these numbers)")
