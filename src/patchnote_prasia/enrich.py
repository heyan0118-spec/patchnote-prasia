"""기존 패치노트 청크/태깅 백필."""

from __future__ import annotations

import logging

from .analyze import analyze_patch_note, normalize_plain_text
from .db import get_connection, init_db
from .dense_index import build_dense_index
from .events import extract_event_records
from .storage import (
    list_patch_notes_for_analysis,
    replace_event_records,
    replace_chunk_analysis,
    update_patch_note_plain_text,
)
from .vector_index import build_vector_index

log = logging.getLogger(__name__)


def run_enrichment(
    *,
    force: bool = False,
    limit: int | None = None,
    db_path=None,
    index_path=None,
) -> dict[str, int]:
    conn = get_connection(db_path)
    init_db(conn)
    rows = list_patch_notes_for_analysis(conn, only_missing=not force, limit=limit)
    processed = 0

    for row in rows:
        normalized_text = normalize_plain_text(row["plain_text"])
        update_patch_note_plain_text(conn, int(row["id"]), normalized_text)
        analyses = analyze_patch_note(row["title"], normalized_text)
        chunk_id_map = replace_chunk_analysis(conn, int(row["id"]), analyses)
        published_at = row["published_at"] if "published_at" in row.keys() else None
        replace_event_records(
            conn,
            int(row["id"]),
            extract_event_records(row["title"], published_at, analyses),
            chunk_id_map,
        )
        processed += 1
        log.info("청크/태깅 완료: %s", row["title"])

    conn.close()
    if processed > 0 or force:
        build_vector_index(db_path=db_path, index_path=index_path)
        build_dense_index(db_path=db_path, index_path=index_path)
    return {"processed": processed}
