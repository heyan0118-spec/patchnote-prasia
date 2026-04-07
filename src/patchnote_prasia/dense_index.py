"""로컬 dense 임베딩 인덱스."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import joblib
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import vector
from .db import get_connection, init_db
from .storage import list_chunks_for_index
from .vector_index import _resolve_index_path

MAX_COMPONENTS = 128


@dataclass(frozen=True)
class LocalDenseIndex:
    index_path: Path
    vectorizer: TfidfVectorizer
    projector: TruncatedSVD | None
    chunk_ids: tuple[int, ...]
    matrix: np.ndarray

    def search(
        self,
        question: str,
        *,
        candidate_ids: set[int] | None = None,
        top_k: int = 30,
    ) -> dict[int, float]:
        if not self.chunk_ids:
            return {}

        query_matrix = self.vectorizer.transform([question])
        query_vector = (
            self.projector.transform(query_matrix)[0]
            if self.projector is not None
            else query_matrix.toarray()[0]
        )
        query_norm = float(np.linalg.norm(query_vector))
        if query_norm == 0.0:
            return {}

        matrix = self.matrix
        doc_norms = np.linalg.norm(matrix, axis=1)
        scores = matrix @ query_vector
        denom = doc_norms * query_norm
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.divide(scores, denom, out=np.zeros_like(scores), where=denom > 0)

        ranked: list[tuple[int, float]] = []
        for idx, chunk_id in enumerate(self.chunk_ids):
            if candidate_ids is not None and chunk_id not in candidate_ids:
                continue
            score = float(scores[idx])
            if score > 0:
                ranked.append((chunk_id, score))

        ranked.sort(key=lambda item: item[1], reverse=True)
        return dict(ranked[:top_k])


class _CacheEntry(NamedTuple):
    signature: tuple[bool, int, int]
    index: LocalDenseIndex


_INDEX_CACHE: dict[Path, _CacheEntry] = {}


def _dense_index_path(
    *,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> Path:
    base = _resolve_index_path(db_path=db_path, index_path=index_path)
    return base.with_suffix(".dense.joblib")


def _file_signature(path: Path) -> tuple[bool, int, int]:
    if not path.exists():
        return (False, 0, 0)
    stat = path.stat()
    return (True, stat.st_mtime_ns, stat.st_size)


def build_dense_index(
    *,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> LocalDenseIndex:
    resolved_path = _dense_index_path(db_path=db_path, index_path=index_path)
    conn = get_connection(db_path)
    init_db(conn)
    rows = list_chunks_for_index(conn)
    conn.close()

    texts: list[str] = []
    chunk_ids: list[int] = []
    for row in rows:
        chunk_ids.append(int(row["chunk_id"]))
        texts.append(
            " ".join(
                part
                for part in (
                    row["title"],
                    row["section_title"],
                    row["chunk_text"],
                )
                if part
            )
        )

    if not texts:
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))
        payload = {
            "chunk_ids": [],
            "vectorizer": vectorizer,
            "projector": None,
            "matrix": np.zeros((0, 0), dtype=float),
        }
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(payload, resolved_path)
        index = LocalDenseIndex(
            resolved_path,
            vectorizer,
            None,
            (),
            payload["matrix"],
        )
        _INDEX_CACHE[resolved_path] = _CacheEntry(
            signature=_file_signature(resolved_path),
            index=index,
        )
        return index

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))
    tfidf = vectorizer.fit_transform(texts)
    projector: TruncatedSVD | None = None
    matrix: np.ndarray

    max_rank = min(tfidf.shape[0] - 1, tfidf.shape[1] - 1, MAX_COMPONENTS)
    if max_rank >= 2:
        projector = TruncatedSVD(n_components=max_rank, random_state=42)
        matrix = projector.fit_transform(tfidf)
    else:
        matrix = tfidf.toarray()

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "chunk_ids": chunk_ids,
            "vectorizer": vectorizer,
            "projector": projector,
            "matrix": matrix,
        },
        resolved_path,
    )
    index = LocalDenseIndex(
        resolved_path,
        vectorizer,
        projector,
        tuple(chunk_ids),
        np.asarray(matrix, dtype=float),
    )
    _INDEX_CACHE[resolved_path] = _CacheEntry(
        signature=_file_signature(resolved_path),
        index=index,
    )
    return index


def load_dense_index(
    index_path: Path | None = None,
    *,
    db_path: Path | None = None,
) -> LocalDenseIndex:
    resolved_path = _dense_index_path(db_path=db_path, index_path=index_path)
    signature = _file_signature(resolved_path)
    cached = _INDEX_CACHE.get(resolved_path)
    if cached is not None and cached.signature == signature:
        return cached.index
    if not resolved_path.exists():
        return LocalDenseIndex(
            resolved_path,
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5)),
            None,
            (),
            np.zeros((0, 0), dtype=float),
        )

    payload = joblib.load(resolved_path)
    index = LocalDenseIndex(
        resolved_path,
        payload["vectorizer"],
        payload["projector"],
        tuple(int(chunk_id) for chunk_id in payload["chunk_ids"]),
        np.asarray(payload["matrix"], dtype=float),
    )
    _INDEX_CACHE[resolved_path] = _CacheEntry(signature=signature, index=index)
    return index
