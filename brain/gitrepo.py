"""Git identity of a working directory, read straight from .git files (no git binary needed)."""
import re
from pathlib import Path

_URL = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+)$", re.I)
_SCP = re.compile(r"^(?:[^@/]+@)?(?P<host>[^/:\\]{2,}):(?!/)(?P<path>[^\\]+)$")
_SECTION = re.compile(r'^\s*\[\s*remote\s+"(?P<name>[^"]+)"\s*\]')
_URL_KEY = re.compile(r"^\s*url\s*=\s*(?P<url>.+?)\s*$", re.I)


def normalize_remote(url: str) -> str | None:
    """'git@github.com:Owner/Repo.git', 'https://user:tok@github.com/owner/repo/' → 'github.com/owner/repo'.

    Local-path and file:// remotes identify nothing across machines, so they yield None.
    Credentials embedded in the URL are dropped.
    """
    url = url.strip()
    m = _URL.match(url)
    if m and m["scheme"].lower() == "file":
        return None
    m = m or _SCP.match(url)
    if not m:
        return None
    path = re.sub(r"\.git$", "", m["path"].strip("/"), flags=re.I).strip("/")
    return f"{m['host']}/{path}".lower() if path else None


def _git_dir(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    # Worktrees and submodules: .git is a file "gitdir: <path>", relative to the work tree.
    match = re.match(r"gitdir:\s*(.+)", dot_git.read_text(errors="replace").strip())
    return (root / match[1]).resolve() if match else None


def _remotes(config: Path) -> dict[str, str]:
    remotes, section = {}, None
    for line in config.read_text(errors="replace").splitlines():
        if line.lstrip().startswith("["):
            m = _SECTION.match(line)
            section = m["name"] if m else None
        elif section and section not in remotes and (m := _URL_KEY.match(line)):
            remotes[section] = m["url"]
    return remotes


def find_repo(cwd: str) -> tuple[str | None, str | None]:
    """(normalized remote or None, repo root path or None) for the repo containing cwd.

    'origin' wins, else the first remote listed; a repo without a usable remote still returns
    its root. Missing folders, non-repos and unreadable files all give (None, None), and so does a
    path written for another OS (`C:\\…` read on Linux), which would otherwise resolve against
    the current folder.
    """
    try:
        path = Path(cwd)
        if not path.is_absolute():
            return None, None
        for root in (path, *path.parents):
            if not (root / ".git").exists():
                continue
            git_dir = _git_dir(root)
            if git_dir is None:
                return None, str(root)
            common = git_dir / "commondir"  # linked worktrees share the main repo's config
            if common.is_file():
                git_dir = (git_dir / common.read_text().strip()).resolve()
            config = git_dir / "config"
            remotes = _remotes(config) if config.is_file() else {}
            url = remotes.get("origin") or next(iter(remotes.values()), None)
            return (normalize_remote(url) if url else None), str(root)
    except (OSError, ValueError):
        pass
    return None, None
