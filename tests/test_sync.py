import pytest

from brain.sync import neon_url, redact


@pytest.mark.parametrize("secret, label", [
    ("sk-ant-api03-" + "a" * 40, "api-key"),
    ("ghp_" + "A1b2" * 9, "github-token"),
    ("github_pat_" + "x" * 30, "github-token"),
    ("AKIAABCDEFGHIJKLMNOP", "aws-key"),
    ("AIza" + "B" * 35, "google-key"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
])
def test_redacts_known_token_formats(secret, label):
    out = redact(f"use {secret} here")
    assert secret not in out and f"[REDACTED:{label}]" in out


def test_redacts_url_password_but_keeps_context():
    out = redact("connect to postgresql://neondb_owner:npg_S3cr3tValue@ep-x.neon.tech/neondb")
    assert out == "connect to postgresql://neondb_owner:[REDACTED]@ep-x.neon.tech/neondb"


def test_redacts_assignments_and_private_keys():
    assert redact('PASSWORD="hunter2hunter2"') == 'PASSWORD=[REDACTED]"'
    assert redact("api_key: abcd1234efgh") == "api_key: [REDACTED]"
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    assert redact(f"key:\n{key}\nend") == "key:\n[REDACTED:private-key]\nend"


def test_leaves_ordinary_text_alone():
    text = "Decidimos usar GraphSAGE; max_tokens: 1024; el token: ok; https://neon.com/docs"
    assert redact(text) == text


def test_neon_url_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("NEON_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text('# comment\nNEON_URL="postgresql://u:p@h/db?sslmode=require"\n')
    assert neon_url(env) == "postgresql://u:p@h/db?sslmode=require"
    assert neon_url(tmp_path / "missing") is None
    monkeypatch.setenv("NEON_URL", "postgresql://env")
    assert neon_url(env) == "postgresql://env"


def test_merge_aliases_last_write_wins():
    from brain.sync import merge_aliases

    local = {"a": ("p1", "2026-10-02"), "b": ("old", "2026-10-01"), "c": ("mine", "2026-10-01")}
    remote = {"b": ("new", "2026-10-05"), "c": ("theirs", "2026-09-01"), "d": ("p4", "2026-10-03")}
    to_local, to_remote = merge_aliases(local, remote)
    assert to_local == {"b": ("new", "2026-10-05"), "d": ("p4", "2026-10-03")}
    assert to_remote == {"a": ("p1", "2026-10-02"), "c": ("mine", "2026-10-01")}


def test_direct_url_bypasses_neon_pooler():
    from brain.sync import direct_url

    pooled = "postgresql://owner:p%40ss@ep-cool-name-123-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"
    assert direct_url(pooled) == "postgresql://owner:p%40ss@ep-cool-name-123.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"
    direct = "postgresql://owner:x@ep-cool-name-123.c-6.us-east-2.aws.neon.tech/neondb"
    assert direct_url(direct) == direct


class FakeNeon:
    """Just enough of a psycopg connection for the schema/password bookkeeping in sync.py."""

    def __init__(self, version=None, legacy=False):
        self.tables = {"messages"} if legacy or version is not None else set()
        self.meta = {}
        if version is not None:
            self.tables.add("brain_meta")
            self.meta["schema_version"] = str(version)
        self.applied = self.passwords = 0
        self.locked = False
        self.rows = []

    def execute(self, query, params=None):
        q = str(query)  # psycopg's sql.Composed prints its parts, so ALTER ROLE shows up too
        self.rows = []
        if q.startswith("SELECT to_regclass"):
            self.rows = [("brain_meta" in self.tables, "messages" in self.tables)]
        elif q.startswith("SELECT value FROM brain_meta"):
            self.rows = [(self.meta[params[0]],)] if params[0] in self.meta else []
        elif q.startswith("INSERT INTO brain_meta"):
            self.meta[params[0]] = params[1]
        elif q.startswith("SELECT pg_advisory_xact_lock"):
            self.locked = True
        elif "CREATE TABLE IF NOT EXISTS brain_meta" in q:
            self.applied += 1
            self.tables |= {"brain_meta", "messages"}
        elif "ALTER ROLE brain_reader" in q:
            self.passwords += 1
        else:
            raise AssertionError(f"unexpected query: {q[:80]}")
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def commit(self):
        pass


def test_schema_version_is_declared_in_schema_sql():
    from brain.sync import schema_version

    assert schema_version() >= 1
    assert schema_version("-- schema_version: 7\nCREATE …") == 7


def test_schema_plan_never_goes_backwards():
    from brain.sync import schema_plan

    assert schema_plan(2, None) == "apply"       # empty database
    assert schema_plan(2, 0) == "apply"          # mirror from before versioning
    assert schema_plan(2, 1) == "apply"
    assert schema_plan(2, 2) == "current"
    assert schema_plan(2, 2, force=True) == "apply"
    assert schema_plan(2, 3) == "newer"
    assert schema_plan(2, 3, force=True) == "newer"  # an outdated machine must not roll back


def test_empty_neon_gets_schema_and_then_a_connector_password():
    from brain.sync import ensure_schema, reader_ready, schema_version, set_reader_password

    neon = FakeNeon()
    assert ensure_schema(neon) == ("apply", None)
    assert neon.applied == 1 and neon.locked
    assert neon.meta["schema_version"] == str(schema_version())
    assert not reader_ready(neon)  # first computer: setup will set it
    set_reader_password(neon)
    assert neon.passwords == 1 and reader_ready(neon)


def test_mirror_from_before_versioning_keeps_its_connector_password():
    from brain.sync import ensure_schema, reader_ready

    neon = FakeNeon(legacy=True)
    assert ensure_schema(neon) == ("apply", 0)
    assert neon.meta["reader_password"] == "assumed"
    assert reader_ready(neon)  # so `cloud setup` on another computer won't rotate it


def test_current_and_newer_schemas_are_left_alone():
    from brain.sync import ensure_schema, schema_version

    current = FakeNeon(version=schema_version())
    assert ensure_schema(current) == ("current", schema_version())
    newer = FakeNeon(version=schema_version() + 1)
    assert ensure_schema(newer, force=True) == ("newer", schema_version() + 1)
    assert current.applied == newer.applied == 0
    assert newer.meta["schema_version"] == str(schema_version() + 1)


def test_write_env_keeps_other_lines_and_is_private(tmp_path):
    import os
    import stat

    from brain.sync import env_problems, env_value, write_env

    env = tmp_path / "cfg" / ".env"
    write_env({"NEON_URL": "postgresql://a"}, env)
    env.write_text(env.read_text() + "OTHER=keep\n")
    write_env({"NEON_URL": "postgresql://b", "NEON_PROJECT_ID": "p-1"}, env)
    assert env_value("NEON_URL", env) == "postgresql://b"
    assert env_value("NEON_PROJECT_ID", env) == "p-1"
    assert "OTHER=keep" in env.read_text() and env.read_text().count("NEON_URL") == 1
    if os.name != "nt":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert env_problems(env) == []
        env.chmod(0o644)
        assert "chmod 600" in env_problems(env)[0]


class RecordingNeon:
    """Records statements; answers the tombstone query with other machines' forgotten ids."""

    def __init__(self, theirs=()):
        self.theirs = list(theirs)
        self.sql = []

    def execute(self, query, params=None):
        self.sql.append((" ".join(str(query).split()), params))
        self.rows = [(sid,) for sid in self.theirs] if str(query) == "SELECT session_id FROM forgotten" else []
        return self

    def __iter__(self):
        return iter(self.rows)

    def commit(self):
        pass


def test_sync_forgotten_pushes_tombstones_redactions_and_pulls_others(conn, root):
    from conftest import SID, SID2, rec, session_records, write_jsonl

    from brain import forget
    from brain.db import forgotten_ids
    from brain.ingest import ingest
    from brain.sync import sync_forgotten

    write_jsonl(root / "p" / f"{SID}.jsonl", session_records())
    write_jsonl(root / "q" / f"{SID2}.jsonl", [rec("x1", "user", "hello there", "2026-10-02T09:00:00Z", sid=SID2)])
    ingest(conn, root)
    forget.forget_sessions(conn, [SID])
    forget.redact_text(conn, "GraphSAGE")

    neon = RecordingNeon(theirs=[SID, SID2])  # SID2 was forgotten on another computer
    assert sync_forgotten(conn, neon) == 1
    statements = [q for q, _ in neon.sql]
    assert any(q.startswith("DELETE FROM messages WHERE session_id = ANY") for q in statements)
    assert any(q.startswith("UPDATE messages SET text = replace") for q in statements)
    assert conn.execute("SELECT COUNT(*) FROM pending_remote").fetchone()[0] == 0
    assert conn.execute("SELECT MIN(synced) FROM forgotten").fetchone()[0] == 1
    assert forgotten_ids(conn) == {SID, SID2}
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0  # SID2 dropped here too

    again = RecordingNeon(theirs=[SID, SID2])
    assert sync_forgotten(conn, again) == 0
    assert not any(q.startswith("DELETE") for q, _ in again.sql)  # nothing left to push


class _FakePsycopg:
    class OperationalError(Exception):
        pass

    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    def connect(self, url, connect_timeout):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.OperationalError("connection timeout expired")
        return "conn"


def test_failure_kind_names_the_cause():
    from brain.sync import failure_kind
    assert failure_kind(Exception("connection timeout expired")) == "timeout"
    assert failure_kind(Exception("server closed the connection unexpectedly")) == "closed by the server"
    assert failure_kind(Exception("password authentication failed")) == "authentication"
    assert failure_kind(Exception("could not translate host name")) == "dns"


def test_connect_awake_retries_a_sleeping_compute_and_logs_each_miss(monkeypatch):
    import io
    import sys
    from brain.sync import connect_awake
    fake = _FakePsycopg(failures=2)
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    log = io.StringIO()
    assert connect_awake("postgresql://u:p@h/db", pause=0, log=log) == "conn"
    assert fake.calls == 3 and log.getvalue().count("timeout") == 2
    assert "attempt 1/3" in log.getvalue() and "u:p" not in log.getvalue()  # never the credentials


def test_connect_awake_gives_up_after_the_last_attempt(monkeypatch):
    import io
    import sys
    import pytest
    from brain.sync import connect_awake
    fake = _FakePsycopg(failures=9)
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    with pytest.raises(fake.OperationalError):
        connect_awake("postgresql://u:p@h/db", attempts=2, pause=0, log=io.StringIO())
    assert fake.calls == 2
