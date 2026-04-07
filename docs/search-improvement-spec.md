# 검색 개선 스펙

## 문서 목적
- 현재 `chunk + sparse hybrid` 중심 검색 구조의 한계를 보완한다.
- 운영 이벤트 질의, 기간 질의, 히스토리 질의에 강한 검색 구조로 확장한다.
- 구현을 독립 태스크로 나누고 각 태스크를 검수 가능 상태로 명세한다.

## 문제 정의
현재 검색은 아래 유형에서 일관성이 떨어진다.
- 특정 운영 이벤트의 진행 이력 질의
  - 예: `클래스 체인지 진행한 날짜`, `월드 오픈 히스토리`, `부스팅 기간`
- 기간/대상/횟수 같은 구조화 사실 질의
  - 예: `언제 열렸어`, `몇 번 진행했어`, `어느 월드 대상이었어`
- 동일 키워드가 소개/개선/주의사항/실제 진행 공지에 함께 등장하는 경우
  - 예: `클래스 체인지`가 진행 공지와 제한사항 안내에 모두 등장

핵심 원인:
- 상위 토픽 태그만 있고 운영 이벤트 단위 태그가 없다.
- 기간/대상/렐름/횟수 같은 슬롯이 구조화돼 있지 않다.
- 청크가 검색과 정답 구조를 동시에 떠안고 있다.
- sparse 로컬 인덱스만으로는 표현 다양성과 의미 매칭이 부족하다.
- 질의 의도 분류가 약해 `역대/모두/기간/언제` 질문도 최신 우선으로 기운다.

## 설계 원칙
- 기존 `patch_notes`, `patch_note_chunks`, `topic_tags` 자산은 유지한다.
- 청크 검색은 증거 추출용으로 축소하고, 이벤트 레코드 검색을 추가한다.
- 구조화 질의는 가능한 한 SQL 우선으로 해결한다.
- dense embedding은 sparse와 병행하며, 로컬 우선 구현을 기본으로 둔다.
- 모든 단계는 백필 가능해야 하며 현재 100건 DB에 재적용 가능해야 한다.

## 목표 아키텍처
검색 계층을 3단으로 나눈다.

1. 문서/청크 계층
- 기존 patch note 원문과 청크
- 자유 질의, 근거 표시, 세부 문단 인용에 사용

2. 이벤트 레코드 계층
- 운영 이벤트 단위 canonical record
- 기간/대상/렐름/횟수 조회에 사용

3. 하이브리드 검색 계층
- structured filter + event record lookup + sparse/dense similarity + rerank

## 태스크 분해

### 태스크 A. 이벤트 태그 체계 확장
목표:
- 상위 토픽 외에 검색 의도와 직접 연결되는 운영 이벤트 태그를 추가한다.

1차 도입 대상:
- `class_change`
- `class_change_return`
- `attendance_event`
- `boosting_event`
- `transfer_event`
- `season_event`
- `world_open_event`

출력:
- 기존 `topic_tags.topic_type`에 세부 이벤트 태그를 저장
- 필요 시 `topic_key`에 이벤트 식별 키 저장

검수 기준:
- 단순 소개/제한사항 문장과 실제 진행 공지를 구분한다.
- `class_change`와 `class_change_return`은 별도로 태깅된다.
- 기존 `class`, `event`, `world_open`와 충돌하지 않고 공존한다.

### 태스크 B. 슬롯 추출 정규화 추가
목표:
- 이벤트성 섹션에서 구조화된 슬롯을 추출한다.

추출 대상:
- `event_type`
- `start_at`
- `end_at`
- `target_scope`
- `realm_scope`
- `limit_per_account`
- `source_patch_note_id`
- `source_chunk_id`

권장 해석 규칙:
- `진행 기간`에서 시작/종료 시각 추출
- `대상`에서 클래스/월드/렐름 범위 추출
- `진행 렐름`, `전체 월드`, `아우리엘 ~ 메르비스`, `올인원부스팅 제외` 같은 범위 표현 정규화
- `계정당 최대 N회`, `계정당 1회`, `리턴 1회 가능` 같은 횟수 추출

정규화 포맷:
- `target_scope`와 `realm_scope`는 1차 구현에서 JSON 문자열로 저장한다.
- 공통 포맷:
```json
{
  "mode": "all|include|range",
  "include": ["야만투사", "환영검사"],
  "exclude": ["올인원부스팅"],
  "range": {"from": "아우리엘", "to": "메르비스"},
  "raw": "전체 월드 (올인원부스팅 제외)"
}
```
- `mode=all`: 전체 대상/전체 월드
- `mode=include`: 특정 목록 명시
- `mode=range`: `A ~ B` 형태 구간
- `exclude`: 예외 제외 대상
- `raw`: 원문 표현 보존

datetime 정규화 규칙:
- 모든 datetime은 KST(`+09:00`) 기준 ISO 8601 문자열로 저장한다.
- `점검 후` 시작은 당일 `05:00:00+09:00`를 기본값으로 사용한다.
- `오전 4시 59분까지` 종료는 해당 일시를 그대로 사용한다.
- `점검 전` 종료는 해당 날짜 `04:59:59+09:00`로 저장한다.
- 날짜만 있고 시각이 없는 경우:
  - 시작: `00:00:00+09:00`
  - 종료: `23:59:59+09:00`
- 원문에 시각이 있으면 원문 시각을 우선 사용한다.

검수 기준:
- 날짜가 문자열만 아니라 비교 가능한 ISO datetime으로 저장된다.
- 부분 추출 실패 시에도 레코드는 남기되 실패 필드는 null 허용한다.
- 현재 DB 100건에 대해 재백필 가능하다.

### 태스크 C. Canonical Event Record 계층 도입
목표:
- 이벤트 하나당 검색용 요약 레코드를 별도 저장한다.

권장 신규 테이블:
- `event_records`

권장 필드:
- `id`
- `patch_note_id`
- `chunk_id`
- `event_type`
- `event_key`
- `title`
- `summary`
- `start_at`
- `end_at`
- `target_scope`
- `realm_scope`
- `limit_per_account`
- `raw_period_text`
- `raw_target_text`
- `raw_realm_text`
- `is_historical`
- `created_at`
- `updated_at`

예시:
- `class_change` 이벤트 1회당 1레코드
- `class_change_return`은 별도 레코드

검수 기준:
- 하나의 patch note 안에 이벤트가 2개 이상이면 각각 분리 저장된다.
- SQL만으로 `클래스 체인지 기간`, `역대 월드 오픈`, `출석 이벤트 목록` 질의가 가능해진다.

정합 규칙:
- `event_records.event_type`은 세부 이벤트 태그와 동일한 이벤트 타입을 사용한다.
  - 예: `topic_tags.topic_type = class_change`인 대표 이벤트 청크에서 생성된 레코드는 `event_records.event_type = class_change`
- `event_records.event_key`는 같은 이벤트 회차를 식별하는 정규화 키를 사용한다.
  - 권장 포맷: `{event_type}:{start_at or published_at}:{target_scope or title_slug}`
- 한 이벤트가 다중 청크에 걸쳐 있을 경우 대표 `chunk_id`는 아래 우선순위로 고른다.
  1. `진행 기간` 슬롯을 포함한 청크
  2. `대상` 또는 `진행 렐름` 슬롯을 포함한 청크
  3. 이벤트 헤더가 포함된 가장 앞 청크
- 같은 `patch_note_id + event_type + event_key` 조합은 하나의 레코드만 허용한다.
- 백필/재분석 시 동일 키 레코드는 `UPSERT`로 교체한다.

### 태스크 D. Dense Embedding 병행
목표:
- sparse 인덱스만으로 놓치는 의미 매칭을 보완한다.

전략:
- sparse 인덱스 유지
- dense embedding을 추가 인덱스로 병행
- 질의 시 `structured + sparse + dense` 병합

후보 기술:
- 로컬: `sentence-transformers`
- API: OpenAI embedding

1차 구현 방안:
- `VECTOR_BACKEND=local` 유지
- `DENSE_EMBEDDING_BACKEND=local|openai|disabled`
- dense는 청크와 event record 모두 인덱싱 가능하게 설계

검수 기준:
- dense 비활성 상태에서도 전체 시스템이 동작한다.
- dense 활성 시 인덱스 재빌드/동기화 경로가 분리되어 있다.

저장 모델:
- sparse 인덱스 파일은 기존처럼 `data/vector_index.json`
- dense 청크 인덱스는 별도 파일 `data/dense_chunk_index.json`
- dense event record 인덱스는 별도 파일 `data/dense_event_index.json`
- 각 인덱스 파일은 최소한 아래 메타데이터를 가진다.
  - `version`
  - `backend`
  - `source_type`
  - `built_at`
  - `source_count`
  - `embedding_model`
- dense 인덱스는 DB에 원벡터를 직접 저장하지 않고 파일 기반으로 유지한다.
- 인덱스 버전 동기화는 `built_at`과 `source_count`로 1차 검증하고, 필요 시 별도 `index_builds` 메타 테이블 도입을 허용한다.
- 재빌드 시 sparse/dense는 각각 독립 재생성 가능해야 하지만, `ingest/enrich/backfill` 완료 후 둘 다 최신 버전으로 갱신되어야 한다.

### 태스크 E. 질문 의도 기반 재랭킹 강화
목표:
- 질의 표현만으로 최신 우선/히스토리/구조화 검색 우선순위를 조정한다.

규칙 예시:
- `언제`, `기간`, `역대`, `모두`, `정리`, `몇 번` 포함 시 `preserve_history`
- `현재`, `지금`, `최신`, `현재 기준` 포함 시 `prefer_latest`
- `기간`, `대상`, `렐름`, `횟수` 관련 질문은 event record 우선
- 진행 공지형 청크에 가산점
- 날짜 표현이 있는 청크와 레코드에 가산점

검수 기준:
- `클래스 체인지 진행한 날짜`
- `월드 오픈 히스토리`
- `최근 거래소 수수료`
이 3종이 서로 다른 정책으로 처리된다.

### 태스크 F. API/CLI 응답 개선
목표:
- `/query`, `/query/debug`, CLI가 event record를 우선 활용할 수 있게 한다.

응답 추가 항목:
- `record_type`
- `event_type`
- `start_at`
- `end_at`
- `target_scope`
- `realm_scope`
- `limit_per_account`

정책:
- 구조화 질의는 event record를 우선 증거로 사용
- 청크는 원문 근거로 보조 사용

검수 기준:
- 사용자가 날짜/기간만 묻는 경우 답변 근거가 청크 조각보다 event record 중심으로 나온다.

## 데이터 모델 제안

### 기존 테이블 활용
- `patch_notes`
- `patch_note_chunks`
- `topic_tags`

### 신규 테이블
```sql
CREATE TABLE event_records (
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
```

권장 인덱스:
- `idx_event_records_event_type`
- `idx_event_records_event_key`
- `idx_event_records_period`
- `idx_event_records_patch_note_id`
- `ux_event_records_identity`

## 파이프라인 변경점

### 수집/분석 단계
1. 기존 청크 생성
2. 기존 토픽 태깅
3. 이벤트 태그 추가
4. 이벤트 슬롯 추출
5. `event_records` 생성/교체
6. sparse 인덱스 재빌드
7. dense 인덱스 활성 시 dense 인덱스 재빌드

### 백필 단계
- 현재 100건 전량 재분석
- `topic_tags` 세부 이벤트 태그 보강
- `event_records` 신규 생성
- 인덱스 전면 재빌드

## 검색 전략 변경안

### 질의 분류
출력:
- `intent_type`: `current_state | historical_list | event_lookup | patch_lookup`
- `prefer_history`: bool
- `structured_slots_requested`: list[str]

### 실행 순서
1. 의도 분석
2. event record SQL 검색
3. chunk sparse/dense 검색
4. 후보 병합
5. 정책 기반 재랭킹
6. 답변/증거 조립

### 재랭킹 가중치 방향
- `historical_list`:
  - event record 가산점 높음
  - 기간 정보 포함 가산점
  - 날짜 오름차순 정렬
- `current_state`:
  - 최신성 가중치 높음
  - event record보다 최신 패치 청크 우선 가능

## 테스트 계획

### 단위 테스트
- 이벤트 태그 분류
- 기간/대상/렐름/횟수 파싱
- `class_change`와 `class_change_return` 구분
- 의도 분류 규칙
- sparse/dense 병합 점수 계산

### 통합 테스트
- 백필 후 `event_records` 생성 확인
- `클래스 체인지 진행한 날짜`
- `클래스 체인지 리턴 기간`
- `최근 거래소 수수료`
- `역대 월드 오픈`
- `출석 이벤트 기간`

### 회귀 테스트
- 기존 `ingest`, `enrich`, `index`, `search`, `/query`, `/query/debug`
- dense 비활성 상태 fallback

게이트 기준:
- 백필 후 `event_records`는 최소 1건 이상이 아니라, 검증용 fixture DB에서 기대 건수와 정확히 일치해야 한다.
- 실데이터 백필 기준으로 `class_change` 실제 진행 회차는 최소 5건 복원돼야 한다.
- `클래스 체인지 진행한 날짜` 질의는 상위 근거 3건 안에 event record가 포함되어야 한다.
- `클래스 체인지 리턴 기간` 질의는 `class_change_return` event record를 우선 근거로 사용해야 한다.
- `최근 거래소 수수료` 질의는 event record가 아니라 최신 청크/문서 근거가 우선이어야 한다.
- dense 비활성 상태와 활성 상태 둘 다 회귀 테스트를 분리 수행해야 하며, 비활성 상태는 기존 sparse 기반 테스트를 전부 통과해야 한다.

## 완료 판정 기준
- `class_change` 실제 진행 회차를 구조화 레코드로 정확히 복원한다.
- `클래스 체인지 진행한 날짜/기간` 질의가 청크 우연 매칭이 아니라 event record 기반으로 답된다.
- `역대`형 질문은 `preserve_history`로 일관 처리된다.
- dense 비활성 상태에서도 시스템이 동작한다.
- 백필 포함 전체 테스트가 통과한다.

## 이번 작업의 구현 순서
1. `event_records` 스키마 추가
2. `analyze`에 이벤트 태그/슬롯 추출 추가
3. 백필 경로 연결
4. event record SQL 검색 계층 추가
5. dense embedding 옵션 설계 및 기본 비활성 추가
6. rerank 의도 규칙 강화
7. API/CLI 응답 확장
8. 테스트와 문서 업데이트
