"""패치노트 청크 분할과 토픽 태깅."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .config import policy

MAX_CHUNK_CHARS = 1400
GENERIC_WORLD_KEYS = {
    "전체",
    "기존",
    "신규",
    "통합",
    "일부",
    "특정",
    "안내",
    "이벤트",
    "기념",
    "일자",
    "입니다",
    "오픈",
}

TOPIC_RULES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("event", ("이벤트", "출석", "보상", "쿠폰", "기간 한정"), "event"),
    ("world_open", ("월드 오픈", "신규 월드", "신규 서버", "서버 오픈"), "world"),
    (
        "balance",
        ("밸런스", "상향", "하향", "조정", "너프", "버프"),
        "balance",
    ),
    (
        "maintenance",
        ("점검", "긴급점검", "정기점검", "서버 작업"),
        "maintenance",
    ),
    ("item", ("아이템", "장비", "드롭", "교환", "상자"), "item"),
    ("content", ("던전", "레이드", "퀘스트", "필드", "보스"), "content"),
    ("system", ("시스템", "이용 안내", "편의", "거래소", "우편", "UI"), "system"),
)

EVENT_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("class_change_return", ("클래스 체인지 리턴",)),
    ("class_change", ("클래스 체인지", "골드 클래스 체인지")),
    ("attendance_event", ("출석", "출석 이벤트")),
    ("boosting_event", ("부스팅", "올인원부스팅")),
    ("transfer_event", ("월드 이전", "서버 이전", "월드 이동", "서버 이동")),
    ("season_event", ("시즌", "인피니티 시즌")),
)

HISTORY_TOPIC_TYPES = {
    "event",
    "class",
    "world_open",
    "balance",
    "class_change",
    "class_change_return",
    "attendance_event",
    "boosting_event",
    "transfer_event",
    "season_event",
}

CLASS_NAMES: tuple[str, ...] = (
    "아처",
    "메이지",
    "워리어",
    "어쌔신",
    "프리스트",
    "야만투사",
    "헌터",
    "환영검사",
)

WORLD_OPEN_PATTERNS = (
    re.compile(
        r"(?:신규|새로운)\s*(?:월드|서버)\s*[:：-]?\s*([가-힣A-Za-z][가-힣A-Za-z0-9]+)\s*(?:오픈|추가)"
    ),
    re.compile(r"([가-힣A-Za-z][가-힣A-Za-z0-9]+)\s*(?:월드|서버)\s*(?:오픈|추가)(?!\s*후)"),
    re.compile(r"(?:월드|서버)\s*오픈\s*[:：-]\s*([가-힣A-Za-z][가-힣A-Za-z0-9]+)"),
)


SECTION_MARKERS = ("┃", "◾", "■", "[", "※")


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    section_title: str | None
    chunk_text: str
    token_count: int


@dataclass(frozen=True)
class TopicTag:
    topic_type: str
    topic_key: str | None
    tag_value: str | None
    prefer_latest: bool
    preserve_history: bool
    confidence: float


@dataclass(frozen=True)
class ChunkAnalysis:
    chunk: Chunk
    tags: tuple[TopicTag, ...]


def _normalize_line(line: str) -> str:
    return " ".join(line.replace("\xa0", " ").split())


def normalize_plain_text(plain_text: str) -> str:
    lines = [_normalize_line(line) for line in plain_text.splitlines()]
    merged: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue

        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if line in SECTION_MARKERS and next_line:
            merged.append(f"{line} {next_line}".strip())
            index += 2
            continue
        if line.endswith(("(", "[", "‘", "'")) and next_line:
            merged.append(f"{line}{next_line}".strip())
            index += 2
            continue

        merged.append(line)
        index += 1

    return "\n".join(merged)


def _heading_level(line: str) -> int | None:
    if not line:
        return None
    if line in SECTION_MARKERS:
        return None
    if line.startswith("┃"):
        return 1
    if line.startswith(("◾", "■", "[", "※")):
        return 2
    if line.endswith(("업데이트", "안내", "변경사항", "패치노트")):
        return 1
    if line.endswith("드립니다."):
        return None
    if len(line) <= 30 and any(token in line for token in ("변경", "정보", "안내")):
        return 2
    return None


def _compose_section_title(top_level: str | None, sub_level: str | None) -> str | None:
    if top_level and sub_level:
        return f"{top_level} / {sub_level}"
    return sub_level or top_level


def _iter_sections(title: str, plain_text: str) -> Iterable[tuple[str | None, list[str]]]:
    top_level: str | None = title
    sub_level: str | None = None
    buffer: list[str] = []

    for raw_line in normalize_plain_text(plain_text).splitlines():
        line = _normalize_line(raw_line)
        if not line:
            continue
        heading_level = _heading_level(line)
        if heading_level is not None:
            if buffer:
                yield _compose_section_title(top_level, sub_level), buffer
                buffer = []
            if heading_level == 1:
                top_level = line
                sub_level = None
            else:
                sub_level = line
            continue
        buffer.append(line)

    if buffer:
        yield _compose_section_title(top_level, sub_level), buffer


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split_oversized_line(line: str) -> list[str]:
    if len(line) <= MAX_CHUNK_CHARS:
        return [line]

    parts: list[str] = []
    current = ""
    for fragment in re.split(r"(?<=[.!?])\s+", line):
        fragment = fragment.strip()
        if not fragment:
            continue
        projected = f"{current} {fragment}".strip()
        if current and len(projected) > MAX_CHUNK_CHARS:
            parts.append(current)
            current = fragment
        else:
            current = projected

    if current:
        parts.append(current)

    if parts:
        return parts

    return [line[i : i + MAX_CHUNK_CHARS] for i in range(0, len(line), MAX_CHUNK_CHARS)]


def chunk_plain_text(title: str, plain_text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_index = 0

    for section_title, lines in _iter_sections(title, plain_text):
        current: list[str] = []
        current_len = 0

        for raw_line in lines:
            for line in _split_oversized_line(raw_line):
                projected_len = current_len + len(line) + 1
                if current and projected_len > MAX_CHUNK_CHARS:
                    chunk_text = "\n".join(current)
                    chunks.append(
                        Chunk(
                            chunk_index=chunk_index,
                            section_title=section_title,
                            chunk_text=chunk_text,
                            token_count=_estimate_tokens(chunk_text),
                        )
                    )
                    chunk_index += 1
                    current = []
                    current_len = 0

                current.append(line)
                current_len += len(line) + 1

        if current:
            chunk_text = "\n".join(current)
            chunks.append(
                Chunk(
                    chunk_index=chunk_index,
                    section_title=section_title,
                    chunk_text=chunk_text,
                    token_count=_estimate_tokens(chunk_text),
                )
            )
            chunk_index += 1

    if chunks:
        return chunks

    normalized = _normalize_line(plain_text)
    if not normalized:
        return []
    return [
        Chunk(
            chunk_index=0,
            section_title=title,
            chunk_text=normalized,
            token_count=_estimate_tokens(normalized),
        )
    ]


def _policy_flags(topic_type: str) -> tuple[bool, bool]:
    preserve_history = (
        topic_type in policy.preserve_history_topics or topic_type in HISTORY_TOPIC_TYPES
    )
    prefer_latest = (
        policy.default_prefer_latest if not preserve_history else False
    )
    return prefer_latest, preserve_history


def _make_tag(
    topic_type: str,
    *,
    topic_key: str | None = None,
    tag_value: str | None = None,
    confidence: float = 0.8,
) -> TopicTag:
    prefer_latest, preserve_history = _policy_flags(topic_type)
    return TopicTag(
        topic_type=topic_type,
        topic_key=topic_key,
        tag_value=tag_value,
        prefer_latest=prefer_latest,
        preserve_history=preserve_history,
        confidence=confidence,
    )


def _is_valid_world_key(candidate: str) -> bool:
    normalized = candidate.strip("[]()'\"“”‘’ ")
    if not normalized or normalized in GENERIC_WORLD_KEYS:
        return False
    if re.search(r"\d", normalized):
        return False
    if normalized.endswith("개"):
        return False
    return len(normalized) >= 2


def _extract_world_open_keys(text: str) -> tuple[str, ...]:
    found: dict[str, None] = {}
    for pattern in WORLD_OPEN_PATTERNS:
        for candidate in pattern.findall(text):
            if _is_valid_world_key(candidate):
                found[candidate] = None
    return tuple(found.keys())


def classify_text(title: str, section_title: str | None, chunk_text: str) -> tuple[TopicTag, ...]:
    text = " ".join(part for part in (title, section_title or "", chunk_text) if part)
    tags: dict[tuple[str, str | None, str | None], TopicTag] = {}

    for class_name in CLASS_NAMES:
        if class_name in text:
            tag = _make_tag(
                "class",
                topic_key=class_name,
                tag_value=class_name,
                confidence=0.95,
            )
            tags[(tag.topic_type, tag.topic_key, tag.tag_value)] = tag

    for world_name in _extract_world_open_keys(text):
        tag = _make_tag(
            "world_open",
            topic_key=world_name,
            tag_value=world_name,
            confidence=0.9,
        )
        tags[(tag.topic_type, tag.topic_key, tag.tag_value)] = tag

    for topic_type, keywords, default_key in TOPIC_RULES:
        if any(keyword in text for keyword in keywords):
            if topic_type == "world_open":
                continue
            key = default_key
            if topic_type == "event":
                key = section_title or title
            tag = _make_tag(
                topic_type,
                topic_key=key,
                tag_value=section_title or title,
                confidence=0.8,
            )
            tags[(tag.topic_type, tag.topic_key, tag.tag_value)] = tag

    for topic_type, keywords in EVENT_TOPIC_RULES:
        if not any(keyword in text for keyword in keywords):
            continue
        key = section_title or title
        tag = _make_tag(
            topic_type,
            topic_key=key,
            tag_value=section_title or title,
            confidence=0.9 if topic_type.startswith("class_change") else 0.8,
        )
        tags[(tag.topic_type, tag.topic_key, tag.tag_value)] = tag

    if not tags:
        tag = _make_tag(
            "system",
            topic_key="system",
            tag_value=section_title or title,
            confidence=0.4,
        )
        tags[(tag.topic_type, tag.topic_key, tag.tag_value)] = tag

    return tuple(tags.values())


def analyze_patch_note(title: str, plain_text: str) -> list[ChunkAnalysis]:
    return [
        ChunkAnalysis(
            chunk=chunk,
            tags=classify_text(title, chunk.section_title, chunk.chunk_text),
        )
        for chunk in chunk_plain_text(title, plain_text)
    ]
