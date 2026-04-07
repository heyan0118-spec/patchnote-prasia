"""SQLite 데이터베이스 초기화 및 연결 관리."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import PROJECT_ROOT, database


SCHEMA_PATH = PROJECT_ROOT / "schema.sql"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """SQLite 연결을 반환한다. WAL 모드, foreign_keys 활성화."""
    path = db_path or database.path
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """schema.sql을 실행하여 테이블을 생성한다."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    existing_columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute("PRAGMA table_info(patch_notes)").fetchall()
    }
    if "source_board" not in existing_columns:
        conn.execute(
            "ALTER TABLE patch_notes ADD COLUMN source_board TEXT NOT NULL DEFAULT 'update'"
        )
        conn.commit()

    if close:
        conn.close()
