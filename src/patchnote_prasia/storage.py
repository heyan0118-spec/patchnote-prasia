"""수집 데이터를 SQLite에 저장하고 수집 상태를 기록한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

from .analyze import ChunkAnalysis
from .crawler import PatchDetail
from .events import EventRecordDraft

KST = timezone(timedelta(hours=9))


def _now_kst() -> str:
    return datetime.now(KST).isoformat()


# ── ingestion run 관리 ─────────────────────────────────────


def start_run(conn: sqlite3.Connection, run_type: str = "scheduled") -> int:
    """새 수집 실행을 시작하고 run_id를 반환한다."""
    cur = conn.execute(
        "INSERT INTO ingestion_runs (run_type, started_at, status) VALUES (?, ?, ?)",
        (run_type, _now_kst(), "running"),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str = "success",
    scanned: int = 0,
    inserted: int = 0,
    updated: int = 0,
    errors: int = 0,
    note: str | None = None,
) -> None:
    conn.execute(
        """UPDATE ingestion_runs
           SET finished_at=?, status=?, scanned_count=?,
               inserted_count=?, updated_count=?, error_count=?, note=?
           WHERE id=?""",
        (_now_kst(), status, scanned, inserted, updated, errors, note, run_id),
    )
    conn.commit()


# ── 개별 아이템 기록 ───────────────────────────────────────


def record_item(
    conn: sqlite3.Connection,
    run_id: int,
    url: str,
    action: str,
    status: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO ingestion_items
           (ingestion_run_id, url, action, status, error_message)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, url, action, status, error_message),
    )
    conn.commit()


# ── 패치노트 저장 ─────────────────────────────────────────


def url_exists(conn: sqlite3.Connection, url: str) -> tuple[bool, str | None]:
    """URL 존재 여부와 기존 content_hash를 반환한다."""
    row = conn.execute(
        "SELECT content_hash FROM patch_notes WHERE url = ?", (url,)
    ).fetchone()
    if row is None:
        return False, None
    return True, row["content_hash"]


def insert_patch_note(conn: sqlite3.Connection, detail: PatchDetail) -> int:
    """새 패치노트를 삽입하고 id를 반환한다."""
    cur = conn.execute(
        """INSERT INTO patch_notes
           (source_site, game_code, source_board, external_id, url, title,
            published_at, collected_at, content_hash, raw_html, plain_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "nexon",
            "prasia-electric",
            detail.board_key,
            detail.thread_id,
            detail.url,
            detail.title,
            detail.published_at.isoformat(),
            _now_kst(),
            detail.content_hash,
            detail.raw_html,
            detail.plain_text,
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_patch_note(conn: sqlite3.Connection, detail: PatchDetail) -> None:
    """기존 패치노트의 본문이 변경된 경우 갱신한다."""
    conn.execute(
        """UPDATE patch_notes
           SET source_board=?, title=?, content_hash=?, raw_html=?, plain_text=?,
               collected_at=?, updated_at=CURRENT_TIMESTAMP
           WHERE url=?""",
        (
            detail.board_key,
            detail.title,
            detail.content_hash,
            detail.raw_html,
            detail.plain_text,
            _now_kst(),
            detail.url,
        ),
    )
    conn.commit()


def update_patch_note_plain_text(
    conn: sqlite3.Connection, patch_note_id: int, plain_text: str
) -> None:
    conn.execute(
        """UPDATE patch_notes
           SET plain_text=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (plain_text, patch_note_id),
    )
    conn.commit()


def replace_chunk_analysis(
    conn: sqlite3.Connection, patch_note_id: int, analyses: list[ChunkAnalysis]
) -> dict[int, int]:
    """청크/토픽 태그를 교체 저장한다."""
    conn.execute("DELETE FROM event_records WHERE patch_note_id = ?", (patch_note_id,))
    conn.execute("DELETE FROM topic_tags WHERE patch_note_id = ?", (patch_note_id,))
    conn.execute("DELETE FROM patch_note_chunks WHERE patch_note_id = ?", (patch_note_id,))
    chunk_id_map: dict[int, int] = {}

    for analysis in analyses:
        cur = conn.execute(
            """INSERT INTO patch_note_chunks
               (patch_note_id, chunk_index, section_title, chunk_text, token_count)
               VALUES (?, ?, ?, ?, ?)""",
            (
                patch_note_id,
                analysis.chunk.chunk_index,
                analysis.chunk.section_title,
                analysis.chunk.chunk_text,
                analysis.chunk.token_count,
            ),
        )
        chunk_id = int(cur.lastrowid)
        chunk_id_map[analysis.chunk.chunk_index] = chunk_id
        for tag in analysis.tags:
            conn.execute(
                """INSERT INTO topic_tags
                   (patch_note_id, chunk_id, topic_type, topic_key, tag_value,
                    prefer_latest, preserve_history, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    patch_note_id,
                    chunk_id,
                    tag.topic_type,
                    tag.topic_key,
                    tag.tag_value,
                    int(tag.prefer_latest),
                    int(tag.preserve_history),
                    tag.confidence,
                ),
            )

    conn.commit()
    return chunk_id_map


def replace_event_records(
    conn: sqlite3.Connection,
    patch_note_id: int,
    records: list[EventRecordDraft],
    chunk_id_map: dict[int, int],
) -> None:
    conn.execute("DELETE FROM event_records WHERE patch_note_id = ?", (patch_note_id,))

    for record in records:
        conn.execute(
            """INSERT INTO event_records
               (patch_note_id, chunk_id, event_type, event_key, title, summary,
                start_at, end_at, target_scope, realm_scope, limit_per_account,
                raw_period_text, raw_target_text, raw_realm_text, is_historical, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patch_note_id,
                chunk_id_map.get(record.chunk_index),
                record.event_type,
                record.event_key,
                record.title,
                record.summary,
                record.start_at,
                record.end_at,
                record.target_scope,
                record.realm_scope,
                record.limit_per_account,
                record.raw_period_text,
                record.raw_target_text,
                record.raw_realm_text,
                int(record.is_historical),
                _now_kst(),
            ),
        )

    conn.commit()


def get_patch_note_id_by_url(conn: sqlite3.Connection, url: str) -> int | None:
    row = conn.execute("SELECT id FROM patch_notes WHERE url = ?", (url,)).fetchone()
    if row is None:
        return None
    return int(row["id"])


def list_patch_notes_for_analysis(
    conn: sqlite3.Connection, *, only_missing: bool = True, limit: int | None = None
) -> list[sqlite3.Row]:
    sql = """
        SELECT pn.id, pn.title, pn.plain_text
             , pn.published_at
        FROM patch_notes pn
        WHERE pn.plain_text IS NOT NULL
          AND pn.plain_text != ''
    """
    params: list[object] = []
    if only_missing:
        sql += """
          AND NOT EXISTS (
              SELECT 1 FROM patch_note_chunks pc
              WHERE pc.patch_note_id = pn.id
          )
        """
    sql += " ORDER BY pn.published_at DESC, pn.id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def list_chunks_for_index(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            pc.id AS chunk_id,
            pc.chunk_text,
            pc.section_title,
            pn.title,
            pn.published_at,
            pn.url
        FROM patch_note_chunks pc
        JOIN patch_notes pn ON pn.id = pc.patch_note_id
        ORDER BY pn.published_at DESC, pc.id ASC
        """
    ).fetchall()


def fetch_search_rows(
    conn: sqlite3.Connection,
    *,
    topic_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT
            pc.id AS chunk_id,
            pc.chunk_text,
            pc.section_title,
            pc.chunk_index,
            pn.id AS patch_note_id,
            pn.title AS patch_title,
            pn.published_at,
            pn.url,
            COALESCE(MAX(tt.prefer_latest), 1) AS prefer_latest,
            COALESCE(MAX(tt.preserve_history), 0) AS preserve_history,
            GROUP_CONCAT(DISTINCT tt.topic_type) AS topic_types,
            GROUP_CONCAT(DISTINCT tt.topic_key) AS topic_keys
        FROM patch_note_chunks pc
        JOIN patch_notes pn ON pn.id = pc.patch_note_id
        LEFT JOIN topic_tags tt ON tt.chunk_id = pc.id
        WHERE 1=1
    """
    params: list[object] = []
    if date_from:
        sql += " AND pn.published_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND pn.published_at <= ?"
        params.append(date_to)
    if topic_type:
        sql += """
            AND EXISTS (
                SELECT 1
                FROM topic_tags ttf
                WHERE ttf.chunk_id = pc.id
                  AND ttf.topic_type = ?
            )
        """
        params.append(topic_type)
    sql += """
        GROUP BY pc.id, pn.id
        ORDER BY pn.published_at DESC, pc.chunk_index ASC
    """
    return conn.execute(sql, params).fetchall()


def fetch_event_search_rows(
    conn: sqlite3.Connection,
    *,
    topic_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT
            er.id AS event_record_id,
            er.chunk_id,
            er.event_type,
            er.event_key,
            er.title AS event_title,
            er.summary,
            er.start_at,
            er.end_at,
            er.target_scope,
            er.realm_scope,
            er.limit_per_account,
            er.raw_period_text,
            er.raw_target_text,
            er.raw_realm_text,
            er.is_historical,
            pn.id AS patch_note_id,
            pn.title AS patch_title,
            pn.published_at,
            pn.url,
            COALESCE(pc.section_title, er.title) AS section_title,
            COALESCE(pc.chunk_text, er.summary, er.title) AS chunk_text,
            er.event_type AS topic_types,
            er.event_type AS topic_keys,
            0 AS prefer_latest,
            1 AS preserve_history
        FROM event_records er
        JOIN patch_notes pn ON pn.id = er.patch_note_id
        LEFT JOIN patch_note_chunks pc ON pc.id = er.chunk_id
        WHERE 1 = 1
    """
    params: list[object] = []
    if date_from:
        sql += " AND COALESCE(er.end_at, er.start_at, pn.published_at) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND COALESCE(er.start_at, er.end_at, pn.published_at) <= ?"
        params.append(date_to)
    if topic_type:
        sql += " AND er.event_type = ?"
        params.append(topic_type)
    sql += """
        ORDER BY COALESCE(er.start_at, pn.published_at) DESC, er.id ASC
    """
    return conn.execute(sql, params).fetchall()


def list_chunks_for_vector_index(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            pc.id AS chunk_id,
            pc.patch_note_id,
            pn.title AS patch_title,
            pn.published_at,
            pn.url,
            pc.section_title,
            pc.chunk_text
        FROM patch_note_chunks pc
        JOIN patch_notes pn ON pn.id = pc.patch_note_id
        ORDER BY pc.id ASC
        """
    ).fetchall()


def fetch_chunk_search_rows(
    conn: sqlite3.Connection, chunk_ids: list[int]
) -> list[sqlite3.Row]:
    if not chunk_ids:
        return []

    placeholders = ",".join("?" for _ in chunk_ids)
    return conn.execute(
        f"""
        SELECT
            pc.id AS chunk_id,
            pc.patch_note_id,
            pc.chunk_index,
            pc.section_title,
            pc.chunk_text,
            pn.title AS patch_title,
            pn.published_at,
            pn.url,
            GROUP_CONCAT(DISTINCT tt.topic_type) AS topic_types,
            MAX(COALESCE(tt.prefer_latest, 0)) AS prefer_latest,
            MAX(COALESCE(tt.preserve_history, 0)) AS preserve_history
        FROM patch_note_chunks pc
        JOIN patch_notes pn ON pn.id = pc.patch_note_id
        LEFT JOIN topic_tags tt ON tt.chunk_id = pc.id
        WHERE pc.id IN ({placeholders})
        GROUP BY pc.id
        """,
        chunk_ids,
    ).fetchall()


def filter_chunk_ids(
    conn: sqlite3.Connection,
    *,
    topic_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[int]:
    sql = """
        SELECT DISTINCT pc.id
        FROM patch_note_chunks pc
        JOIN patch_notes pn ON pn.id = pc.patch_note_id
        LEFT JOIN topic_tags tt ON tt.chunk_id = pc.id
        WHERE 1 = 1
    """
    params: list[object] = []

    if topic_type:
        sql += " AND tt.topic_type = ?"
        params.append(topic_type)
    if date_from:
        sql += " AND pn.published_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND pn.published_at <= ?"
        params.append(date_to)

    rows = conn.execute(sql, params).fetchall()
    return [int(row["id"]) for row in rows]


# ── 재시도 대상 조회 ──────────────────────────────────────


def get_retry_urls(conn: sqlite3.Connection, max_retries: int = 3) -> list[str]:
    """실패했지만 재시도 가능한 URL 목록을 반환한다."""
    rows = conn.execute(
        """SELECT url FROM ingestion_items
           WHERE status = 'failed'
           GROUP BY url
           HAVING COUNT(*) < ?""",
        (max_retries,),
    ).fetchall()
    return [r["url"] for r in rows]


def is_abandoned(conn: sqlite3.Connection, url: str, max_retries: int = 3) -> bool:
    """해당 URL이 재시도 한도를 초과했는지 확인한다."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM ingestion_items WHERE url = ? AND status = 'failed'",
        (url,),
    ).fetchone()
    return row["cnt"] >= max_retries
