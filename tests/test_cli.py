from pathlib import Path

from click.testing import CliRunner

from patchnote_prasia import cli
from patchnote_prasia.search import HybridSearchResult, SearchHit
from patchnote_prasia.db import get_connection


def test_status_initializes_missing_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "status.db"

    def _temp_connection():
        return get_connection(db_path)

    monkeypatch.setattr(cli, "get_connection", _temp_connection)

    runner = CliRunner()
    result = runner.invoke(cli.main, ["status"])

    assert result.exit_code == 0
    assert "수집 이력 없음." in result.output


def test_index_command_prints_rebuild_summary(monkeypatch) -> None:
    index_stub = type(
        "IndexStub",
        (),
        {"documents": {1: object()}, "idf": {"a": 1.0, "b": 2.0}},
    )()
    dense_stub = type("DenseStub", (), {"chunk_ids": (1,)})()
    monkeypatch.setattr(
        cli,
        "build_vector_index",
        lambda: index_stub,
    )
    monkeypatch.setattr(
        cli,
        "build_dense_index",
        lambda: dense_stub,
    )

    runner = CliRunner()
    result = runner.invoke(cli.main, ["index"])

    assert result.exit_code == 0
    assert "sparse 1건 / dense 1건 / 토큰 2개" in result.output


def test_search_command_prints_hits(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "hybrid_search",
        lambda *args, **kwargs: HybridSearchResult(
            hits=(
                SearchHit(
                    chunk_id=1,
                    patch_title="테스트 패치노트",
                    published_at="2026-03-29T00:00:00+09:00",
                    url="https://example.test/1",
                    section_title="거래소",
                    chunk_text="거래소 수수료가 조정되었습니다.",
                    topic_types=("system",),
                    topic_keys=("system",),
                    policy="prefer_latest",
                    similarity=0.8,
                    recency=1.0,
                    policy_bonus=1.0,
                    final_score=0.9,
                ),
            ),
            policy_applied="prefer_latest",
            total_hits=1,
            sql_hits=1,
            vector_hits=1,
            merged_candidates=1,
            rerank_weights={"similarity": 0.4, "recency": 0.4, "policy": 0.2},
            elapsed_ms=5,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli.main, ["search", "거래소 수수료 알려줘"])

    assert result.exit_code == 0
    assert "policy=prefer_latest" in result.output
    assert "테스트 패치노트" in result.output
