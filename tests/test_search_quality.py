from pathlib import Path
import json

from patchnote_prasia.analyze import analyze_patch_note
from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.events import extract_event_records
from patchnote_prasia.search import hybrid_search
from patchnote_prasia.storage import replace_chunk_analysis, replace_event_records
from patchnote_prasia.vector_index import build_vector_index, load_vector_index
from patchnote_prasia.dense_index import build_dense_index, load_dense_index
import joblib


CLASS_CHANGE_CASES = (
    (
        1,
        "2025-01-22T06:00:00+09:00",
        "심연추방자 클래스 체인지 안내",
        "┃ 클래스 체인지\n진행 기간 : 2025년 1월 22일(수) 점검 후 ~ 2025년 2월 5일(수) 오전 4시 59분\n대상 : 심연추방자 외 모든 클래스\n진행 렐름 : 아우리엘 ~ 트렌체 월드\n계정당 1회",
        "https://example.test/class-change-20250122",
    ),
    (
        2,
        "2025-03-12T06:00:00+09:00",
        "전체 클래스 체인지 안내",
        "┃ 클래스 체인지\n진행 기간 : 2025년 3월 12일(수) 점검 후 ~ 2025년 3월 26일(수) 점검 전\n대상 : 전체 클래스\n진행 렐름 : 전체 월드\n계정당 최대 2회",
        "https://example.test/class-change-20250312",
    ),
    (
        3,
        "2025-05-21T06:00:00+09:00",
        "골드 클래스 체인지 안내",
        "┃ 골드 클래스 체인지\n진행 기간 : 2025년 5월 21일(수) 점검 후 ~ 2025년 6월 4일(수) 점검 전\n대상 : 전체 클래스\n진행 렐름 : 전체 월드\n계정당 최대 2회",
        "https://example.test/class-change-20250521",
    ),
)


def _seed_event_history_db(db_path: Path) -> None:
    conn = get_connection(db_path)
    init_db(conn)
    for patch_note_id, published_at, title, plain_text, url in CLASS_CHANGE_CASES:
        conn.execute(
            """INSERT INTO patch_notes
               (id, url, title, published_at, collected_at, plain_text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                patch_note_id,
                url,
                title,
                published_at,
                "2026-03-30T00:00:00+09:00",
                plain_text,
            ),
        )
        analyses = analyze_patch_note(title, plain_text)
        chunk_id_map = replace_chunk_analysis(conn, patch_note_id, analyses)
        replace_event_records(
            conn,
            patch_note_id,
            extract_event_records(title, published_at, analyses),
            chunk_id_map,
        )
    conn.close()


def test_class_change_history_quality_guard_returns_all_expected_periods(tmp_path: Path):
    db_path = tmp_path / "quality.db"
    index_path = tmp_path / "quality.vector.json"
    _seed_event_history_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)
    build_dense_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "2025년 클래스 체인지 진행 기간 정리해줘",
        db_path=db_path,
        index_path=index_path,
        top_k=10,
    )

    assert result.hits[:3]
    assert [hit.source_type for hit in result.hits[:3]] == [
        "event_record",
        "event_record",
        "event_record",
    ]
    event_hits = [hit for hit in result.hits if hit.source_type == "event_record"]
    assert [hit.start_at for hit in event_hits] == [
        "2025-01-22T05:00:00+09:00",
        "2025-03-12T05:00:00+09:00",
        "2025-05-21T05:00:00+09:00",
    ]
    assert [hit.end_at for hit in event_hits] == [
        "2025-02-05T04:59:00+09:00",
        "2025-03-26T04:59:59+09:00",
        "2025-06-04T04:59:59+09:00",
    ]


def test_query_analysis_runs_once_per_search(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "quality.db"
    index_path = tmp_path / "quality.vector.json"
    _seed_event_history_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)
    build_dense_index(db_path=db_path, index_path=index_path)

    import patchnote_prasia.search as search_module

    original = search_module.classify_text
    calls = {"count": 0}

    def counted(question, title, text):
        calls["count"] += 1
        return original(question, title, text)

    monkeypatch.setattr(search_module, "classify_text", counted)

    result = hybrid_search(
        "2025년 클래스 체인지 진행 기간 정리해줘",
        db_path=db_path,
        index_path=index_path,
        top_k=10,
    )

    assert result.hits
    assert calls["count"] == 1


def test_spacing_variant_query_matches_compound_term(tmp_path: Path):
    db_path = tmp_path / "quality.db"
    index_path = tmp_path / "quality.vector.json"
    _seed_event_history_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO patch_notes
           (id, url, title, published_at, collected_at, plain_text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            10,
            "https://example.test/white-token-20250325",
            "3/25 패치노트",
            "2025-03-25T06:00:00+09:00",
            "2026-03-30T00:00:00+09:00",
            "백색 증표 획득처와 교환처가 추가되었습니다.",
        ),
    )
    analyses = analyze_patch_note("3/25 패치노트", "백색 증표 획득처와 교환처가 추가되었습니다.")
    chunk_id_map = replace_chunk_analysis(conn, 10, analyses)
    replace_event_records(conn, 10, extract_event_records("3/25 패치노트", "2025-03-25T06:00:00+09:00", analyses), chunk_id_map)
    conn.close()
    build_vector_index(db_path=db_path, index_path=index_path)
    build_dense_index(db_path=db_path, index_path=index_path)

    result = hybrid_search(
        "백색증표 언제 업데이트 됐어",
        db_path=db_path,
        index_path=index_path,
        top_k=5,
    )

    assert result.hits
    assert any("백색 증표" in hit.chunk_text for hit in result.hits)


def test_vector_index_uses_process_cache_and_reloads_on_file_change(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "quality.db"
    index_path = tmp_path / "quality.vector.json"
    _seed_event_history_db(db_path)
    build_vector_index(db_path=db_path, index_path=index_path)

    import patchnote_prasia.vector_index as vector_module
    vector_module._INDEX_CACHE.clear()

    original = vector_module.json.loads
    calls = {"count": 0}

    def counted(payload, *args, **kwargs):
        calls["count"] += 1
        return original(payload, *args, **kwargs)

    monkeypatch.setattr(vector_module.json, "loads", counted)

    first = load_vector_index(index_path=index_path, db_path=db_path)
    second = load_vector_index(index_path=index_path, db_path=db_path)
    payload = original(index_path.read_text(encoding="utf-8"))
    first_key = next(iter(payload["documents"]))
    del payload["documents"][first_key]
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    third = load_vector_index(index_path=index_path, db_path=db_path)

    assert first.documents
    assert second.documents
    assert len(third.documents) == len(first.documents) - 1
    assert calls["count"] == 2


def test_dense_index_uses_process_cache_and_reloads_on_file_change(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "quality.db"
    index_path = tmp_path / "quality.vector.json"
    _seed_event_history_db(db_path)
    build_dense_index(db_path=db_path, index_path=index_path)

    import patchnote_prasia.dense_index as dense_module
    dense_module._INDEX_CACHE.clear()

    original = dense_module.joblib.load
    calls = {"count": 0}

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(dense_module.joblib, "load", counted)

    first = load_dense_index(index_path=index_path, db_path=db_path)
    second = load_dense_index(index_path=index_path, db_path=db_path)
    payload = original(index_path.with_suffix(".dense.joblib"))
    payload["chunk_ids"] = payload["chunk_ids"][:-1]
    payload["matrix"] = payload["matrix"][:-1]
    joblib.dump(payload, index_path.with_suffix(".dense.joblib"))
    third = load_dense_index(index_path=index_path, db_path=db_path)

    assert first.chunk_ids
    assert second.chunk_ids
    assert len(third.chunk_ids) == len(first.chunk_ids) - 1
    assert calls["count"] == 2
