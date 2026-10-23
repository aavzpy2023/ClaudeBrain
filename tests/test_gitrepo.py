import pytest

from brain.db import project_for, resolve_repos, set_alias, load_aliases
from brain.gitrepo import find_repo, normalize_remote
from brain.ingest import ingest

from conftest import SID, SID2, rec, write_jsonl


@pytest.mark.parametrize("url", [
    "git@github.com:Aavzpy2023/Leai-CLI.git",
    "https://github.com/aavzpy2023/leai-cli",
    "https://user:ghp_secret@github.com/aavzpy2023/leai-cli.git/",
    "ssh://git@github.com:22/aavzpy2023/leai-cli.git",
    "github.com:aavzpy2023/leai-cli",
])
def test_normalize_remote_spellings(url):
    assert normalize_remote(url) == "github.com/aavzpy2023/leai-cli"


@pytest.mark.parametrize("url", ["/srv/git/repo.git", "../repo", "file:///srv/repo.git", r"C:\repos\x"])
def test_local_remotes_identify_nothing(url):
    assert normalize_remote(url) is None


def make_repo(root, remotes=None):
    git = root / ".git"
    git.mkdir(parents=True)
    lines = ["[core]", "\tbare = false"]
    for name, url in (remotes or {}).items():
        lines += [f'[remote "{name}"]', f"\turl = {url}", "\tfetch = +refs/heads/*:refs/remotes/x/*"]
    (git / "config").write_text("\n".join(lines) + "\n")
    return root


def test_find_repo_from_subfolder_prefers_origin(tmp_path):
    repo = make_repo(tmp_path / "leai", {"upstream": "git@github.com:other/fork.git",
                                         "origin": "git@github.com:aavzpy2023/leai-cli.git"})
    (repo / "src" / "pkg").mkdir(parents=True)
    assert find_repo(str(repo / "src" / "pkg")) == ("github.com/aavzpy2023/leai-cli", str(repo))


def test_find_repo_without_remote_and_outside_repos(tmp_path):
    repo = make_repo(tmp_path / "notes")
    assert find_repo(str(repo)) == (None, str(repo))
    assert find_repo(str(tmp_path / "plain")) == (None, None)
    assert find_repo(str(tmp_path / "missing" / "dir")) == (None, None)


def test_find_repo_in_linked_worktree(tmp_path):
    main = make_repo(tmp_path / "main", {"origin": "https://github.com/a/b.git"})
    wt_git = main / ".git" / "worktrees" / "feat"
    wt_git.mkdir(parents=True)
    (wt_git / "commondir").write_text("../..\n")
    wt = tmp_path / "feat"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_git}\n")
    assert find_repo(str(wt)) == ("github.com/a/b", str(wt))


def test_project_rules_with_repo():
    aliases = {"leaicli": "devleaicli", "github.com/a/skrpa": "devskrpa", "docs": "documentation"}
    # remote name drives the default, through its folder-style alias
    assert project_for("/w/leai/src", aliases, "github.com/x/leai-cli", "/w/leai") == "devleaicli"
    # alias on the remote beats everything
    assert project_for("/w/anything/docs", aliases, "github.com/a/skrpa", "/w/anything") == "devskrpa"
    # folder alias inside the repo beats the repo default
    assert project_for("/w/repo/docs", aliases, "github.com/x/repo", "/w/repo") == "documentation"
    # repo without remote: its root folder name, not the subfolder's
    assert project_for("/w/notes/2026/oct", {}, None, "/w/notes") == "notes"
    # not a repo: unchanged behaviour
    assert project_for("/w/plain/sub", {}, None, "") == "sub"


def test_clones_with_different_folder_names_merge(tmp_path, conn, root):
    home = make_repo(tmp_path / "home" / "leai-cli", {"origin": "git@github.com:me/leai-cli.git"})
    work = make_repo(tmp_path / "work" / "leai", {"origin": "https://github.com/me/leai-cli"})
    (work / "src").mkdir()
    write_jsonl(root / "a" / f"{SID}.jsonl", [
        rec("h1", "user", [{"type": "text", "text": "hola"}], "2026-10-01T10:00:00Z", cwd=str(home))])
    write_jsonl(root / "b" / f"{SID2}.jsonl", [
        rec("w1", "user", [{"type": "text", "text": "hola"}], "2026-10-02T10:00:00Z", sid=SID2,
            cwd=str(work / "src"))])
    ingest(conn, root)

    rows = dict(conn.execute("SELECT session_id, project FROM sessions").fetchall())
    assert rows == {SID: "leaicli", SID2: "leaicli"}
    assert conn.execute("SELECT DISTINCT repo FROM sessions").fetchall()[0][0] == "github.com/me/leai-cli"

    # Aliasing a repo folder path also aliases its remote, so every clone follows.
    assert set_alias(conn, str(home), "DEV-LeAI-cli") == 2
    assert load_aliases(conn) == {"leaicli": "devleaicli", "github.com/me/leai-cli": "devleaicli"}
    assert set(dict(conn.execute("SELECT session_id, project FROM sessions").fetchall()).values()) == {"devleaicli"}


def test_alias_by_remote_url_and_sticky_resolution(tmp_path, conn, root):
    repo = make_repo(tmp_path / "x", {"origin": "git@gitlab.com:me/thing.git"})
    write_jsonl(root / "a" / f"{SID}.jsonl", [
        rec("h1", "user", [{"type": "text", "text": "hola"}], "2026-10-01T10:00:00Z", cwd=str(repo))])
    ingest(conn, root)
    set_alias(conn, "https://gitlab.com/me/thing", "stuff")
    assert conn.execute("SELECT project FROM sessions").fetchone()[0] == "stuff"

    # The repo identity survives the folder disappearing.
    import shutil
    shutil.rmtree(repo)
    assert resolve_repos(conn) == 0
    assert conn.execute("SELECT repo FROM sessions").fetchone()[0] == "gitlab.com/me/thing"
