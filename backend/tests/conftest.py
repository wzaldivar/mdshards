from pathlib import Path

import pytest


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    vault_dir = tmp_path / "vault"
    cache_dir = tmp_path / "cache"
    vault_dir.mkdir()
    cache_dir.mkdir()
    monkeypatch.setenv("VAULT_DIR", str(vault_dir))
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))
    from app import config

    config.get_settings.cache_clear()
    yield vault_dir
    config.get_settings.cache_clear()


@pytest.fixture
def client(vault: Path):
    """TestClient pre-loaded with `Sec-Fetch-Site: same-origin` so the
    request shape matches what a real browser sends when the loaded bundle
    calls /api or opens /ws. Tests asserting the curl-bypass block (no
    browser fingerprint) should use `bare_client` instead."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), headers={"sec-fetch-site": "same-origin"}) as c:
        yield c, vault


@pytest.fixture
def bare_client(vault: Path):
    """TestClient with NO default browser-fingerprint headers — represents a
    raw caller (curl, script, server-to-server). Used to verify OriginGuard
    blocks bypass attempts on /api and /ws."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c, vault
