"""AUTH_TOKEN_SECRET resolution (env, protected file, ephemeral) and provisioning."""

import stat

import pytest

from app.core import config
from scripts.provision_auth_secret import provision

LONG = "x" * 40


def test_env_secret_wins_over_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret"
    secret_file.write_text("f" * 40)
    monkeypatch.setenv("AUTH_TOKEN_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("AUTH_TOKEN_SECRET", LONG)
    settings = config.get_settings()
    assert settings.auth_token_secret == LONG and not settings.auth_token_secret_ephemeral
    assert LONG not in repr(settings)


def test_file_secret_used_when_env_unset(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret"
    secret_file.write_text("f" * 40 + "\n")
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("AUTH_TOKEN_SECRET_FILE", str(secret_file))
    settings = config.get_settings()
    assert settings.auth_token_secret == "f" * 40 and not settings.auth_token_secret_ephemeral


def test_missing_file_falls_back_to_ephemeral(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("AUTH_TOKEN_SECRET_FILE", str(tmp_path / "absent"))
    assert config.get_settings().auth_token_secret_ephemeral


def test_short_file_secret_is_rejected(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret"
    secret_file.write_text("short")
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("AUTH_TOKEN_SECRET_FILE", str(secret_file))
    with pytest.raises(ValueError):
        config.get_settings()


def test_provision_is_idempotent_private_and_rotatable(tmp_path):
    path = tmp_path / "dir" / "secret"
    assert provision(path) == "created"
    first = path.read_text()
    assert len(first.strip()) >= config.MIN_TOKEN_SECRET_LENGTH
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert provision(path) == "kept" and path.read_text() == first
    assert provision(path, rotate=True) == "rotated" and path.read_text() != first
