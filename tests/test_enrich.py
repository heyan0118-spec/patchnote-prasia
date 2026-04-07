from pathlib import Path

from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.enrich import run_enrichment


def test_run_enrichment_backfills_chunks(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "enrich.db"
    monkeypatch.setattr("patchnote_prasia.enrich.get_connection", lambda: get_connection(db_path))

    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (url, title, collected_at, plain_text)
           VALUES (?, ?, ?, ?)""",
        (
            "https://example.test/1",
            "야만투사 업데이트",
            "2026-03-29T00:00:00+09:00",
            "신규 클래스 야만투사\n야만투사 전승 스킬이 추가됩니다.",
        ),
    )
    conn.commit()
    conn.close()

    result = run_enrichment()

    conn = get_connection(db_path)
    chunk_count = conn.execute("SELECT COUNT(*) FROM patch_note_chunks").fetchone()[0]
    tag_count = conn.execute("SELECT COUNT(*) FROM topic_tags").fetchone()[0]
    conn.close()

    assert result["processed"] == 1
    assert chunk_count > 0
    assert tag_count > 0


def test_run_enrichment_skips_already_analyzed_notes(
    monkeypatch, tmp_path: Path
):
    db_path = tmp_path / "enrich-skip.db"
    monkeypatch.setattr(
        "patchnote_prasia.enrich.get_connection",
        lambda: get_connection(db_path),
    )

    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (url, title, collected_at, plain_text)
           VALUES (?, ?, ?, ?)""",
        (
            "https://example.test/1",
            "봄 이벤트 안내",
            "2026-03-29T00:00:00+09:00",
            "봄 이벤트\n이벤트 보상이 지급됩니다.",
        ),
    )
    conn.commit()
    conn.close()

    first = run_enrichment()
    second = run_enrichment()
    forced = run_enrichment(force=True)

    assert first["processed"] == 1
    assert second["processed"] == 0
    assert forced["processed"] == 1
