"""수집 파이프라인 — 목록 확인 → 상세 수집 → DB 저장."""

from __future__ import annotations

import logging
import time

import httpx

from .config import nexon_api, ingestion
from .analyze import analyze_patch_note
from .crawler import (
    PatchListItem,
    fetch_all_list,
    fetch_detail,
    make_client,
)
from .db import get_connection, init_db
from .dense_index import build_dense_index
from .events import extract_event_records
from .storage import (
    finish_run,
    get_patch_note_id_by_url,
    insert_patch_note,
    replace_event_records,
    replace_chunk_analysis,
    is_abandoned,
    record_item,
    start_run,
    update_patch_note,
    url_exists,
)
from .vector_index import build_vector_index

log = logging.getLogger(__name__)


def run_ingestion(
    *,
    run_type: str = "manual",
    max_items: int | None = None,
    db_path=None,
    index_path=None,
) -> dict:
    """전체 수집 파이프라인을 실행한다.

    Returns:
        실행 결과 요약 dict.
    """
    conn = get_connection(db_path)
    init_db(conn)

    run_id = start_run(conn, run_type)
    stats = {"scanned": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

    client = make_client()

    # 1) 목록 수집
    try:
        all_items: list[PatchListItem] = fetch_all_list(client, max_items=max_items)
    except httpx.HTTPError as exc:
        log.error("목록 페이지 요청 실패: %s", exc)
        finish_run(conn, run_id, status="list_fetch_failed", note=str(exc))
        conn.close()
        return {"status": "list_fetch_failed", "error": str(exc)}

    stats["scanned"] = len(all_items)
    log.info("목록 수집 완료: %d건", len(all_items))

    # 2) 상세 수집 및 저장
    for item in all_items:
        # 재시도 한도 초과 확인
        if is_abandoned(conn, item.url, ingestion.max_retries):
            log.warning("재시도 한도 초과, 건너뜀: %s", item.url)
            stats["skipped"] += 1
            continue

        # 이미 저장된 URL인지 확인
        exists, existing_hash = url_exists(conn, item.url)

        try:
            time.sleep(nexon_api.request_delay)
            detail = fetch_detail(
                client,
                item.thread_id,
                board_key=item.board_key,
                board_id=item.board_id,
            )
        except httpx.HTTPError as exc:
            log.error("상세 수집 실패 [%s]: %s", item.url, exc)
            record_item(conn, run_id, item.url, "fetch", "failed", str(exc))
            stats["errors"] += 1
            continue

        try:
            if not exists:
                patch_note_id = insert_patch_note(conn, detail)
                analyses = analyze_patch_note(detail.title, detail.plain_text)
                chunk_id_map = replace_chunk_analysis(conn, patch_note_id, analyses)
                replace_event_records(
                    conn,
                    patch_note_id,
                    extract_event_records(
                        detail.title,
                        detail.published_at.isoformat(),
                        analyses,
                    ),
                    chunk_id_map,
                )
                record_item(conn, run_id, item.url, "insert", "success")
                stats["inserted"] += 1
                log.info("신규 저장: %s", detail.title)
            elif existing_hash != detail.content_hash:
                update_patch_note(conn, detail)
                patch_note_id = get_patch_note_id_by_url(conn, detail.url)
                if patch_note_id is not None:
                    analyses = analyze_patch_note(detail.title, detail.plain_text)
                    chunk_id_map = replace_chunk_analysis(
                        conn,
                        patch_note_id,
                        analyses,
                    )
                    replace_event_records(
                        conn,
                        patch_note_id,
                        extract_event_records(
                            detail.title,
                            detail.published_at.isoformat(),
                            analyses,
                        ),
                        chunk_id_map,
                    )
                record_item(conn, run_id, item.url, "update", "success")
                stats["updated"] += 1
                log.info("갱신: %s", detail.title)
            else:
                stats["skipped"] += 1
        except Exception as exc:
            log.error("DB 저장 실패 [%s]: %s", item.url, exc)
            record_item(conn, run_id, item.url, "store", "failed", str(exc))
            stats["errors"] += 1

    try:
        if stats["inserted"] > 0 or stats["updated"] > 0:
            build_vector_index(db_path=db_path, index_path=index_path)
            build_dense_index(db_path=db_path, index_path=index_path)
    except Exception as exc:
        log.error("검색 인덱스 재빌드 실패: %s", exc)
        stats["errors"] += 1

    # 3) 실행 결과 기록
    final_status = "success" if stats["errors"] == 0 else "partial_success"
    finish_run(
        conn,
        run_id,
        status=final_status,
        scanned=stats["scanned"],
        inserted=stats["inserted"],
        updated=stats["updated"],
        errors=stats["errors"],
    )
    conn.close()
    client.close()

    log.info(
        "수집 완료 — 스캔: %d / 신규: %d / 갱신: %d / 건너뜀: %d / 오류: %d",
        stats["scanned"],
        stats["inserted"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )
    return {"status": final_status, **stats}
