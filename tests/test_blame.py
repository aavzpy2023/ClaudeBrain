from datetime import datetime, timezone

from brain import blame, query
from brain.ingest import ingest

from conftest import CWD, SID, SID2, rec, write_jsonl

SID3 = "33333333-aaaa-bbbb-cccc-000000000003"
WIN_CWD = "C:\\Users\\u\\MLvsGNN"


def tool(uuid, name, args, ts, **kw):
    return rec(uuid, "assistant", [{"type": "tool_use", "name": name, "input": args}], ts, **kw)


def _archive(conn, root):
    write_jsonl(root / "a" / f"{SID}.jsonl", [
        rec("p1", "user", "Add dropout to the model", "2026-10-01T10:00:00Z"),
        tool("e1", "Edit", {"file_path": f"{CWD}/src/model.py", "old_string": "x"}, "2026-10-01T10:01:00Z"),
        rec("p2", "user", "Now tune the learning rate", "2026-10-01T10:05:00Z"),
        tool("e2", "Bash", {"command": "sed -i 's/0.1/0.01/' src/model.py"}, "2026-10-01T10:06:00Z"),
        # a different file that merely ends the same way must not count
        tool("e3", "Edit", {"file_path": f"{CWD}/lib/src/model.py", "old_string": "y"}, "2026-10-01T10:07:00Z"),
    ])
    write_jsonl(root / "b" / f"{SID2}.jsonl", [
        rec("q1", "user", "What does src/model.py do?", "2026-10-03T09:00:00Z", sid=SID2),
        rec("q2", "assistant", "It defines the GNN.", "2026-10-03T09:00:05Z", sid=SID2),
    ])
    write_jsonl(root / "c" / f"{SID3}.jsonl", [
        rec("w1", "user", "Port the model to Windows paths", "2026-10-05T08:00:00Z", sid=SID3, cwd=WIN_CWD),
        tool("w2", "Write", {"file_path": f"{WIN_CWD}\\src\\model.py", "content": "..."},
             "2026-10-05T08:02:00Z", sid=SID3, cwd=WIN_CWD),
    ])
    ingest(conn, root)


def test_same_file_across_clones_and_path_styles():
    assert blame.is_same_file("/home/a/x/src/model.py", "src/model.py", "/home/a/x")
    assert blame.is_same_file("/home/a/x/src/model.py", "src/model.py", "/home/a/x/docs")  # cwd below root
    assert blame.is_same_file("C:\\Users\\u\\X\\src\\Model.py", "src/model.py", "c:\\users\\u\\x")
    assert not blame.is_same_file("/home/a/x/lib/src/model.py", "src/model.py", "/home/a/x")
    assert not blame.is_same_file("/home/a/x/brain/db.py", "db.py", "/home/a/x")
    assert blame.is_same_file("/etc/hosts", "/etc/hosts", "/home/a")


def test_shell_commands_naming_the_file():
    line = '[tool:Bash] {"command": "sed -i \'s/a/b/\' ./src/model.py && git add src/model.py"}'
    assert blame.shell_names(line, "src/model.py", "/r")
    assert blame.shell_names('[tool:Bash] {"command": "cat /r/src/model.py"}', "src/model.py", "/r")
    assert not blame.shell_names('[tool:Bash] {"command": "cat lib/src/model.py"}', "src/model.py", "/r")
    assert not blame.shell_names("we changed src/model.py", "src/model.py", "/r")  # prose: a mention


def test_blame_finds_changes_whys_mentions_and_commits(conn, root):
    _archive(conn, root)
    commit_time = datetime(2026, 10, 1, 10, 20, tzinfo=timezone.utc)  # just after session 1
    late = datetime(2026, 10, 9, tzinfo=timezone.utc)  # no session active: unattributed
    out = blame.blame(conn, query, "src/model.py", "mlvsgnn",
                      [("abc1234", late, "later"), ("def5678", commit_time, "Tune model")])

    assert out["changed"] == 2
    newest, oldest = out["sessions"]
    assert newest["session_id"] == SID3 and newest["edits"] == 1  # Windows clone, same file
    assert oldest["session_id"] == SID
    assert (oldest["edits"], oldest["shell"]) == (1, 1)  # the lib/src/model.py edit is not counted
    assert [w["text"] for w in oldest["whys"]] == ["Add dropout to the model", "Now tune the learning rate"]
    assert [c[0] for c in oldest["commits"]] == ["def5678"]
    assert not newest["commits"]
    assert [s["session_id"] for s in out["mentioned"]] == [SID2]


def test_blame_command_output(conn, root, monkeypatch, capsys, tmp_path):
    _archive(conn, root)
    monkeypatch.chdir(tmp_path)
    args = query.build_parser().parse_args(["blame", "src/model.py", "--project", "gnn"])
    text = query.render(conn, args)
    assert "# " in text and "changed in 2 session(s)" in text
    assert 'why  2026-10-01 10:05  "Now tune the learning rate"' in text
    assert f"also mentioned in: {SID2[:8]}" in text
    assert f"claude-brain session {SID[:8]} --after 2026-10-01T10:00:00" in text


def test_repo_relative_uses_the_repo_root(tmp_path):
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:o/proj.git\n')
    (repo / "src").mkdir()
    assert blame.repo_relative("model.py", str(repo / "src")) == "src/model.py"
    assert blame.repo_relative(str(repo / "src" / "model.py"), "/") == "src/model.py"
    assert blame.repo_relative("notes/a.md", str(tmp_path)) == "notes/a.md"  # no repo: from here
    outside = tmp_path / "loose.txt"
    assert blame.repo_relative(str(outside), str(repo / "src")) == outside.resolve().as_posix()
