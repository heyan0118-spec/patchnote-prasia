from pathlib import Path

from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.search import SearchFilters, hybrid_search
from patchnote_prasia.vector_index import build_vector_index
from patchnote_prasia.events import extract_event_records
from patchnote_prasia.analyze import analyze_patch_note
from patchnote_prasia.storage import replace_chunk_analysis, replace_event_records


def _seed_search_db(db_path: Path) -> None:
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            1,
            "https://example.test/class",
            "야만투사 업데이트",
            "2026-03-25T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "야만투사 전승과 스킬 변경",
        ),
    )
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            2,
            "https://example.test/event",
            "봄 이벤트 안내",
            "2026-03-11T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "봄 이벤트 출석 보상",
        ),
    )
    conn.execute(
        """INSERT INTO patch_note_chunks
           (id, patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (11, 1, 0, "야만투사", "야만투사 전승과 스킬이 개편되었습니다.", 10),
    )
    conn.execute(
        """INSERT INTO patch_note_chunks
           (id, patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (21, 2, 0, "이벤트", "봄 이벤트 출석 보상과 쿠폰 안내입니다.", 10),
    )
    conn.execute(
        """INSERT INTO topic_tags
           (patch_note_id, chunk_id, topic_type, topic_key, tag_value, prefer_latest, preserve_history, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, 11, "class", "야만투사", "야만투사", 0, 1, 0.95),
    )
    conn.execute(
        """INSERT INTO topic_tags
           (patch_note_id, chunk_id, topic_type, topic_key, tag_value, prefer_latest, preserve_history, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (2, 21, "event", "봄 이벤트", "봄 이벤트", 0, 1, 0.95),
    )
    conn.commit()
    conn.close()


def test_build_vector_index_creates_index_file(tmp_path: Path):
    db_path = tmp_path / "search.db"
    index_path = tmp_path / "vector_index.json"
    _seed_search_db(db_path)

    index = build_vector_index(db_path=db_path, index_path=index_path)

    assert index_path.exists()
    assert len(index.documents) == 2
    assert index.idf


def test_hybrid_search_returns_class_hit(tmp_path: Path):
    db_path = tmp_path / "search.db"
    index_path = tmp_path / "vector_index.json"
    _seed_search_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "야만투사 변경 내역",
        filters=SearchFilters(topic_type="class"),
        db_path=db_path,
        index_path=index_path,
    )

    assert result.policy_applied == "preserve_history"
    assert result.total_hits == 1
    assert result.sql_hits == 1
    assert result.hits[0].patch_title == "야만투사 업데이트"


def test_hybrid_search_respects_event_filter(tmp_path: Path):
    db_path = tmp_path / "search.db"
    index_path = tmp_path / "vector_index.json"
    _seed_search_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "이벤트 보상",
        filters=SearchFilters(topic_type="event"),
        db_path=db_path,
        index_path=index_path,
    )

    assert result.total_hits == 1
    assert result.hits[0].patch_title == "봄 이벤트 안내"


def test_extract_event_records_parses_generic_period_label():
    analyses = analyze_patch_note(
        "봄 출석 이벤트",
        "┃ 이벤트 안내\n기간 : 2026년 3월 1일(일) 점검 후 ~ 2026년 3월 7일(토) 오전 4시 59분\n대상 : 전체 클래스",
    )

    records = extract_event_records(
        "봄 출석 이벤트",
        "2026-03-01T06:00:00+09:00",
        analyses,
    )

    assert len(records) == 1
    assert records[0].event_type == "attendance_event"
    assert records[0].start_at == "2026-03-01T05:00:00+09:00"
    assert records[0].end_at == "2026-03-07T04:59:00+09:00"


def test_hybrid_search_prioritizes_event_records_for_class_change_history(tmp_path: Path):
    db_path = tmp_path / "events.db"
    index_path = tmp_path / "vector_index.json"
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            1,
            "https://example.test/class-change",
            "클래스 체인지 안내",
            "2026-03-25T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "┃ 클래스 체인지\n진행 기간 : 2026년 3월 25일(수) 점검 후 ~ 2026년 4월 8일(수) 오전 4시 59분\n대상 : 전체 클래스\n진행 렐름 : 전체 월드\n계정당 최대 3회",
        ),
    )
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            2,
            "https://example.test/class-balance",
            "아처 밸런스 조정",
            "2026-03-26T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "아처 스킬 계수가 변경되었습니다.",
        ),
    )
    analyses = analyze_patch_note(
        "클래스 체인지 안내",
        "┃ 클래스 체인지\n진행 기간 : 2026년 3월 25일(수) 점검 후 ~ 2026년 4월 8일(수) 오전 4시 59분\n대상 : 전체 클래스\n진행 렐름 : 전체 월드\n계정당 최대 3회",
    )
    chunk_id_map = replace_chunk_analysis(conn, 1, analyses)
    replace_event_records(
        conn,
        1,
        extract_event_records("클래스 체인지 안내", "2026-03-25T06:00:00+09:00", analyses),
        chunk_id_map,
    )
    conn.execute(
        """INSERT INTO patch_note_chunks
           (id, patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (21, 2, 0, "밸런스", "아처 스킬 계수가 변경되었습니다.", 8),
    )
    conn.execute(
        """INSERT INTO topic_tags
           (patch_note_id, chunk_id, topic_type, topic_key, tag_value, prefer_latest, preserve_history, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (2, 21, "class", "아처", "아처", 0, 1, 0.9),
    )
    conn.commit()
    conn.close()
    build_vector_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "클래스 체인지 진행 기간 알려줘",
        db_path=db_path,
        index_path=index_path,
    )

    assert result.hits
    assert result.hits[0].source_type == "event_record"
    assert result.hits[0].event_type == "class_change"
    assert result.hits[0].start_at == "2026-03-25T05:00:00+09:00"


def test_extract_event_records_deduplicates_same_event_across_chunks():
    analyses = analyze_patch_note(
        "클래스 체인지 안내",
        "┃ 클래스 체인지\n진행 기간 : 2026년 3월 25일(수) 점검 후 ~ 2026년 4월 8일(수) 오전 4시 59분\n대상 : 전체 클래스\n\n◾ 클래스 체인지 상세\n진행 기간 : 2026년 3월 25일(수) 점검 후 ~ 2026년 4월 8일(수) 오전 4시 59분\n대상 : 전체 클래스\n진행 렐름 : 전체 월드\n계정당 최대 3회",
    )

    records = extract_event_records(
        "클래스 체인지 안내",
        "2026-03-25T06:00:00+09:00",
        analyses,
    )

    assert len(records) == 1
    assert records[0].realm_scope is not None
    assert records[0].limit_per_account == 3


def test_hybrid_search_event_date_filter_uses_overlap(tmp_path: Path):
    db_path = tmp_path / "overlap.db"
    index_path = tmp_path / "vector-overlap.json"
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            1,
            "https://example.test/class-change",
            "클래스 체인지 안내",
            "2026-03-25T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "클래스 체인지 진행",
        ),
    )
    conn.execute(
        """INSERT INTO patch_note_chunks
           (id, patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (11, 1, 0, "클래스 체인지", "클래스 체인지 진행 안내입니다.", 10),
    )
    conn.execute(
        """INSERT INTO event_records
           (patch_note_id, chunk_id, event_type, event_key, title, summary, start_at, end_at, is_historical)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1,
            11,
            "class_change",
            "class_change:2026-03-25:전체-클래스",
            "클래스 체인지",
            "클래스 체인지 진행 안내입니다.",
            "2026-03-25T05:00:00+09:00",
            "2026-04-08T04:59:00+09:00",
            1,
        ),
    )
    conn.commit()
    conn.close()
    build_vector_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "클래스 체인지 기간",
        filters=SearchFilters(date_from="2026-04-01T00:00:00+09:00"),
        db_path=db_path,
        index_path=index_path,
    )

    assert result.hits
    assert result.hits[0].source_type == "event_record"
