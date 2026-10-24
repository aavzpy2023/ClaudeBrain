import json
from pathlib import Path

import pytest

from brain.db import connect

SID = "11111111-aaaa-bbbb-cccc-000000000001"
SID2 = "22222222-aaaa-bbbb-cccc-000000000002"
CWD = "/home/u/Projects/ML-vs-GNN"
CWD2 = "/home/u/Dropbox/PhD/MLvsGNN"


def rec(uuid, type_, content, ts, sid=SID, cwd=CWD, entry="cli", **extra):
    r = {
        "parentUuid": None, "isSidechain": False, "type": type_,
        "message": {"role": type_, "content": content},
        "uuid": uuid, "timestamp": ts, "entrypoint": entry, "cwd": cwd,
        "sessionId": sid, "gitBranch": "main",
    }
    r.update(extra)
    return r


def session_records():
    """One realistic session: noise to drop, messages to keep, bookkeeping lines."""
    return [
        {"type": "mode", "mode": "normal", "sessionId": SID},
        rec("u1", "user", [{"type": "text", "text":
            "<ide_selection>selected junk</ide_selection>Entrena el modelo GNN con regresión"}],
            "2026-10-01T10:00:00Z"),
        {"type": "ai-title", "aiTitle": "GNN training", "sessionId": SID},
        rec("a0", "assistant", [{"type": "thinking", "thinking": "secret plan"}], "2026-10-01T10:00:01Z"),
        rec("a1", "assistant", [{"type": "text", "text": "Decidimos usar GraphSAGE."}], "2026-10-01T10:00:02Z"),
        rec("a2", "assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": "python train.py"}}],
            "2026-10-01T10:00:03Z"),
        rec("t1", "user", [{"type": "tool_result", "content": "accuracy 0.91 " * 50}], "2026-10-01T10:00:04Z"),
        rec("m1", "user", [{"type": "text", "text": "meta caveat"}], "2026-10-01T10:00:05Z", isMeta=True),
        rec("n1", "user", "<task-notification>done</task-notification>", "2026-10-01T10:00:06Z"),
        {"type": "api-request-blob", "sessionId": SID, "message": {"role": "user", "content": "big blob"}},
        {"parentUuid": None, "isSidechain": False, "type": "system", "subtype": "away_summary",
         "content": "Resumen: modelo entrenado.", "uuid": "s1", "timestamp": "2026-10-01T10:00:07Z",
         "entrypoint": "cli", "cwd": CWD, "sessionId": SID},
        rec("c1", "user", "Summary: compacted context", "2026-10-01T10:00:08Z", isCompactSummary=True),
    ]


def write_jsonl(path: Path, records, partial: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
        if partial:
            fh.write(partial)


@pytest.fixture(autouse=True)
def no_real_cloud(monkeypatch, tmp_path_factory):
    """No test may reach the user's real Neon: hide NEON_URL and the real .env everywhere."""
    monkeypatch.delenv("NEON_URL", raising=False)
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.setattr("brain.sync.ENV_FILE", tmp_path_factory.mktemp("cfg") / "missing.env")


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "brain.db")
    yield c
    c.close()


@pytest.fixture
def root(tmp_path):
    return tmp_path / "projects"
