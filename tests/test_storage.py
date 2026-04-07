from datetime import datetime, timezone, timedelta
from pathlib import Path

from patchnote_prasia.crawler import PatchDetail
from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.storage import insert_patch_note


KST = timezone(timedelta(hours=9))


def test_insert_patch_note_persists_source_board(tmp_path: Path):
    db_path = tmp_path / "storage.db"
    conn = get_connection(db_path)
    init_db(conn)

    patch_note_id = insert_patch_note(
        conn,
        PatchDetail(
            thread_id="123",
            board_key="notice",
            board_id="2829",
            title="공지 제목",
            published_at=datetime(2026, 3, 29, tzinfo=KST),
            url="https://wp.nexon.com/news/notice/123",
            raw_html="<p>공지</p>",
            plain_text="공지",
            content_hash="abc123",
        ),
    )

    row = conn.execute(
        "SELECT id, source_board, url FROM patch_notes WHERE id = ?",
        (patch_note_id,),
    ).fetchone()
    conn.close()

    assert row["source_board"] == "notice"
    assert row["url"] == "https://wp.nexon.com/news/notice/123"
