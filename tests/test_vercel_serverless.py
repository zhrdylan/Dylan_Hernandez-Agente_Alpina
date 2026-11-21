import importlib
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import pytest


def test_api_index_import():
    from api.index import app
    assert app is not None
    assert app.title == "Agente Alpina"


def test_vercel_environment_paths(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    import app.config as config
    importlib.reload(config)

    temp_base = Path(tempfile.gettempdir())
    assert config.REPORTS_DIR == temp_base / "reports"
    assert config.CACHE_DIR == temp_base / ".cache"
    assert config.DATA_DIR == temp_base / "data"

    # Ensure ensure_project_dirs succeeds
    config.ensure_project_dirs()


def test_preview_cache_under_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    import app.documents.preview as preview
    importlib.reload(preview)

    temp_base = Path(tempfile.gettempdir())
    assert preview._CACHE_BASE == temp_base / "alpina_cache"
    assert preview.CACHE_DIR == temp_base / "alpina_cache" / "pages"
    assert preview.DOCUMENT_CACHE_DIR == temp_base / "alpina_cache" / "documents"

    # Verify write and cleanup
    test_file = preview.CACHE_DIR / "sample_page.png"
    preview._write_cache(test_file, b"fake_png_data")
    assert test_file.exists()
    assert test_file.read_bytes() == b"fake_png_data"
    test_file.unlink()


def test_trusted_hosts_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    import app.config as config
    importlib.reload(config)

    settings = config.Settings()
    assert "*.vercel.app" in settings.trusted_hosts or "*" in settings.trusted_hosts

    # Test HTTP request with vercel.app host header
    from api.index import app
    client = TestClient(app, base_url="https://alpina-agent-preview.vercel.app")
    response = client.get("/health", headers={"host": "alpina-agent-preview.vercel.app"})
    # Should not return 400 Invalid Host
    assert response.status_code != 400
