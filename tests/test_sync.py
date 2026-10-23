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
