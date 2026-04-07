"""반복 운영 검증용 체크 함수."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import httpx

from .config import database, nexon_api


def _api_headers() -> dict[str, str]:
    return {
        "x-inface-api-key": nexon_api.api_key,
        "community-id": nexon_api.community_id,
        "User-Agent": nexon_api.user_agent,
    }


def collect_db_counts(db_path: Path | None = None) -> dict[str, object]:
    conn = _open_readonly_connection(db_path)
    payload = {
        "patch_notes": _scalar(conn, "SELECT COUNT(*) FROM patch_notes"),
        "patch_note_chunks": _scalar(conn, "SELECT COUNT(*) FROM patch_note_chunks"),
        "topic_tags": _scalar(conn, "SELECT COUNT(*) FROM topic_tags"),
        "event_records": _scalar(conn, "SELECT COUNT(*) FROM event_records"),
        "ingestion_runs": _scalar(conn, "SELECT COUNT(*) FROM ingestion_runs"),
        "ingestion_items": _scalar(conn, "SELECT COUNT(*) FROM ingestion_items"),
        "source_boards": {
            row["source_board"]: row["cnt"]
            for row in conn.execute(
                """
                SELECT source_board, COUNT(*) AS cnt
                FROM patch_notes
                GROUP BY source_board
                ORDER BY source_board
                """
            ).fetchall()
        },
    }
    conn.close()
    return payload


def collect_latest_run(db_path: Path | None = None) -> dict[str, object] | None:
    conn = _open_readonly_connection(db_path)
    row = conn.execute(
        """
        SELECT id, run_type, status, scanned_count, inserted_count,
               updated_count, error_count, started_at, finished_at, note
        FROM ingestion_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row is not None else None


def fetch_board_total(board_id: str) -> int:
    url = f"{nexon_api.base_url}/board/{board_id}/threadsV2"
    params = {
        "paginationType": "PAGING",
        "pageSize": 1,
        "blockSize": 1,
        "communityId": nexon_api.community_id,
        "boardId": board_id,
        "reqStr": "npsnUser",
        "pageNo": 1,
    }
    response = httpx.get(url, headers=_api_headers(), params=params, timeout=30)
    response.raise_for_status()
    return int(response.json()["totalElements"])


def board_parity(board_key: str, board_id: str, db_path: Path | None = None) -> dict[str, object]:
    counts = collect_db_counts(db_path)
    db_count = int(dict(counts["source_boards"]).get(board_key, 0))
    api_total = fetch_board_total(board_id)
    return {
        "board_key": board_key,
        "board_id": board_id,
        "db_count": db_count,
        "api_total": api_total,
        "match": db_count == api_total,
    }


def load_doc_counts(project_root: Path) -> dict[str, dict[str, int]]:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    handoff = (project_root / "HANDOFF.md").read_text(encoding="utf-8")
    return {
        "README": _parse_readme_counts(readme),
        "HANDOFF": _parse_handoff_counts(handoff),
    }


def compare_doc_counts(project_root: Path, db_path: Path | None = None) -> dict[str, object]:
    counts = collect_db_counts(db_path)
    docs = load_doc_counts(project_root)
    expected = {
        "patch_notes": int(counts["patch_notes"]),
        "patch_note_chunks": int(counts["patch_note_chunks"]),
        "topic_tags": int(counts["topic_tags"]),
        "event_records": int(counts["event_records"]),
        "update": int(dict(counts["source_boards"]).get("update", 0)),
        "notice": int(dict(counts["source_boards"]).get("notice", 0)),
    }

    mismatches: list[dict[str, object]] = []
    readme_counts = docs["README"]
    for key in ("update", "notice", "patch_notes"):
        actual = readme_counts.get(key)
        expected_key = "patch_notes" if key == "patch_notes" else key
        if actual is None:
            mismatches.append({"document": "README", "field": key, "expected": expected[expected_key], "actual": None})
        elif actual != expected[expected_key]:
            mismatches.append({"document": "README", "field": key, "expected": expected[expected_key], "actual": actual})

    handoff_counts = docs["HANDOFF"]
    for key, expected_value in expected.items():
        actual = handoff_counts.get(key)
        if actual is None:
            mismatches.append({"document": "HANDOFF", "field": key, "expected": expected_value, "actual": None})
        elif actual != expected_value:
            mismatches.append({"document": "HANDOFF", "field": key, "expected": expected_value, "actual": actual})

    return {"expected": expected, "documents": docs, "mismatches": mismatches}


def dump_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_readme_counts(text: str) -> dict[str, int]:
    match = re.search(
        r"update\s+(\d+)건`,\s*`notice\s+(\d+)건`,\s*총\s*`(\d+)건`",
        text,
    )
    if not match:
        return {}
    return {
        "update": int(match.group(1)),
        "notice": int(match.group(2)),
        "patch_notes": int(match.group(3)),
    }


def _parse_handoff_counts(text: str) -> dict[str, int]:
    fields = {
        "patch_notes": r"`patch_notes`:\s*(\d+)",
        "patch_note_chunks": r"`patch_note_chunks`:\s*(\d+)",
        "topic_tags": r"`topic_tags`:\s*(\d+)",
        "event_records": r"`event_records`:\s*(\d+)",
        "update": r"`source_board='update'`:\s*(\d+)",
        "notice": r"`source_board='notice'`:\s*(\d+)",
    }
    parsed: dict[str, int] = {}
    for key, pattern in fields.items():
        match = re.search(pattern, text)
        if match:
            parsed[key] = int(match.group(1))
    return parsed


def _scalar(conn: sqlite3.Connection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


def _open_readonly_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or database.path
    if path == Path(":memory:"):
        raise ValueError("Review checks require a persistent SQLite database, not :memory:")
    if not path.exists():
        raise FileNotFoundError(f"Database does not exist: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
