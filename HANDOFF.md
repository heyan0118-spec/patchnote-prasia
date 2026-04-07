# 프라시아 전기 패치노트 프로젝트 HANDOFF

> **문서 버전**: v0.4
> **최종 수정**: 2026-03-30
> **변경 이력**: v0.1 초안 작성 / v0.2 토픽 분류표·API 스펙·재랭킹·에러 전략·크롤링 제약 추가 / v0.3 구현 현행화 / v0.4 멀티보드 적재, 검증 스크립트, 정확도 가드, 안전 최적화 반영

## 현재 상태
- 프로젝트 목적: 프라시아 전기 공식 `업데이트`/`공지사항` 페이지(`https://wp.nexon.com/news/update`, `https://wp.nexon.com/news/notice`)를 수집해 이력을 저장하고, 자연어 질의에 대해 정확도 높은 답변을 제공.
- 현재 단계: **수집기/SQLite 적재/청크/태깅/event_records/sparse+dense 검색/FastAPI/테스트까지 구현 완료**.
- 현재 데이터 상태:
  - `patch_notes`: 1322
  - `patch_note_chunks`: 13313
  - `topic_tags`: 22015
  - `event_records`: 816
  - `source_board='update'`: 104
  - `source_board='notice'`: 1218
- 최근 추가 상태:
  - `update` / `notice` 멀티보드 적재 완료
  - `board parity` 검증 스크립트 추가
  - 문서 숫자 정합성 검증 스크립트 추가
  - 검색 hot path 안전 최적화 1차 적용
    - sparse/dense 인덱스 프로세스 캐시
    - 질의 분석 `QueryPlan` 1회 계산
    - 이벤트성 history 질의에서 `event_record` 우선 정렬
  - gold query set 기반 정확도 보호선 추가

## 생성된 작업 폴더
- 워킹트리/프로젝트 폴더:
  - `C:\Users\drkim\.openclaw\workspace\patchnote-prasia`

## 현재 생성된 파일
- `README.md`
- `architecture.md`
- `schema.sql`
- `.env.example`
- `docs/ingestion-strategy.md`
- `HANDOFF.md` (이 문서)
- `src/patchnote_prasia/config.py`
- `src/patchnote_prasia/db.py`
- `src/patchnote_prasia/crawler.py`
- `src/patchnote_prasia/storage.py`
- `src/patchnote_prasia/ingest.py`
- `src/patchnote_prasia/cli.py`
- `src/patchnote_prasia/analyze.py`
- `src/patchnote_prasia/enrich.py`
- `src/patchnote_prasia/events.py`
- `src/patchnote_prasia/vector_index.py`
- `src/patchnote_prasia/dense_index.py`
- `src/patchnote_prasia/search.py`
- `src/patchnote_prasia/api.py`
- `src/patchnote_prasia/review_checks.py`
- `tests/test_config.py`
- `tests/test_analyze.py`
- `tests/test_api.py`
- `tests/test_cli.py`
- `tests/test_crawler.py`
- `tests/test_enrich.py`
- `tests/test_search.py`
- `tests/test_storage.py`
- `tests/test_search_quality.py`
- `tests/test_vector_index.py`
- `tests/test_review_checks.py`
- `scripts/check_counts.py`
- `scripts/check_latest_run.py`
- `scripts/check_board_parity.py`
- `scripts/check_docs_consistency.py`
- `docs/search-improvement-spec.md`
- `docs/review-workflow.md`
- `docs/query-optimization-plan.md`
- `docs/team-start-here.md`
- `data/prasia_patchnotes.db`

## 지금까지 합의/설계된 핵심 방향

### 제품 목적
- 패치노트 기록을 저장
- 자연어 질의 지원
- 정확도 높은 응답
- 공식 출처 링크 포함
- 매주 수요일 오전 신규 패치노트 확인 및 반영

### 데이터 소스
- Nexon 공식 게시판
  - `https://wp.nexon.com/news/update`
  - `https://wp.nexon.com/news/notice`

### 현재 아키텍처
- 저장소: `SQLite`
- 수집 소스:
  - `update` (`boardId=2830`)
  - `notice` (`boardId=2829`)
- 검색:
  - 청크 기반 sparse TF-IDF + char ngram
  - 청크 기반 dense LSA (`scikit-learn` TF-IDF + `TruncatedSVD`)
  - `event_records` canonical layer
  - 프로세스 레벨 index cache
  - `QueryPlan` 기반 단일 질의 해석
- 서비스 형태:
  - CLI + FastAPI
- API:
  - `POST /query`
  - `GET /query/debug`

## 핵심 정책

### 1) 최신 우선
동일/유사 주제의 반복 안내는 **최신 기준으로 우선 응답**.
적용 예:
- 시스템 규칙
- 상시 콘텐츠/운영 규칙
- UI/편의 기능
- 일반 이용 안내

### 2) 누적 보존
겉으로 비슷해 보여도 **히스토리 누적 관리/응답**해야 하는 항목:
- 이벤트
- 클래스 변경 / 밸런스 조정
- 신규 월드 오픈

### 3) 혼합 응답 가능
질문 의도에 따라:
- 현재 기준 요약 + 과거 이력
- 최신 우선 + 히스토리 비교
를 함께 보여줄 수 있도록 설계

## 설계 문서 요약

### `README.md`
- 프로젝트 목표
- MVP 범위
- 하이브리드 검색 방향
- 수요일 오전 배치 확인
- 최신 우선 / 누적 보존 규칙 요약

### `architecture.md`
- Ingestion Worker / Structured Store / Vector Index / Query Service 구성
- 데이터 흐름
- 최신 우선 vs 히스토리 누적 정책
- 질의 처리 전략과 재랭킹 방향

### `schema.sql`
최소 스키마 포함:
- `patch_notes`
- `patch_note_chunks`
- `topic_tags`
- `event_records`
- `ingestion_runs`
- `ingestion_items`

정책용 필드:
- `topic_key`
- `prefer_latest`
- `preserve_history`

### `.env.example`
- 소스 URL
- SQLite 경로
- 스케줄 cron
- 정책 플래그
- 임베딩/LLM 관련 예시 변수

### `docs/ingestion-strategy.md`
- 목록 → 상세 → 정규화 → 청크 → 태깅 → 임베딩 흐름
- URL + content hash 기반 중복 방지

## 질의 정책(대화 중 확정된 방향)
- 질의 스타일은 **검색형 + 비서형 둘 다 지원**
- 내부 구조는 검색형(근거 중심) 기반 위에 비서형 설명 계층을 얹는 방식 권장
- 응답은 되도록 아래 형식 유지 권장:
  1. 한 줄 결론
  2. 근거 요약
  3. 정책 기준(최신 우선/누적형)
  4. 원문 링크
- 근거 링크 표기 규칙:
  - 문장 끝에 `[L](https://...)` 형식으로 삽입
  - `[L]`은 항상 하이퍼링크여야 함
  - 근거가 여러 개면 해당 문장마다 각각 `[L]`을 붙이거나, 문장별로 가장 직접적인 링크를 붙임
  - 예시:
    - 올인원부스팅 월드는 메르비스 월드로 통합됩니다. `[L](https://wp.nexon.com/news/notice/3311746)`
    - 이동하지 않은 스탠더님은 메르비스05(평화)로 통합됩니다. `[L](https://wp.nexon.com/news/notice/3388955)`

## 현재 구현된 이벤트 타입
- `class_change`
- `class_change_return`
- `attendance_event`
- `boosting_event`
- `transfer_event`
- `season_event`
- `world_open_event`

## 현재 남은 다음 단계
1. 이벤트 슬롯 추출 정확도 보정
2. 답변 생성층 고도화
3. 2단계 retrieval 전환
4. 배치 스케줄링/운영 자동화
5. dense backend 확장 옵션 추가
6. 질의 정규화 강화 (붙여쓰기/띄어쓰기 변형, 동의어 사전)

## 팀 작업 시작 전 권장 읽기 순서
1. `docs/team-start-here.md`
2. `README.md`
3. `HANDOFF.md`
4. `architecture.md`
5. `docs/search-improvement-spec.md`
6. `docs/query-optimization-plan.md`
7. `docs/review-workflow.md`

## 운영 규칙 추가
- 사용자 요청이 `프라시아`로 시작하면, 다른 일반 웹/수동 소스보다 이 프로젝트 폴더를 먼저 참고한다.
- 참고 순서는 문서 우선(`README.md`, `HANDOFF.md`, `architecture.md`)이며, 그 다음에 필요한 코드/DB를 본다.
- 불필요한 전체 리커시브 검색은 지양하고, 이미 알려진 파일 경로와 문서부터 확인한다.

## 토픽 분류표

| topic_type    | 판별 키워드/패턴 예시                                  | prefer_latest | preserve_history |
|---------------|-------------------------------------------------------|:---:|:---:|
| system        | 시스템, 이용 안내, UI, 편의기능, 거래소, 우편         | 1   | 0   |
| class         | 직업명(아처, 메이지 등), 스킬, 전직                    | 0   | 1   |
| balance       | 밸런스, 상향, 하향, 조정, 너프, 버프                   | 0   | 1   |
| event         | 이벤트, 출석, 보상, 기간 한정, 쿠폰                    | 0   | 1   |
| world_open    | 월드 오픈, 신규 서버, 신규 월드                         | 0   | 1   |
| item          | 아이템, 장비, 소비, 드롭, 교환                          | 1   | 0   |
| content       | 던전, 레이드, 퀘스트, 필드, 보스                        | 1   | 0   |
| maintenance   | 점검, 긴급점검, 정기점검, 서버 작업                     | 1   | 0   |

> 한 청크에 복수 태그 가능. 키워드 매칭 우선, 향후 LLM 보조 분류로 교체 가능.

## MVP 질의 API 스펙

### `POST /query`

요청:
```json
{
  "question": "최근 아처 변경 내역 알려줘",
  "filters": {
    "topic_type": "class",
    "date_from": "2025-01-01",
    "date_to": null
  },
  "top_k": 8
}
```
- `question` (필수): 자연어 질문
- `filters` (선택): 구조화 필터. 모든 필드 선택.
- `top_k` (선택): 반환 청크 수. 기본값 8.

응답:
```json
{
  "answer": "한 줄 결론",
  "evidence": [
    {
      "patch_title": "2025년 3월 19일 업데이트 안내",
      "published_at": "2025-03-19",
      "url": "https://wp.nexon.com/news/update/... 또는 https://wp.nexon.com/news/notice/...",
      "chunk_text": "관련 원문 발췌",
      "topic_type": "class",
      "policy": "preserve_history",
      "score": 0.87
    }
  ],
  "policy_applied": "preserve_history",
  "total_hits": 12
}
```

### `GET /query/debug?question=...`
위 `/query`와 동일 응답 + 아래 추가:
```json
{
  "debug": {
    "sql_hits": 5,
    "vector_hits": 10,
    "dense_hits": 10,
    "merged_candidates": 12,
    "rerank_weights": {
      "similarity": 0.35,
      "recency": 0.35,
      "policy": 0.15,
      "structured": 0.15
    },
    "elapsed_ms": 142
  }
}
```

## 재랭킹 규칙

점수 산출:
```
final_score = (similarity * W_sim) + (recency * W_rec) + (policy_bonus * W_pol) + (structured_bonus * W_struct)
```

| 조건 | W_sim | W_rec | W_pol | W_struct | 비고 |
|------|:-----:|:-----:|:-----:|:--------:|------|
| `preserve_history = false` (기본) | 0.35 | 0.35 | 0.15 | 0.15 | 최신성 강조 |
| `preserve_history = true`         | 0.35 | 0.10 | 0.30 | 0.25 | 시계열 다양성 우선, 날짜순 정렬 |

- SQL 필터 hit은 후보군 선정 단계에서 사용 (점수가 아닌 필터)
- 벡터 hit은 similarity 점수 원천
- `preserve_history` 결과는 최종 출력 시 날짜 오름차순 재정렬

## 에러 및 재시도 전략

| 실패 유형 | 처리 |
|-----------|------|
| 목록 페이지 요청 실패 | 해당 배치 전체 중단, `ingestion_runs.status = 'list_fetch_failed'` 기록 |
| 상세 페이지 개별 실패 | 해당 URL만 `ingestion_items.status = 'failed'`로 기록, 나머지 계속 진행 |
| 부분 성공 (N건 중 일부 실패) | 성공분은 정상 저장, 실패분은 다음 배치에서 재시도 대상에 자동 포함 |
| 최대 재시도 | URL당 최대 3회. 현재 구현은 `failed` 누적 횟수로만 판별하고, 한도 초과 URL은 실행 중 건너뜀 |

재시도 대상 선별 쿼리:
```sql
SELECT DISTINCT url FROM ingestion_items
WHERE status = 'failed'
GROUP BY url
HAVING COUNT(*) < 3
```

## 크롤링 제약 조건

- **robots.txt**: 수집 전 `https://wp.nexon.com/robots.txt` 확인 후 준수
- **요청 간격**: 상세 페이지 수집 시 요청 간 최소 2초 대기 (`time.sleep(2)`)
- **페이지네이션**: 목록 페이지 구조(페이지 파라미터, 무한스크롤 여부)는 첫 구현 시 실제 HTML 분석 후 확정. HANDOFF 시점에서는 미확인.
- **User-Agent**: `.env`에 명시된 커스텀 UA 사용 (`PrasiaPatchBot/0.1`)

## 검증 상태
- `py -3 -m pytest -q` → `42 passed`
- `py -3 -m patchnote_prasia.cli enrich --force` → 당시 `update` 코퍼스 100건 재처리 성공 이력 있음
- `NEXON_BOARD_TARGETS=notice:2829`로 full ingest 실행 → `notice 1218건`, 최신 API total `1218`과 일치
- `NEXON_BOARD_TARGETS=notice:2829`로 `ingest --max-items 5` 재실행 → `신규 0 / 오류 0` 확인
- `patchnote search`에서 event record 우선 검색 확인

최근 추가 검증:
- `scripts/check_counts.py` → 현재 DB count 출력
- `scripts/check_latest_run.py` → 최신 ingestion run 확인
- `scripts/check_board_parity.py --board update|notice` → API total과 DB count 일치 확인
- `scripts/check_docs_consistency.py` → README/HANDOFF 숫자 정합성 확인
- `py -3 -m pytest tests/test_search_quality.py tests/test_search.py tests/test_vector_index.py tests/test_api.py -q` → `17 passed`

현재 최신 run 기준선:
- `#6 success | update-reconcile`
- 시작: `2026-03-30T07:00:32.153465+09:00`
- 스캔 `104` / 신규 `4` / 갱신 `99` / 오류 `0`

## 현재 정확도 보호선
- 대표 gold query:
  - `2025년 클래스 체인지 진행 기간 정리해줘`
- 보호 조건:
  - 기대 회차 수가 모두 반환되어야 함
  - 각 회차 `start_at`, `end_at`이 기대값과 일치해야 함
  - 상위 결과가 `event_record` 우선이어야 함
  - index cache 재사용 및 파일 변경 시 invalidation이 보장되어야 함

## 변경 범위 중심 검증 원칙
- 이미 안 바뀐 영역은 매번 전체 재검토하지 않는다.
- `docs/review-workflow.md` 기준으로:
  - 변경된 코드
  - 관련 테스트
  - 관련 count/parity/doc consistency
  만 재증명한다.
- 단, 수정이 검색 recall이나 event 추출에 닿으면 gold query set은 반드시 다시 돈다.

## 다음 에이전트에게 넘길 시작 프롬프트 예시
"이 폴더의 docs/team-start-here.md, HANDOFF.md, README.md, architecture.md, docs/search-improvement-spec.md, docs/query-optimization-plan.md를 먼저 읽고 시작해. 현재 구현된 프라시아 전기 패치노트 검색 서비스에서 gold query set을 깨지 않는 범위로 작업해야 한다. 기존 `event_records`, sparse+dense 검색, FastAPI `/query` 구조는 유지하고, 변경 범위 중심 검증과 회귀 테스트를 추가하면서 수정해줘."
