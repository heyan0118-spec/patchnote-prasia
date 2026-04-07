from pathlib import Path

from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.dense_index import build_dense_index, load_dense_index
from patchnote_prasia.vector_index import build_vector_index, load_vector_index


def test_build_vector_index_creates_searchable_index(tmp_path: Path):
    db_path = tmp_path / "index.db"
    index_path = tmp_path / "vector.json"
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (url, title, collected_at, plain_text)
           VALUES (?, ?, ?, ?)""",
        (
            "https://example.test/1",
            "거래소 업데이트",
            "2026-03-29T00:00:00+09:00",
            "거래소 수수료가 조정되었습니다.",
        ),
    )
    patch_note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO patch_note_chunks
           (patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?)""",
        (patch_note_id, 0, "거래소 업데이트", "거래소 수수료가 조정되었습니다.", 8),
    )
    conn.commit()
    conn.close()

    index = build_vector_index(db_path=db_path, index_path=index_path)
    loaded = load_vector_index(index_path)
    scores = loaded.search("거래소 수수료", top_k=5)

    assert index_path.exists()
    assert len(index.documents) == 1
    assert list(scores.values())[0] > 0


def test_build_dense_index_creates_searchable_index(tmp_path: Path):
    db_path = tmp_path / "index.db"
    index_path = tmp_path / "vector.json"
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (url, title, collected_at, plain_text)
           VALUES (?, ?, ?, ?)""",
        (
            "https://example.test/1",
            "클래스 체인지 안내",
            "2026-03-29T00:00:00+09:00",
            "클래스 체인지 진행 기간이 공개되었습니다.",
        ),
    )
    patch_note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO patch_note_chunks
           (patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?)""",
        (patch_note_id, 0, "클래스 체인지", "클래스 체인지 진행 기간이 공개되었습니다.", 8),
    )
    conn.commit()
    conn.close()

    index = build_dense_index(db_path=db_path, index_path=index_path)
    loaded = load_dense_index(index_path)
    scores = loaded.search("클래스 체인지 기간", top_k=5)

    assert index.index_path.exists()
    assert len(index.chunk_ids) == 1
    assert list(scores.values())[0] > 0


def test_dense_index_uses_db_scoped_default_path(tmp_path: Path):
    db_path = tmp_path / "isolated.db"
    conn = get_connection(db_path)
    init_db(conn)
    conn.execute(
        """INSERT INTO patch_notes
           (url, title, collected_at, plain_text)
           VALUES (?, ?, ?, ?)""",
        (
            "https://example.test/1",
            "격리 테스트",
            "2026-03-29T00:00:00+09:00",
            "격리된 dense 인덱스 테스트입니다.",
        ),
    )
    patch_note_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO patch_note_chunks
           (patch_note_id, chunk_index, section_title, chunk_text, token_count)
           VALUES (?, ?, ?, ?, ?)""",
        (patch_note_id, 0, "격리", "격리된 dense 인덱스 테스트입니다.", 8),
    )
    conn.commit()
    conn.close()

    index = build_dense_index(db_path=db_path)

    assert index.index_path == tmp_path / "isolated.vector_index.dense.joblib"
