from pathlib import Path

from patchnote_prasia import config


def test_resolve_relative_database_url():
    path = config._resolve_database_path("sqlite:./data/test_patchnotes.db")

    assert path == (config.PROJECT_ROOT / "data" / "test_patchnotes.db").resolve()


def test_load_settings_reads_runtime_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("DATABASE_URL", "sqlite:./data/runtime.db")
    monkeypatch.setenv("REQUEST_DELAY", "1.5")
    monkeypatch.setenv("RERANK_ENABLE", "false")
    monkeypatch.setenv("PRESERVE_HISTORY_TOPICS", "event,class")
    monkeypatch.setenv("NEXON_BOARD_TARGETS", "update:2830,notice:2829")

    settings = config.load_settings()

    assert settings.app.env == "test"
    assert settings.app.port == 9000
    assert settings.database.path == (
        config.PROJECT_ROOT / "data" / "runtime.db"
    ).resolve()
    assert settings.nexon_api.request_delay == 1.5
    assert settings.nexon_api.board_targets == (("update", "2830"), ("notice", "2829"))
    assert settings.query.rerank_enabled is False
    assert settings.policy.preserve_history_topics == ("event", "class")


def test_load_settings_prefers_database_path(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "./data/from-path.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:./data/from-url.db")

    settings = config.load_settings()

    assert settings.database.path == (
        config.PROJECT_ROOT / "data" / "from-path.db"
    ).resolve()


def test_resolve_memory_database_url():
    path = config._resolve_database_path("sqlite::memory:")

    assert path == Path(":memory:")
