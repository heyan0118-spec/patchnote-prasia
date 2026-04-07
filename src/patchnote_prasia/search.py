"""하이브리드 검색 서비스."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from .analyze import classify_text
from .config import policy, query
from .db import get_connection, init_db
from .dense_index import build_dense_index, load_dense_index
from .storage import fetch_event_search_rows, fetch_search_rows
from .vector_index import build_vector_index, load_vector_index


@dataclass(frozen=True)
class SearchFilters:
    topic_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None


QueryFilters = SearchFilters

EVENT_TOPIC_TYPES = {
    "class_change",
    "class_change_return",
    "attendance_event",
    "boosting_event",
    "transfer_event",
    "season_event",
    "world_open_event",
}


@dataclass(frozen=True)
class QueryPlan:
    question: str
    query_tags: tuple
    query_topic_keys: tuple[str, ...]
    event_type_hints: tuple[str, ...]
    preserve_history: bool
    question_tokens: frozenset[str]


@dataclass(frozen=True)
class SearchHit:
    source_type: str = "chunk"
    source_id: int = 0
    chunk_id: int | None = None
    patch_title: str = ""
    published_at: str | None = None
    url: str = ""
    section_title: str | None = None
    chunk_text: str = ""
    topic_types: tuple[str, ...] = ()
    topic_keys: tuple[str, ...] = ()
    event_type: str | None = None
    event_title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    target_scope: str | None = None
    realm_scope: str | None = None
    limit_per_account: int | None = None
    policy: str = "prefer_latest"
    similarity: float = 0.0
    recency: float = 0.0
    policy_bonus: float = 0.0
    structured_bonus: float = 0.0
    final_score: float = 0.0


@dataclass(frozen=True)
class HybridSearchResult:
    hits: tuple[SearchHit, ...] = ()
    policy_applied: str = "prefer_latest"
    total_hits: int = 0
    sql_hits: int = 0
    vector_hits: int = 0
    dense_hits: int = 0
    merged_candidates: int = 0
    rerank_weights: dict[str, float] | None = None
    elapsed_ms: int = 0


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part for part in value.split(",") if part)


def _query_tags(question: str):
    return classify_text(question, None, question)


def _rerank_weights(policy_applied: str) -> dict[str, float]:
    if policy_applied == "preserve_history":
        return {"similarity": 0.35, "recency": 0.15, "policy": 0.25, "structured": 0.25}
    return {"similarity": 0.30, "recency": 0.50, "policy": 0.10, "structured": 0.10}


def _recency_score(published_at: str | None, latest_ts: datetime | None) -> float:
    if not published_at or latest_ts is None:
        return 0.0
    published_ts = datetime.fromisoformat(published_at)
    age_days = max((latest_ts - published_ts).days, 0)
    return max(0.0, 1.0 - min(age_days / 365.0, 1.0))


def _policy_bonus(
    row,
    policy_applied: str,
    query_topic_keys: tuple[str, ...],
) -> float:
    base = 1.0 if (
        int(row["preserve_history"]) if policy_applied == "preserve_history" else int(row["prefer_latest"])
    ) else 0.0
    if not query_topic_keys:
        return base

    row_topic_keys = set(_parse_csv(row["topic_keys"]))
    key_match = 1.0 if row_topic_keys & set(query_topic_keys) else 0.0
    return max(base, key_match)


def _event_type_hints(question: str) -> tuple[str, ...]:
    mapping = (
        ("class_change_return", ("클래스 체인지 리턴",)),
        ("class_change", ("클래스 체인지", "골드 클래스 체인지")),
        ("attendance_event", ("출석", "출석 이벤트")),
        ("boosting_event", ("부스팅", "올인원부스팅")),
        ("transfer_event", ("월드 이전", "서버 이전", "월드 이동", "서버 이동")),
        ("season_event", ("시즌",)),
        ("world_open_event", ("월드 오픈", "신규 월드", "신규 서버")),
    )
    found = [event_type for event_type, keywords in mapping if any(keyword in question for keyword in keywords)]
    return tuple(found)


def _question_tokens(question: str) -> frozenset[str]:
    return frozenset(re.findall(r"[가-힣A-Za-z0-9]+", question.lower()))


QUERY_NORMALIZATION_MAP: tuple[tuple[str, str], ...] = (
    ("백색증표", "백색 증표"),
    ("클래스체인지", "클래스 체인지"),
    ("부스팅월드", "부스팅 월드"),
)


def _normalize_question_variants(question: str) -> tuple[str, ...]:
    variants = [question]
    normalized = question
    for compact, spaced in QUERY_NORMALIZATION_MAP:
        if compact in normalized and spaced not in normalized:
            variants.append(normalized.replace(compact, spaced))
        if spaced in normalized and compact not in normalized:
            variants.append(normalized.replace(spaced, compact))
    return tuple(dict.fromkeys(part.strip() for part in variants if part.strip()))


def _build_query_plan(question: str, filters: SearchFilters) -> QueryPlan:
    query_tags = tuple(_query_tags(question))
    generic_keys = {
        "event",
        "world",
        "balance",
        "maintenance",
        "item",
        "content",
        "system",
    }
    query_topic_keys = tuple(
        dict.fromkeys(
            tag.topic_key
            for tag in query_tags
            if tag.topic_key and tag.topic_key not in generic_keys
        )
    )
    preserve_history = (
        filters.topic_type in policy.preserve_history_topics
        or any(token in question for token in ("언제", "기간", "역대", "모두", "정리", "몇 번"))
        or any(tag.preserve_history for tag in query_tags)
    )
    return QueryPlan(
        question=question,
        query_tags=query_tags,
        query_topic_keys=query_topic_keys,
        event_type_hints=_event_type_hints(question),
        preserve_history=preserve_history,
        question_tokens=_question_tokens(question),
    )


def _should_include_event_candidates(
    question: str,
    filters: SearchFilters,
    event_type_hints: tuple[str, ...],
    query_tags,
) -> bool:
    if filters.topic_type in EVENT_TOPIC_TYPES:
        return True
    if event_type_hints:
        return True
    return any(tag.topic_type in EVENT_TOPIC_TYPES for tag in query_tags)


def _keyword_overlap_score(question_tokens: frozenset[str], text: str) -> float:
    if not question_tokens:
        return 0.0
    haystack = set(re.findall(r"[가-힣A-Za-z0-9]+", text.lower()))
    if not haystack:
        return 0.0
    overlap = len(question_tokens & haystack)
    return min(overlap / max(len(question_tokens), 1), 1.0)


def _structured_bonus(query_plan: QueryPlan, row) -> float:
    row_keys = set(row.keys())
    patch_title = row["patch_title"]
    text = " ".join(
        str(part)
        for part in (
            patch_title,
            row["section_title"],
            row["chunk_text"],
            row["event_title"] if "event_title" in row_keys else None,
            row["raw_period_text"] if "raw_period_text" in row_keys else None,
            row["raw_target_text"] if "raw_target_text" in row_keys else None,
            row["raw_realm_text"] if "raw_realm_text" in row_keys else None,
        )
        if part
    )
    bonus = _keyword_overlap_score(query_plan.question_tokens, text)
    
    # "점검" 키워드 처리 강화
    if "점검" in query_plan.question:
        if "점검" in patch_title:
            bonus = max(bonus, 1.0)  # 제목에 점검이 있으면 최고점
        elif "maintenance" in _parse_csv(row.get("topic_types", "")):
            bonus = max(bonus, 0.8)  # 토픽이 점검이면 높은 점수

    if query_plan.event_type_hints and "event_type" in row_keys and row["event_type"] in query_plan.event_type_hints:
        bonus = max(bonus, 1.0)
    has_period = ("start_at" in row_keys and row["start_at"]) or ("end_at" in row_keys and row["end_at"])
    if any(token in query_plan.question for token in ("기간", "언제")) and has_period:
        bonus = max(bonus, 0.9)
    if "몇 회" in query_plan.question or "몇 번" in query_plan.question:
        if "limit_per_account" in row_keys and row["limit_per_account"] is not None:
            bonus = max(bonus, 0.9)
    return bonus


def hybrid_search(
    question: str,
    *,
    filters: SearchFilters | None = None,
    top_k: int | None = None,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> HybridSearchResult:
    started = time.perf_counter()
    filters = filters or SearchFilters()
    top_k = top_k or query.top_k

    conn = get_connection(db_path)
    init_db(conn)
    chunk_rows = fetch_search_rows(
        conn,
        topic_type=filters.topic_type,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
    event_rows = fetch_event_search_rows(
        conn,
        topic_type=filters.topic_type,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
    conn.close()

    total_hits = len(chunk_rows) + len(event_rows)
    query_plan = _build_query_plan(question, filters)
    question_variants = _normalize_question_variants(question)
    policy_applied = "preserve_history" if query_plan.preserve_history else "prefer_latest"
    weights = _rerank_weights(policy_applied)

    index = load_vector_index(index_path, db_path=db_path)
    dense_index = load_dense_index(index_path, db_path=db_path)
    if not index.documents and chunk_rows:
        index = build_vector_index(db_path=db_path, index_path=index_path)
    if not dense_index.chunk_ids and chunk_rows:
        dense_index = build_dense_index(db_path=db_path, index_path=index_path)

    candidate_ids = {int(row["chunk_id"]) for row in chunk_rows}
    sparse_scores: dict[int, float] = {}
    dense_scores: dict[int, float] = {}
    for question_variant in question_variants:
        variant_sparse = index.search(
            question_variant,
            candidate_ids=candidate_ids,
            top_k=query.hybrid_candidates,
        )
        variant_dense = dense_index.search(
            question_variant,
            candidate_ids=candidate_ids,
            top_k=query.hybrid_candidates,
        )
        for chunk_id, score in variant_sparse.items():
            sparse_scores[chunk_id] = max(sparse_scores.get(chunk_id, 0.0), score)
        for chunk_id, score in variant_dense.items():
            dense_scores[chunk_id] = max(dense_scores.get(chunk_id, 0.0), score)
    vector_scores = {
        chunk_id: sparse_scores.get(chunk_id, 0.0) * 0.55 + dense_scores.get(chunk_id, 0.0) * 0.45
        for chunk_id in set(sparse_scores) | set(dense_scores)
    }

    recent_rows = chunk_rows[: query.hybrid_candidates]
    keyed_rows = [
        row
        for row in chunk_rows
        if set(_parse_csv(row["topic_keys"])) & set(query_plan.query_topic_keys)
    ]
    merged_ids = {int(row["chunk_id"]) for row in recent_rows}
    merged_ids |= {int(row["chunk_id"]) for row in keyed_rows[: query.hybrid_candidates]}
    merged_ids |= set(vector_scores)
    merged_rows = [row for row in chunk_rows if int(row["chunk_id"]) in merged_ids]
    event_candidates: list = []
    if _should_include_event_candidates(question, filters, query_plan.event_type_hints, query_plan.query_tags):
        hinted_rows = [
            row
            for row in event_rows
            if not query_plan.event_type_hints or row["event_type"] in query_plan.event_type_hints
        ]
        event_candidates = hinted_rows[: max(query.hybrid_candidates, top_k * 3)]

    latest_ts = None
    latest_source = chunk_rows[0] if chunk_rows else (event_rows[0] if event_rows else None)
    if latest_source and latest_source["published_at"]:
        latest_ts = datetime.fromisoformat(latest_source["published_at"])

    scored_hits: list[SearchHit] = []
    for row in merged_rows:
        similarity = float(vector_scores.get(int(row["chunk_id"]), 0.0))
        recency = _recency_score(row["published_at"], latest_ts)
        policy_bonus = _policy_bonus(row, policy_applied, query_plan.query_topic_keys)
        structured_bonus = _structured_bonus(query_plan, row)
        final_score = (
            similarity * weights["similarity"]
            + recency * weights["recency"]
            + policy_bonus * weights["policy"]
            + structured_bonus * weights["structured"]
        )
        topic_types = _parse_csv(row["topic_types"])
        topic_keys = _parse_csv(row["topic_keys"])
        hit_policy = "preserve_history" if int(row["preserve_history"]) else "prefer_latest"
        scored_hits.append(
            SearchHit(
                source_type="chunk",
                source_id=int(row["chunk_id"]),
                chunk_id=int(row["chunk_id"]),
                patch_title=row["patch_title"],
                published_at=row["published_at"],
                url=row["url"],
                section_title=row["section_title"],
                chunk_text=row["chunk_text"],
                topic_types=topic_types,
                topic_keys=topic_keys,
                event_type=None,
                event_title=None,
                start_at=None,
                end_at=None,
                target_scope=None,
                realm_scope=None,
                limit_per_account=None,
                policy=hit_policy,
                similarity=similarity,
                recency=recency,
                policy_bonus=policy_bonus,
                structured_bonus=structured_bonus,
                final_score=final_score,
            )
        )

    for row in event_candidates:
        similarity = _keyword_overlap_score(
            query_plan.question_tokens,
            " ".join(
                part
                for part in (
                    row["event_title"],
                    row["summary"],
                    row["raw_period_text"],
                    row["raw_target_text"],
                    row["raw_realm_text"],
                    row["chunk_text"],
                )
                if part
            ),
        )
        recency = _recency_score(row["published_at"], latest_ts)
        policy_bonus = _policy_bonus(row, policy_applied, query_plan.query_topic_keys)
        structured_bonus = _structured_bonus(query_plan, row)
        final_score = (
            similarity * weights["similarity"]
            + recency * weights["recency"]
            + policy_bonus * weights["policy"]
            + structured_bonus * weights["structured"]
        )
        scored_hits.append(
            SearchHit(
                source_type="event_record",
                source_id=int(row["event_record_id"]),
                chunk_id=int(row["chunk_id"]) if row["chunk_id"] is not None else None,
                patch_title=row["patch_title"],
                published_at=row["published_at"],
                url=row["url"],
                section_title=row["section_title"],
                chunk_text=row["chunk_text"],
                topic_types=_parse_csv(row["topic_types"]),
                topic_keys=_parse_csv(row["topic_keys"]),
                event_type=row["event_type"],
                event_title=row["event_title"],
                start_at=row["start_at"],
                end_at=row["end_at"],
                target_scope=row["target_scope"],
                realm_scope=row["realm_scope"],
                limit_per_account=row["limit_per_account"],
                policy="preserve_history",
                similarity=similarity,
                recency=recency,
                policy_bonus=policy_bonus,
                structured_bonus=structured_bonus,
                final_score=final_score,
            )
        )

    # 중복 제거 (패치노트 ID별로 가장 점수 높은 것만 유지)
    unique_hits: dict[str, SearchHit] = {}
    for hit in scored_hits:
        # URL 또는 patch_title을 기준으로 중복 체크
        key = hit.url or hit.patch_title
        if key not in unique_hits or hit.final_score > unique_hits[key].final_score:
            unique_hits[key] = hit
    
    final_candidates = list(unique_hits.values())
    final_candidates.sort(key=lambda hit: (hit.final_score, hit.published_at or ""), reverse=True)
    
    selected_hits = final_candidates[:top_k]
    if policy_applied == "preserve_history":
        if query_plan.event_type_hints or filters.topic_type in EVENT_TOPIC_TYPES:
            selected_hits.sort(
                key=lambda hit: (
                    0 if hit.source_type == "event_record" else 1,
                    hit.published_at or "",
                )
            )
        else:
            selected_hits.sort(key=lambda hit: hit.published_at or "")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return HybridSearchResult(
        hits=tuple(selected_hits),
        policy_applied=policy_applied,
        total_hits=total_hits,
        sql_hits=total_hits,
        vector_hits=len(sparse_scores),
        dense_hits=len(dense_scores),
        merged_candidates=len(merged_rows) + len(event_candidates),
        rerank_weights=weights,
        elapsed_ms=elapsed_ms,
    )


def run_hybrid_search(
    question: str,
    *,
    filters: SearchFilters | None = None,
    top_k: int | None = None,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> HybridSearchResult:
    return hybrid_search(
        question,
        filters=filters,
        top_k=top_k,
        db_path=db_path,
        index_path=index_path,
    )
