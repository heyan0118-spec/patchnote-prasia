"""운영 이벤트 태그 및 canonical event record 추출."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from .analyze import ChunkAnalysis

KST_OFFSET = "+09:00"
DEFAULT_PATCH_START_HOUR = (5, 0, 0)
PATCH_END_SECOND = (4, 59, 59)
DATE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*년\s*)?"
    r"(?P<month>\d{1,2})\s*월\s*"
    r"(?P<day>\d{1,2})\s*일"
    r"(?:\([^)]+\))?"
    r"(?:\s*(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2})\s*시(?:\s*(?P<minute>\d{1,2})\s*분)?)?"
)


@dataclass(frozen=True)
class EventRecordDraft:
    chunk_index: int
    event_type: str
    event_key: str
    title: str
    summary: str
    start_at: str | None
    end_at: str | None
    target_scope: str | None
    realm_scope: str | None
    limit_per_account: int | None
    raw_period_text: str | None
    raw_target_text: str | None
    raw_realm_text: str | None
    is_historical: bool = True


def _slug(text: str) -> str:
    compact = re.sub(r"[^가-힣A-Za-z0-9]+", "-", text).strip("-").lower()
    return compact[:80] or "event"


def _extract_block(text: str, label: str, stop_labels: tuple[str, ...]) -> str | None:
    idx = text.find(label)
    if idx < 0:
        return None
    start = idx + len(label)
    tail = text[start:]
    stop_positions = [tail.find(stop) for stop in stop_labels if tail.find(stop) >= 0]
    end = min(stop_positions) if stop_positions else len(tail)
    value = tail[:end].strip(" :-")
    return value or None


def _parse_datetime_token(
    token: str,
    *,
    reference_year: int,
    end_of_day: bool = False,
) -> str | None:
    match = DATE_PATTERN.search(token)
    if not match:
        return None

    year = int(match.group("year") or reference_year)
    month = int(match.group("month"))
    day = int(match.group("day"))

    if "점검 후" in token:
        hour, minute, second = DEFAULT_PATCH_START_HOUR
    elif "점검 전" in token:
        hour, minute, second = PATCH_END_SECOND
    elif match.group("hour"):
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        second = 0
        if match.group("ampm") == "오후" and hour < 12:
            hour += 12
        if match.group("ampm") == "오전" and hour == 12:
            hour = 0
    elif end_of_day:
        hour, minute, second = (23, 59, 59)
    else:
        hour, minute, second = (0, 0, 0)

    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}{KST_OFFSET}"


def _extract_period(text: str, *, reference_year: int) -> tuple[str | None, str | None, str | None]:
    raw = None
    for label in ("진행 기간", "이벤트 기간", "운영 기간", "기간"):
        raw = _extract_block(
            text,
            label,
            ("대상", "진행 렐름", "진행 렐름", "계정당", "기타", "클래스", "임무"),
        )
        if raw:
            break
    if raw is None:
        return None, None, None

    parts = raw.split("~", maxsplit=1)
    if len(parts) != 2:
        return None, None, raw

    start_at = _parse_datetime_token(parts[0], reference_year=reference_year)
    end_at = _parse_datetime_token(parts[1], reference_year=reference_year, end_of_day=True)
    return start_at, end_at, raw


def _extract_limit(text: str) -> int | None:
    match = re.search(r"계정당(?:\s*최대)?\s*(\d+)\s*회", text)
    if match:
        return int(match.group(1))
    return None


def _scope_json(raw: str | None) -> str | None:
    if raw is None:
        return None

    include: list[str] = []
    exclude: list[str] = []
    range_value: dict[str, str] | None = None
    mode = "include"
    text = raw.strip()

    if "전체" in text:
        mode = "all"

    range_match = re.search(r"([가-힣A-Za-z0-9]+)\s*~\s*([가-힣A-Za-z0-9]+)", text)
    if range_match:
        mode = "range"
        range_value = {"from": range_match.group(1), "to": range_match.group(2)}

    exclude_match = re.search(r"\(([^)]*제외[^)]*)\)", text)
    if exclude_match:
        exclude = [
            part.strip()
            for part in re.split(r"[/,]", exclude_match.group(1).replace("제외", ""))
            if part.strip()
        ]

    paren_match = re.search(r"\(([^)]*)\)", text)
    if paren_match and "제외" not in paren_match.group(1):
        include = [
            part.strip()
            for part in re.split(r"[/,]", paren_match.group(1))
            if part.strip()
        ]

    if not include and mode == "include":
        include = [
            part.strip()
            for part in re.split(r"[/,]", re.sub(r"\([^)]*\)", "", text))
            if part.strip() and not any(keyword in part for keyword in ("대상", "진행", "모든", "클래스"))
        ]

    payload = {
        "mode": mode,
        "include": include,
        "exclude": exclude,
        "range": range_value,
        "raw": text,
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_target_scope(text: str) -> tuple[str | None, str | None]:
    raw = _extract_block(text, "대상", ("진행 렐름", "계정당", "기타", "클래스", "임무"))
    return _scope_json(raw), raw


def _extract_realm_scope(text: str) -> tuple[str | None, str | None]:
    raw = _extract_block(text, "진행 렐름", ("계정당", "기타", "클래스", "임무"))
    return _scope_json(raw), raw


def _first_sentence(text: str) -> str:
    normalized = text.replace("\n", " ").strip()
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return parts[0][:240] if parts else normalized[:240]


def _event_type(text: str, tags: tuple[str, ...]) -> str | None:
    if "클래스 체인지 리턴" in text:
        return "class_change_return"
    if "클래스 체인지" in text and any(key in text for key in ("진행 기간", "계정당", "골드 클래스 체인지")):
        return "class_change"
    if "출석" in text and "기간" in text:
        return "attendance_event"
    if "부스팅" in text and "기간" in text:
        return "boosting_event"
    if any(word in text for word in ("이전", "이동")) and any(word in text for word in ("월드", "서버")) and "기간" in text:
        return "transfer_event"
    if "시즌" in text and "기간" in text:
        return "season_event"
    if "world_open" in tags or ("월드 오픈" in text and any(word in text for word in ("신규", "오픈"))):
        return "world_open_event"
    return None


def extract_event_records(
    title: str,
    published_at: str | None,
    analyses: list[ChunkAnalysis],
) -> list[EventRecordDraft]:
    reference_year = datetime.fromisoformat(published_at).year if published_at else datetime.now().year
    records: dict[tuple[str, str], EventRecordDraft] = {}

    for analysis in analyses:
        section_title = analysis.chunk.section_title or title
        text = " ".join(part for part in (title, section_title, analysis.chunk.chunk_text) if part)
        tag_types = tuple(tag.topic_type for tag in analysis.tags)
        event_type = _event_type(text, tag_types)
        if event_type is None:
            continue

        start_at, end_at, raw_period_text = _extract_period(text, reference_year=reference_year)
        target_scope, raw_target_text = _extract_target_scope(text)
        realm_scope, raw_realm_text = _extract_realm_scope(text)
        limit_per_account = _extract_limit(text)

        event_title = section_title.replace("┃", "").replace("◾", "").strip()
        key_source = start_at or (published_at[:10] if published_at else None) or event_title
        event_key = f"{event_type}:{key_source}:{_slug(raw_target_text or event_title)}"
        summary = _first_sentence(analysis.chunk.chunk_text)
        draft = EventRecordDraft(
            chunk_index=analysis.chunk.chunk_index,
            event_type=event_type,
            event_key=event_key,
            title=event_title,
            summary=summary,
            start_at=start_at,
            end_at=end_at,
            target_scope=target_scope,
            realm_scope=realm_scope,
            limit_per_account=limit_per_account,
            raw_period_text=raw_period_text,
            raw_target_text=raw_target_text,
            raw_realm_text=raw_realm_text,
            is_historical=True,
        )
        dedupe_key = (draft.event_type, draft.event_key)
        existing = records.get(dedupe_key)
        if existing is None:
            records[dedupe_key] = draft
            continue
        current_score = sum(
            value is not None and value != ""
            for value in (
                draft.start_at,
                draft.end_at,
                draft.target_scope,
                draft.realm_scope,
                draft.limit_per_account,
            )
        )
        existing_score = sum(
            value is not None and value != ""
            for value in (
                existing.start_at,
                existing.end_at,
                existing.target_scope,
                existing.realm_scope,
                existing.limit_per_account,
            )
        )
        if current_score >= existing_score:
            records[dedupe_key] = draft

    return list(records.values())
