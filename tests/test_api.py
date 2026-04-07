from pathlib import Path

from fastapi.testclient import TestClient

from patchnote_prasia.api import create_app
from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.vector_index import build_vector_index


def _seed_api_db(db_path: Path) -> None:
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            1,
            "https://example.test/system",
            "거래소 안내",
            "2026-03-25T06:00:00+09:00",
            "2026-03-29T00:00:00+09:00",
            "거래소 수수료는 3퍼센트입니다.",
        ),
    )
    conn.execute(
        """INSERT INTO patch_note_chunks
           (id, patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (11, 1, 0, "거래소", "거래소 수수료는 3퍼센트입니다.", 10),
    )
    conn.execute(
        """INSERT INTO topic_tags
           (patch_note_id, chunk_id, topic_type, topic_key, tag_value, prefer_latest, preserve_history, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, 11, "system", "system", "거래소", 1, 0, 0.95),
    )
    conn.commit()
    conn.close()


def test_post_query_returns_response(tmp_path: Path):
    db_path = tmp_path / "api.db"
    index_path = tmp_path / "vector.json"
    _seed_api_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)
    client = TestClient(create_app(db_path=db_path, index_path=index_path))

    response = client.post(
        "/query",
        json={
            "question": "거래소 수수료 알려줘",
            "filters": {"topic_type": "system"},
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["policy_applied"] == "prefer_latest"
    assert data["total_hits"] == 1
    assert data["evidence"][0]["patch_title"] == "거래소 안내"
    assert "debug" not in data or data["debug"] is None


def test_get_query_debug_includes_debug_info(tmp_path: Path):
    db_path = tmp_path / "api.db"
    index_path = tmp_path / "vector.json"
    _seed_api_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)
    client = TestClient(create_app(db_path=db_path, index_path=index_path))

    response = client.get(
        "/query/debug",
        params={"question": "거래소 수수료 알려줘", "topic_type": "system"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["debug"]["sql_hits"] == 1
    assert "vector_hits" in data["debug"]


def test_post_query_returns_event_fields(tmp_path: Path):
    db_path = tmp_path / "api-events.db"
    index_path = tmp_path / "vector-events.json"
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
           (patch_note_id, chunk_id, event_type, event_key, title, summary, start_at, end_at,
            target_scope, realm_scope, limit_per_account, raw_period_text, raw_target_text, raw_realm_text, is_historical)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1,
            11,
            "class_change",
            "class_change:2026-03-25:전체-클래스",
            "클래스 체인지",
            "클래스 체인지 진행 안내입니다.",
            "2026-03-25T05:00:00+09:00",
            "2026-04-08T04:59:00+09:00",
            '{"mode":"all","include":[],"exclude":[],"range":null,"raw":"전체 클래스"}',
            '{"mode":"all","include":[],"exclude":[],"range":null,"raw":"전체 월드"}',
            3,
            "2026년 3월 25일 점검 후 ~ 2026년 4월 8일 오전 4시 59분",
            "전체 클래스",
            "전체 월드",
            1,
        ),
    )
    conn.commit()
    conn.close()
    build_vector_index(db_path=db_path, index_path=index_path)
    client = TestClient(create_app(db_path=db_path, index_path=index_path))

    response = client.post(
        "/query",
        json={"question": "클래스 체인지 진행 기간 알려줘", "top_k": 3},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence"][0]["source_type"] == "event_record"
    assert data["evidence"][0]["event_type"] == "class_change"
    assert data["evidence"][0]["target_scope"] is not None
    assert data["evidence"][0]["realm_scope"] is not None
