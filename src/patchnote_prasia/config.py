"""프로젝트 설정 로더."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value}")


def _resolve_database_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:"):
        raise ValueError("Only sqlite DATABASE_URL is supported in MVP")

    raw_path = database_url.removeprefix("sqlite:")
    if not raw_path:
        raise ValueError("DATABASE_URL must include a SQLite file path")
    if raw_path == ":memory:":
        return Path(":memory:")
    if raw_path.startswith("///"):
        raw_path = raw_path[3:]
    elif raw_path.startswith("//"):
        raw_path = raw_path[2:]
    elif raw_path.startswith("./"):
        raw_path = raw_path[2:]

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _load_database_path() -> Path:
    database_path = os.getenv("DATABASE_PATH")
    if database_path and database_path.strip():
        path = Path(database_path.strip())
        if path == Path(":memory:"):
            return path
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    database_url = _get_str("DATABASE_URL", "sqlite:./data/prasia_patchnotes.db")
    return _resolve_database_path(database_url)


@dataclass(frozen=True)
class App:
    env: str
    port: int
    timezone: str


@dataclass(frozen=True)
class NexonAPI:
    """넥슨 커뮤니티 API 설정."""

    base_url: str
    api_key: str
    community_id: str
    board_id: str
    board_targets: tuple[tuple[str, str], ...]
    page_size: int
    user_agent: str
    request_delay: float


@dataclass(frozen=True)
class Database:
    path: Path


@dataclass(frozen=True)
class Ingestion:
    max_retries: int


@dataclass(frozen=True)
class Vector:
    backend: str
    index_path: Path
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True)
class Query:
    top_k: int
    hybrid_candidates: int
    rerank_enabled: bool


@dataclass(frozen=True)
class Policy:
    default_prefer_latest: bool
    preserve_history_topics: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    app: App
    nexon_api: NexonAPI
    database: Database
    ingestion: Ingestion
    vector: Vector
    query: Query
    policy: Policy


def _parse_board_targets(raw: str | None, default_board_id: str) -> tuple[tuple[str, str], ...]:
    if raw is None or not raw.strip():
        return (("update", default_board_id),)

    targets: list[tuple[str, str]] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Invalid NEXON_BOARD_TARGETS entry: {item}")
        key, board_id = item.split(":", maxsplit=1)
        key = key.strip()
        board_id = board_id.strip()
        if not key or not board_id:
            raise ValueError(f"Invalid NEXON_BOARD_TARGETS entry: {item}")
        targets.append((key, board_id))

    if not targets:
        return (("update", default_board_id),)
    return tuple(targets)


def load_settings() -> Settings:
    default_board_id = _get_str("NEXON_BOARD_ID", "2830")

    preserve_topics = tuple(
        topic.strip()
        for topic in _get_str(
            "PRESERVE_HISTORY_TOPICS", "event,class,world_open,balance"
        ).split(",")
        if topic.strip()
    )

    return Settings(
        app=App(
            env=_get_str("APP_ENV", "local"),
            port=_get_int("APP_PORT", 3000),
            timezone=_get_str("TZ", "Asia/Seoul"),
        ),
        nexon_api=NexonAPI(
            base_url=_get_str(
                "NEXON_API_BASE",
                "https://public.api.nexon.com/community-ext-api/api/v1",
            ),
            api_key=_get_str(
                "NEXON_API_KEY", "0a1a6fb8-8018-5a01-b9d9-91eabe96a0cc"
            ),
            community_id=_get_str("NEXON_COMMUNITY_ID", "299"),
            board_id=default_board_id,
            board_targets=_parse_board_targets(
                os.getenv("NEXON_BOARD_TARGETS"),
                default_board_id,
            ),
            page_size=_get_int("NEXON_PAGE_SIZE", 100),
            user_agent=_get_str(
                "USER_AGENT",
                "Mozilla/5.0 (compatible; PrasiaPatchBot/0.1; +local)",
            ),
            request_delay=_get_float("REQUEST_DELAY", 2.0),
        ),
        database=Database(path=_load_database_path()),
        ingestion=Ingestion(max_retries=_get_int("MAX_RETRIES", 3)),
        vector=Vector(
            backend=_get_str("VECTOR_BACKEND", "local"),
            index_path=(
                PROJECT_ROOT
                / _get_str("VECTOR_INDEX_PATH", "./data/vector_index.json").removeprefix("./")
            ).resolve(),
            embedding_model=_get_str(
                "EMBEDDING_MODEL", "local-tfidf"
            ),
            embedding_dimensions=_get_int("EMBEDDING_DIMENSIONS", 0),
        ),
        query=Query(
            top_k=_get_int("TOP_K", 8),
            hybrid_candidates=_get_int("HYBRID_CANDIDATES", 30),
            rerank_enabled=_get_bool("RERANK_ENABLE", True),
        ),
        policy=Policy(
            default_prefer_latest=_get_bool("DEFAULT_PREFER_LATEST", True),
            preserve_history_topics=preserve_topics,
        ),
    )


settings = load_settings()
app = settings.app
nexon_api = settings.nexon_api
database = settings.database
ingestion = settings.ingestion
vector = settings.vector
query = settings.query
policy = settings.policy
