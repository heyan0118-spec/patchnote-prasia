from pathlib import Path

from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.review_checks import compare_doc_counts, load_doc_counts


def test_compare_doc_counts_matches_current_fixture(tmp_path: Path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "README.md").write_text(
        "현재 메인 DB에는 `update 2건`, `notice 3건`, 총 `5건`이 적재되어 있습니다.\n",
        encoding="utf-8",
    )
    (project_root / "HANDOFF.md").write_text(
        "\n".join(
            [
                "- `patch_notes`: 5",
                "- `patch_note_chunks`: 7",
                "- `topic_tags`: 11",
                "- `event_records`: 13",
                "- `source_board='update'`: 2",
                "- `source_board='notice'`: 3",
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "review.db"
    conn = get_connection(db_path)
    init_db(conn)
    rows = [
        ("update", "https://example.test/update/1"),
        ("update", "https://example.test/update/2"),
        ("notice", "https://example.test/notice/1"),
        ("notice", "https://example.test/notice/2"),
        ("notice", "https://example.test/notice/3"),
    ]
    for index, (source_board, url) in enumerate(rows, start=1):
        conn.execute(
            """
            INSERT INTO patch_notes
            (source_site, game_code, source_board, external_id, url, title, collected_at, plain_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "nexon",
                "prasia-electric",
                source_board,
                str(index),
                url,
                f"title-{index}",
                "2026-03-30T00:00:00+09:00",
                "본문",
            ),
        )
    for patch_note_id in range(1, 6):
        conn.execute(
            """
            INSERT INTO patch_note_chunks (patch_note_id, chunk_index, chunk_text, token_count)
            VALUES (?, ?, ?, ?)
            """,
            (patch_note_id, 0, "chunk", 1),
        )
    conn.execute(
        "INSERT INTO patch_note_chunks (patch_note_id, chunk_index, chunk_text, token_count) VALUES (1, 1, 'chunk', 1)"
    )
    conn.execute(
        "INSERT INTO patch_note_chunks (patch_note_id, chunk_index, chunk_text, token_count) VALUES (2, 1, 'chunk', 1)"
    )
    for idx in range(11):
        conn.execute(
            """
            INSERT INTO topic_tags (patch_note_id, topic_type, topic_key, tag_value, prefer_latest, preserve_history, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ((idx % 5) + 1, "system", "system", "tag", 1, 0, 0.5),
        )
    for idx in range(13):
        conn.execute(
            """
            INSERT INTO event_records (patch_note_id, event_type, event_key, title, is_historical)
            VALUES (?, ?, ?, ?, ?)
            """,
            ((idx % 5) + 1, "season_event", f"key-{idx}", f"title-{idx}", 1),
        )
    conn.commit()
    conn.close()

    result = compare_doc_counts(project_root, db_path)

    assert result["mismatches"] == []


def test_load_doc_counts_parses_readme_and_handoff(tmp_path: Path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "README.md").write_text(
        "현재 메인 DB에는 `update 10건`, `notice 20건`, 총 `30건`이 적재되어 있습니다.\n",
        encoding="utf-8",
    )
    (project_root / "HANDOFF.md").write_text(
        "\n".join(
            [
                "- `patch_notes`: 30",
                "- `patch_note_chunks`: 300",
                "- `topic_tags`: 400",
                "- `event_records`: 50",
                "- `source_board='update'`: 10",
                "- `source_board='notice'`: 20",
            ]
        ),
        encoding="utf-8",
    )

    parsed = load_doc_counts(project_root)

    assert parsed["README"]["update"] == 10
    assert parsed["README"]["notice"] == 20
    assert parsed["README"]["patch_notes"] == 30
    assert parsed["HANDOFF"]["patch_note_chunks"] == 300
    assert parsed["HANDOFF"]["topic_tags"] == 400
