"""CLI 엔트리포인트."""

from __future__ import annotations

import logging
import sys

import click

from .db import get_connection, init_db
from .dense_index import build_dense_index
from .enrich import run_enrichment
from .ingest import run_ingestion
from .search import SearchFilters, hybrid_search
from .vector_index import build_vector_index


def _safe_console_text(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="디버그 로그 출력")
def main(verbose: bool) -> None:
    """프라시아 전기 패치노트 수집기."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@main.command()
def init() -> None:
    """DB 스키마를 초기화한다."""
    conn = get_connection()
    init_db(conn)
    conn.close()
    click.echo("DB 초기화 완료.")


@main.command()
@click.option("--max-items", type=int, default=None, help="수집할 최대 항목 수")
@click.option("--run-type", default="manual", help="실행 유형 (manual/scheduled)")
def ingest(max_items: int | None, run_type: str) -> None:
    """패치노트를 수집하여 DB에 저장한다."""
    result = run_ingestion(run_type=run_type, max_items=max_items)
    click.echo(f"\n수집 결과: {result['status']}")
    click.echo(f"  스캔: {result.get('scanned', 0)}")
    click.echo(f"  신규: {result.get('inserted', 0)}")
    click.echo(f"  갱신: {result.get('updated', 0)}")
    click.echo(f"  오류: {result.get('errors', 0)}")


@main.command()
def status() -> None:
    """최근 수집 실행 상태를 확인한다."""
    conn = get_connection()
    init_db(conn)
    rows = conn.execute(
        """SELECT id, run_type, started_at, finished_at, status,
                  scanned_count, inserted_count, updated_count, error_count
           FROM ingestion_runs ORDER BY id DESC LIMIT 5"""
    ).fetchall()
    conn.close()

    if not rows:
        click.echo("수집 이력 없음.")
        return

    for r in rows:
        click.echo(
            f"[#{r['id']}] {r['status']} | {r['run_type']} | "
            f"시작: {r['started_at']} | "
            f"스캔 {r['scanned_count']} / 신규 {r['inserted_count']} / "
            f"갱신 {r['updated_count']} / 오류 {r['error_count']}"
        )


@main.command()
def index() -> None:
    """로컬 벡터 인덱스를 재빌드한다."""
    index = build_vector_index()
    dense_index = build_dense_index()
    click.echo(
        f"검색 인덱스 재빌드 완료: sparse {len(index.documents)}건 / "
        f"dense {len(dense_index.chunk_ids)}건 / 토큰 {len(index.idf)}개"
    )


@main.command()
@click.argument("question")
@click.option("--topic-type", default=None, help="토픽 필터")
@click.option("--date-from", default=None, help="시작일 필터 (ISO)")
@click.option("--date-to", default=None, help="종료일 필터 (ISO)")
@click.option("--top-k", type=int, default=None, help="반환 청크 수")
def search(
    question: str,
    topic_type: str | None,
    date_from: str | None,
    date_to: str | None,
    top_k: int | None,
) -> None:
    """하이브리드 검색 결과를 확인한다."""
    result = hybrid_search(
        question,
        filters=SearchFilters(
            topic_type=topic_type,
            date_from=date_from,
            date_to=date_to,
        ),
        top_k=top_k,
    )

    click.echo(f"policy={result.policy_applied}")
    click.echo(
        f"sql_hits={result.sql_hits} vector_hits={result.vector_hits} dense_hits={result.dense_hits} "
        f"merged={result.merged_candidates}"
    )
    for hit in result.hits:
        click.echo(
            f"- {hit.published_at} | {hit.patch_title} | source={hit.source_type} | "
            f"score={hit.final_score:.3f} | topics={','.join(hit.topic_types)}"
        )
        if hit.event_type:
            click.echo(
                f"  event={hit.event_type} period={hit.start_at or '-'}~{hit.end_at or '-'} "
                f"limit={hit.limit_per_account or '-'}"
            )
            if hit.target_scope or hit.realm_scope:
                click.echo(
                    f"  target={_safe_console_text(hit.target_scope or '-')} "
                    f"realm={_safe_console_text(hit.realm_scope or '-')}"
                )
        click.echo(f"  {_safe_console_text(hit.chunk_text[:160])}")


@main.command()
@click.option("--force", is_flag=True, help="이미 분석된 문서도 다시 처리")
@click.option("--limit", type=int, default=None, help="처리할 최대 문서 수")
def enrich(force: bool, limit: int | None) -> None:
    """기존 패치노트의 청크와 토픽 태그를 생성한다."""
    result = run_enrichment(force=force, limit=limit)
    click.echo(f"청크/태깅 처리 완료: {result['processed']}건")


if __name__ == "__main__":
    main()
