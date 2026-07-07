"""Settings validators: tilde expansion + root_path normalisation."""

from pathlib import Path

from app.config import Settings


def test_cache_dir_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", "~/.local/share/mdshards")
    settings = Settings()
    # `~` resolved to the home directory, not left literal.
    assert "~" not in str(settings.cache_dir)
    assert settings.cache_dir == Path("~/.local/share/mdshards").expanduser()


def test_vault_dir_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", "~/notes")
    settings = Settings()
    assert "~" not in str(settings.vault_dir)


def test_base_url_default_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.delenv("BASE_URL", raising=False)
    assert Settings().base_url == ""


def test_base_url_adds_leading_slash(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "wiki")
    assert Settings().base_url == "/wiki"


def test_base_url_strips_trailing_slash(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "/wiki/")
    assert Settings().base_url == "/wiki"


def test_base_url_single_slash_becomes_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "/")
    assert Settings().base_url == ""
