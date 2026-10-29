"""Settings resolution of database URLs (env first, then generated file)."""

from app.core import config


def test_database_urls_read_from_generated_file(tmp_path, monkeypatch):
    urls = tmp_path / "database_urls.env"
    urls.write_text(
        "MIGRATION_DATABASE_URL=postgresql+psycopg://m:p@localhost:5432/d\n"
        "DATABASE_URL=postgresql+psycopg://a:p@localhost:5432/d\n"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URLS_FILE", str(urls))
    settings = config.get_settings()
    assert settings.database_url.endswith("@localhost:5432/d")
    settings_repr = repr(settings)
    assert "database_url" not in settings_repr
    assert "migration_database_url" not in settings_repr
    assert "postgresql+psycopg://" not in settings_repr
    assert "m:p@localhost:5432/d" not in settings_repr
    assert "a:p@localhost:5432/d" not in settings_repr


def test_environment_overrides_generated_file(tmp_path, monkeypatch):
    urls = tmp_path / "database_urls.env"
    urls.write_text("DATABASE_URL=postgresql+psycopg://file:p@localhost/d\n")
    monkeypatch.setenv("DATABASE_URLS_FILE", str(urls))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env:p@localhost/d")
    assert config.get_settings().database_url.startswith("postgresql+psycopg://env:")


def test_missing_file_leaves_urls_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URLS_FILE", str(tmp_path / "none.env"))
    settings = config.get_settings()
    assert settings.database_url is None and settings.migration_database_url is None
