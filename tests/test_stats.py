from datetime import date

from brain import query, stats
from brain.ingest import ingest

from conftest import SID, SID2, rec, session_records, write_jsonl


def test_longest_streak_and_sparkline():
    days = {date(2026, 10, d) for d in (1, 2, 3, 7, 8)}
    assert stats.longest_streak(days) == (3, date(2026, 10, 1), date(2026, 10, 3))
    assert stats.longest_streak(set()) == (0, None, None)
    assert stats.sparkline([0, 1, 8]) == " ▂█"


def test_compact_numbers():
    assert stats._n(950) == "950"
    assert stats._n(12_345) == "12.3k"
    assert stats._n(167_600) == "168k"
    assert stats._n(1_234_567) == "1.2M"


def test_stats_over_an_archive(conn, root):
    write_jsonl(root / "a" / f"{SID}.jsonl", session_records())
    write_jsonl(root / "b" / f"{SID2}.jsonl", [
        rec("x1", "user", "one two three", "2026-10-02T09:00:00Z", sid=SID2, cwd="/home/u/thesis"),
        rec("x2", "assistant", "four five", "2026-10-02T09:00:05Z", sid=SID2, cwd="/home/u/thesis"),
    ])
    ingest(conn, root)

    st = stats.compute(query.stats_data(conn))
    assert st["sessions"] == 2 and set(st["projects"]) == {"mlvsgnn", "thesis"}
    assert st["by_role"]["user"] == 2 and st["words"]["user"] >= 3
    assert st["tools"]["Bash"] == 1
    assert st["active_days"] == 2

    only = stats.compute(query.stats_data(conn, "thesis"))
    assert only["sessions"] == 1 and only["messages"] == 2
    assert stats.compute(query.stats_data(conn, since="2030-01-01")) == {}

    text = query.render(conn, query.build_parser().parse_args(["stats"]))
    assert "2 sessions across 2 projects" in text and "Longest session" in text
    assert "nothing archived" in query.render(conn, query.build_parser().parse_args(["stats", "--since", "2030"]))
