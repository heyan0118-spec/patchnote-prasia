"""로컬 sparse 벡터 인덱스."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .config import vector
from .db import get_connection, init_db
from .storage import list_chunks_for_index

TOKEN_PATTERN = re.compile(r"[가-힣A-Za-z0-9]+")


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: int
    norm: float
    weights: dict[str, float]


@dataclass(frozen=True)
class LocalVectorIndex:
    index_path: Path
    idf: dict[str, float]
    documents: dict[int, IndexedChunk]

    def search(
        self,
        question: str,
        *,
        candidate_ids: set[int] | None = None,
        top_k: int = 30,
    ) -> dict[int, float]:
        query_counts = _feature_counts(question)
        if not query_counts:
            return {}

        query_weights = _tfidf_weights(query_counts, self.idf)
        query_norm = _vector_norm(query_weights)
        if query_norm == 0:
            return {}

        scored: list[tuple[int, float]] = []
        for chunk_id, document in self.documents.items():
            if candidate_ids is not None and chunk_id not in candidate_ids:
                continue
            score = _cosine_similarity(
                query_weights,
                query_norm,
                document.weights,
                document.norm,
            )
            if score > 0:
                scored.append((chunk_id, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return dict(scored[:top_k])


class _CacheEntry(NamedTuple):
    signature: tuple[bool, int, int]
    index: LocalVectorIndex


_INDEX_CACHE: dict[Path, _CacheEntry] = {}


def _resolve_index_path(
    *,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> Path:
    if index_path is not None:
        return index_path
    if db_path is None:
        return vector.index_path
    return db_path.with_name(f"{db_path.stem}.vector_index.json")


def _file_signature(path: Path) -> tuple[bool, int, int]:
    if not path.exists():
        return (False, 0, 0)
    stat = path.stat()
    return (True, stat.st_mtime_ns, stat.st_size)


def _character_ngrams(token: str) -> list[str]:
    if len(token) < 2:
        return []
    upper = min(len(token), 4)
    grams: list[str] = []
    for size in range(2, upper + 1):
        for idx in range(0, len(token) - size + 1):
            grams.append(f"c:{token[idx:idx + size]}")
    return grams


def _feature_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in TOKEN_PATTERN.findall(text.lower()):
        counts[f"t:{token}"] += 1
        for gram in _character_ngrams(token):
            counts[gram] += 1
    return counts


def _tfidf_weights(
    feature_counts: Counter[str],
    idf: dict[str, float],
) -> dict[str, float]:
    total = sum(feature_counts.values())
    if total == 0:
        return {}

    weights: dict[str, float] = {}
    for feature, count in feature_counts.items():
        if feature not in idf:
            continue
        tf = count / total
        weights[feature] = tf * idf[feature]
    return weights


def _vector_norm(weights: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in weights.values()))


def _cosine_similarity(
    left_weights: dict[str, float],
    left_norm: float,
    right_weights: dict[str, float],
    right_norm: float,
) -> float:
    if left_norm == 0 or right_norm == 0:
        return 0.0
    overlap = set(left_weights) & set(right_weights)
    if not overlap:
        return 0.0
    dot = sum(left_weights[key] * right_weights[key] for key in overlap)
    return dot / (left_norm * right_norm)


def build_vector_index(
    *,
    db_path: Path | None = None,
    index_path: Path | None = None,
) -> LocalVectorIndex:
    if vector.backend != "local":
        raise ValueError("Only local sparse vector backend is implemented.")

    resolved_index_path = _resolve_index_path(db_path=db_path, index_path=index_path)
    conn = get_connection(db_path)
    init_db(conn)
    rows = list_chunks_for_index(conn)
    conn.close()

    document_features: dict[int, Counter[str]] = {}
    doc_frequency: Counter[str] = Counter()
    for row in rows:
        chunk_id = int(row["chunk_id"])
        text = " ".join(
            part
            for part in (
                row["title"],
                row["section_title"],
                row["chunk_text"],
            )
            if part
        )
        features = _feature_counts(text)
        document_features[chunk_id] = features
        for feature in features:
            doc_frequency[feature] += 1

    doc_count = max(len(document_features), 1)
    idf = {
        feature: math.log((1 + doc_count) / (1 + frequency)) + 1.0
        for feature, frequency in doc_frequency.items()
    }
    documents = {
        chunk_id: IndexedChunk(
            chunk_id=chunk_id,
            weights=(weights := _tfidf_weights(features, idf)),
            norm=_vector_norm(weights),
        )
        for chunk_id, features in document_features.items()
    }

    resolved_index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "backend": "local-sparse",
        "idf": idf,
        "documents": {
            str(chunk_id): {
                "norm": document.norm,
                "weights": document.weights,
            }
            for chunk_id, document in documents.items()
        },
    }
    resolved_index_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    index = LocalVectorIndex(resolved_index_path, idf, documents)
    _INDEX_CACHE[resolved_index_path] = _CacheEntry(
        signature=_file_signature(resolved_index_path),
        index=index,
    )
    return index


def load_vector_index(
    index_path: Path | None = None,
    *,
    db_path: Path | None = None,
) -> LocalVectorIndex:
    resolved_index_path = _resolve_index_path(db_path=db_path, index_path=index_path)
    signature = _file_signature(resolved_index_path)
    cached = _INDEX_CACHE.get(resolved_index_path)
    if cached is not None and cached.signature == signature:
        return cached.index
    if not resolved_index_path.exists():
        return build_vector_index(db_path=db_path, index_path=resolved_index_path)

    payload = json.loads(resolved_index_path.read_text(encoding="utf-8"))
    documents = {
        int(chunk_id): IndexedChunk(
            chunk_id=int(chunk_id),
            norm=float(doc["norm"]),
            weights={key: float(value) for key, value in doc["weights"].items()},
        )
        for chunk_id, doc in payload["documents"].items()
    }
    idf = {key: float(value) for key, value in payload["idf"].items()}
    index = LocalVectorIndex(resolved_index_path, idf, documents)
    _INDEX_CACHE[resolved_index_path] = _CacheEntry(signature=signature, index=index)
    return index


def build_local_vector_index() -> dict[str, int]:
    index = build_vector_index()
    return {
        "document_count": len(index.documents),
        "token_count": len(index.idf),
    }
