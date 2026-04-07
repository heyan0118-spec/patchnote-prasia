-- 프라시아 전기 패치노트 검색 서비스 최소 스키마
-- 초기 구현은 SQLite 기준으로 작성

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS patch_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site TEXT NOT NULL DEFAULT 'nexon',
    game_code TEXT NOT NULL DEFAULT 'prasia-electric',
    source_board TEXT NOT NULL DEFAULT 'update',
    external_id TEXT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    content_hash TEXT,
    raw_html TEXT,
    plain_text TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patch_note_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patch_note_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    section_title TEXT,
    chunk_text TEXT NOT NULL,
    token_count INTEGER,
    embedding_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patch_note_id) REFERENCES patch_notes(id) ON DELETE CASCADE,
    UNIQUE (patch_note_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS topic_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patch_note_id INTEGER NOT NULL,
    chunk_id INTEGER,
    topic_type TEXT NOT NULL,
    topic_key TEXT,
    tag_value TEXT,
    prefer_latest INTEGER NOT NULL DEFAULT 1,
    preserve_history INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patch_note_id) REFERENCES patch_notes(id) ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES patch_note_chunks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS event_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patch_note_id INTEGER NOT NULL,
    chunk_id INTEGER,
    event_type TEXT NOT NULL,
    event_key TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    start_at TEXT,
    end_at TEXT,
    target_scope TEXT,
    realm_scope TEXT,
    limit_per_account INTEGER,
    raw_period_text TEXT,
    raw_target_text TEXT,
    raw_realm_text TEXT,
    is_historical INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (patch_note_id, event_type, event_key),
    FOREIGN KEY (patch_note_id) REFERENCES patch_notes(id) ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES patch_note_chunks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    scanned_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingestion_run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ingestion_run_id) REFERENCES ingestion_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_patch_notes_published_at ON patch_notes(published_at);
CREATE INDEX IF NOT EXISTS idx_patch_notes_title ON patch_notes(title);
CREATE INDEX IF NOT EXISTS idx_chunks_patch_note_id ON patch_note_chunks(patch_note_id);
CREATE INDEX IF NOT EXISTS idx_topic_tags_patch_note_id ON topic_tags(patch_note_id);
CREATE INDEX IF NOT EXISTS idx_topic_tags_chunk_id ON topic_tags(chunk_id);
CREATE INDEX IF NOT EXISTS idx_topic_tags_topic_type ON topic_tags(topic_type);
CREATE INDEX IF NOT EXISTS idx_topic_tags_topic_key ON topic_tags(topic_key);
CREATE INDEX IF NOT EXISTS idx_topic_tags_policy ON topic_tags(prefer_latest, preserve_history);
CREATE INDEX IF NOT EXISTS idx_event_records_event_type ON event_records(event_type);
CREATE INDEX IF NOT EXISTS idx_event_records_event_key ON event_records(event_key);
CREATE INDEX IF NOT EXISTS idx_event_records_patch_note_id ON event_records(patch_note_id);
CREATE INDEX IF NOT EXISTS idx_event_records_period ON event_records(start_at, end_at);

-- 권장 topic_type 예시
-- system, class, event, world_open, balance, item, content, maintenance

-- 정책 예시
-- 일반 시스템 안내: prefer_latest=1, preserve_history=0
-- 이벤트:         prefer_latest=0, preserve_history=1
-- 클래스 변경:     prefer_latest=0, preserve_history=1
-- 월드 오픈:       prefer_latest=0, preserve_history=1
