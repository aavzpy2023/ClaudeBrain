"""`claude-brain stats`: your Claude history in numbers — volume, rhythm, projects, tools.

Works over any read API (the local archive, or brain.remote for every device). The databases
only aggregate (per hour, per session, per tool); days, streaks and the hour-of-day profile are
computed here, in the local time zone. Subagent messages are left out.
"""
from collections import Counter
from datetime import date, datetime, timedelta

BARS = "▁▂▃▄▅▆▇█"
NOVEL_WORDS = 90_000  # a typical novel, for scale
TOP = 5


def _local(hour_prefix: str) -> datetime:
    """'2026-10-23T21' (UTC) → local time."""
    return datetime.fromisoformat(hour_prefix + ":00:00+00:00").astimezone()


def _n(value: int) -> str:
    """12,345 → 12.3k; 167,600 → 168k; 1,234,567 → 1.2M."""
    for size, unit, start in ((1_000_000, "M", 1_000_000), (1_000, "k", 10_000)):
        if value >= start:
            scaled = value / size
            return (f"{scaled:.0f}" if scaled >= 100 else f"{scaled:.1f}".rstrip("0").rstrip(".")) + unit
    return f"{value:,}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _share(counter: Counter, total: int, top: int = TOP) -> str:
    items = [f"{key or '?'} {round(100 * n / total) or '<1'}%" for key, n in counter.most_common(top) if n]
    rest = len(counter) - top
    return " · ".join(items) + (f" · +{rest} more" if rest > 0 else "")


def longest_streak(days: set[date]) -> tuple[int, date | None, date | None]:
    best, start, end = 0, None, None
    for day in days:
        if day - timedelta(days=1) in days:
            continue  # not the first day of a run
        length = 1
        while day + timedelta(days=length) in days:
            length += 1
        if length > best:
            best, start, end = length, day, day + timedelta(days=length - 1)
    return best, start, end


def sparkline(values: list[int]) -> str:
    top = max(values) or 1
    return "".join(BARS[min(len(BARS) - 1, round(v / top * (len(BARS) - 1)))] if v else " " for v in values)


def compute(data: dict) -> dict:
    per_day: Counter = Counter()
    per_hour: Counter = Counter()
    by_role: Counter = Counter()
    words: Counter = Counter()
    projects: Counter = Counter()
    sources: Counter = Counter()
    for row in data["hours"]:
        when = _local(row["hour"])
        per_day[when.date()] += row["n"]
        per_hour[when.hour] += row["n"]
        by_role[row["role"]] += row["n"]
        words[row["role"]] += row["words"] or 0
        projects[row["project"]] += row["n"]
        sources[row["entrypoint"]] += row["n"]
    sessions = [s for s in data["sessions"] if s["msg_count"]]
    if not per_day:
        return {}
    first = min(per_day)
    streak = longest_streak(set(per_day))
    busiest = max(per_day, key=per_day.get)
    peak = max(range(24), key=lambda h: per_hour[h])
    return {
        "first": first, "span_days": (date.today() - first).days + 1,
        "messages": sum(by_role.values()), "by_role": by_role, "words": words,
        "sessions": len(sessions), "projects": projects, "sources": sources,
        "hosts": {s.get("host") for s in sessions if s.get("host")},
        "active_days": len(per_day), "busiest": (busiest, per_day[busiest]), "streak": streak,
        "hours": [per_hour[h] for h in range(24)], "peak": peak,
        "longest": max(sessions, key=lambda s: s["msg_count"]) if sessions else None,
        "tools": Counter({t["name"]: t["n"] for t in data["tools"] if t["name"]}),
    }


def run(conn, api, args, say=print) -> None:
    project = api.resolve_project(conn, args.project) if args.project else None
    st = compute(api.stats_data(conn, project, args.since))
    scope = f"project {project}" if project else "Your Claude history"
    if not st:
        say(f"{scope}: nothing archived yet")
        return
    computers = f" on {len(st['hosts'])} computers" if len(st["hosts"]) > 1 else ""
    say(f"🧠 {scope} · since {st['first']} ({st['span_days']} days)\n")
    say(f"  {_plural(st['messages'], 'message')} in {_plural(st['sessions'], 'session')} across "
        f"{_plural(len(st['projects']), 'project')}{computers}")
    user, claude = st["by_role"]["user"], st["by_role"]["assistant"]
    say(f"  You wrote {user:,} messages · {_n(st['words']['user'])} words")
    novels = st["words"]["assistant"] / NOVEL_WORDS
    scale = f" — about {novels:.0f} novel{'s' if round(novels) != 1 else ''}" if novels >= 1 else ""
    say(f"  Claude wrote {claude:,} replies · {_n(st['words']['assistant'])} words{scale}")
    if st["tools"]:
        top = " · ".join(f"{name} {_n(n)}" for name, n in st["tools"].most_common(TOP))
        say(f"  {sum(st['tools'].values()):,} tool calls: {top}")
    say("")
    day, count = st["busiest"]
    say(f"  Busiest day      {day} ({day:%a}) · {count:,} messages")
    length, start, end = st["streak"]
    run_ = f" · longest streak {length} days ({start} → {end})" if length > 1 else ""
    say(f"  Active days      {st['active_days']} of {st['span_days']}{run_}")
    if st["longest"]:
        s = st["longest"]
        say(f"  Longest session  {s['session_id'][:8]} · {s['msg_count']:,} msgs · {s['title'] or '(untitled)'}")
    say(f"  When you work    00 {sparkline(st['hours'])} 23   (peak {st['peak']:02d}:00–{(st['peak'] + 1) % 24:02d}:00)")
    say("")
    if not project:
        say(f"  Top projects     {_share(st['projects'], sum(st['projects'].values()))}")
    say(f"  Sources          {_share(st['sources'], sum(st['sources'].values()))}")
