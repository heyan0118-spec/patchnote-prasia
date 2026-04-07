# Team Start Here

## 현재 프로젝트 상태
- 공식 `update` / `notice` 게시판을 SQLite로 수집하는 파이프라인이 구현되어 있다.
- 검색은 `chunk + event_records + sparse/dense hybrid` 구조다.
- API는 `POST /query`, `GET /query/debug`를 제공한다.
- 현재 메인 DB는 `patch_notes 1322`, `update 104`, `notice 1218` 기준이다.

## 먼저 읽을 문서
1. `docs/team-start-here.md`
2. `README.md`
3. `HANDOFF.md`
4. `architecture.md`
5. `docs/search-improvement-spec.md`
6. `docs/query-optimization-plan.md`
7. `docs/review-workflow.md`

## 주요 코드 위치
- 수집: `src/patchnote_prasia/crawler.py`, `src/patchnote_prasia/ingest.py`
- 저장/조회: `src/patchnote_prasia/storage.py`, `src/patchnote_prasia/db.py`
- 분석/이벤트 추출: `src/patchnote_prasia/analyze.py`, `src/patchnote_prasia/events.py`
- 검색: `src/patchnote_prasia/search.py`, `src/patchnote_prasia/vector_index.py`, `src/patchnote_prasia/dense_index.py`
- 인터페이스: `src/patchnote_prasia/cli.py`, `src/patchnote_prasia/api.py`
- 테스트: `tests/`

## 바로 실행
```bash
py -3 -m pytest -q
py -3 scripts/check_counts.py
py -3 scripts/check_latest_run.py
py -3 scripts/check_board_parity.py --board update
py -3 scripts/check_board_parity.py --board notice
py -3 -m patchnote_prasia.cli search "클래스 체인지 진행 기간 알려줘"
uvicorn patchnote_prasia.api:app --reload
```

## 현재 기준선
- 이 문서 기준 최신 확인값은 2026-03-30 작업 상태다.
- 현재 전체 테스트 기준선: `py -3 -m pytest -q` → `42 passed`
- 현재 최신 ingestion run 기준선:
  - `#6 success | update-reconcile`
  - `스캔 104 / 신규 4 / 갱신 99 / 오류 0`
- 새 작업 시작 전에는 위 명령들을 먼저 다시 돌려 현재 상태를 확인하는 것을 권장한다.

## 지금 중요한 운영 규칙
- 최신성 질문은 `prefer_latest`
- 이벤트/히스토리 질문은 `preserve_history`
- 최적화는 정확도 가드를 통과한 범위만 진행
- 이미 안 바뀐 영역은 전체 재검토하지 말고 `docs/review-workflow.md` 기준으로 변경 범위만 재증명
- 답변에 근거 링크를 붙일 때는 문장 끝에 `[L](https://...)` 형식을 사용
- 여러 근거가 있으면 문장별로 가장 직접적인 링크를 `[L]`로 붙이는 것을 우선
- 사용자 요청이 `프라시아`로 시작하면 이 프로젝트 폴더를 먼저 참고한다.
- 이때는 `README.md`, `HANDOFF.md`를 먼저 보고, 필요할 때만 다른 문서와 코드/DB까지 내려간다.
- 불필요한 전체 리커시브 검색은 피한다.

## 현재 품질 보호선
- 대표 회귀 케이스:
  - `2025년 클래스 체인지 진행 기간 정리해줘`
- 기대 조건:
  - `event_record`가 상위 결과를 차지해야 함
  - 기대 회차 수와 `start_at`, `end_at`가 모두 맞아야 함
  - 인덱스 캐시는 재사용되어야 하고, 파일 변경 시 자동 무효화되어야 함

## 추천 작업 분담
- 이벤트 추출 정밀도 개선
  - `events.py`, `test_search_quality.py`
- 검색 성능 개선
  - `search.py`, `storage.py`, `vector_index.py`, `dense_index.py`
  - 단, gold query set 유지 필수
- 답변층 개선
  - `api.py`, `cli.py`, `test_api.py`
- 운영 자동화
  - ingest 배치, 점검 스크립트, 문서 정합성 유지

## 주의할 점
- 실제 숫자나 적재 현황을 문서에 적을 때는 `scripts/check_counts.py`, `scripts/check_docs_consistency.py`로 맞춰야 한다.
- `search.py` 최적화 시 history 질의 recall을 깎으면 안 된다.
- `event_records`만 믿지 말고 chunk 근거 경로가 여전히 보완 역할을 해야 한다.
