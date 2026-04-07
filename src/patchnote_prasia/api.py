"""FastAPI query API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .search import HybridSearchResult, SearchFilters, hybrid_search


class QueryFiltersModel(BaseModel):
    topic_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    filters: QueryFiltersModel | None = None
    top_k: int | None = Field(default=None, ge=1, le=30)


class EvidenceItem(BaseModel):
    source_type: str
    patch_title: str
    published_at: str | None
    url: str
    chunk_text: str
    topic_type: str | None
    event_type: str | None = None
    event_title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    target_scope: str | None = None
    realm_scope: str | None = None
    limit_per_account: int | None = None
    policy: str
    score: float


class DebugInfo(BaseModel):
    sql_hits: int
    vector_hits: int
    dense_hits: int
    merged_candidates: int
    rerank_weights: dict[str, float]
    elapsed_ms: int


class QueryResponse(BaseModel):
    answer: str
    evidence: list[EvidenceItem]
    policy_applied: str
    total_hits: int
    debug: DebugInfo | None = None


def _build_answer(result: HybridSearchResult) -> str:
    if not result.hits:
        return "관련 패치노트를 찾지 못했습니다."

    first = result.hits[0]
    if result.policy_applied == "preserve_history":
        return f"관련 이력 {len(result.hits)}건을 날짜순으로 정리했습니다."
    return f"가장 관련 높은 최신 근거는 '{first.patch_title}'입니다."


def _to_response(result: HybridSearchResult, *, include_debug: bool) -> QueryResponse:
    evidence = [
        EvidenceItem(
            source_type=hit.source_type,
            patch_title=hit.patch_title,
            published_at=hit.published_at,
            url=hit.url,
            chunk_text=hit.chunk_text,
            topic_type=hit.topic_types[0] if hit.topic_types else None,
            event_type=hit.event_type,
            event_title=hit.event_title,
            start_at=hit.start_at,
            end_at=hit.end_at,
            target_scope=hit.target_scope,
            realm_scope=hit.realm_scope,
            limit_per_account=hit.limit_per_account,
            policy=hit.policy,
            score=round(hit.final_score, 4),
        )
        for hit in result.hits
    ]
    debug = None
    if include_debug:
        debug = DebugInfo(
            sql_hits=result.sql_hits,
            vector_hits=result.vector_hits,
            dense_hits=result.dense_hits,
            merged_candidates=result.merged_candidates,
            rerank_weights=result.rerank_weights,
            elapsed_ms=result.elapsed_ms,
        )

    return QueryResponse(
        answer=_build_answer(result),
        evidence=evidence,
        policy_applied=result.policy_applied,
        total_hits=result.total_hits,
        debug=debug,
    )


def create_app(
    *,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Patchnote Prasia API", version="0.1.0")

    # CORS 미들웨어 추가 (로컬 및 배포 환경 필수)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/query", response_model=QueryResponse)
    def query_endpoint(payload: QueryRequest) -> QueryResponse:
        filters = SearchFilters(**payload.filters.model_dump()) if payload.filters else None
        result = hybrid_search(
            payload.question,
            filters=filters,
            top_k=payload.top_k,
            db_path=db_path,
            index_path=index_path,
        )
        return _to_response(result, include_debug=False)

    @app.get("/query/debug", response_model=QueryResponse)
    def query_debug_endpoint(
        question: str = Query(min_length=1),
        topic_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        top_k: int | None = Query(default=None, ge=1, le=30),
    ) -> QueryResponse:
        result = hybrid_search(
            question,
            filters=SearchFilters(
                topic_type=topic_type,
                date_from=date_from,
                date_to=date_to,
            ),
            top_k=top_k,
            db_path=db_path,
            index_path=index_path,
        )
        return _to_response(result, include_debug=True)

    return app


app = create_app()
