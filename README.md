# 프라시아 전기 패치노트 검색 서비스

프라시아 전기 공식 `업데이트`/`공지사항` 페이지(`https://wp.nexon.com/news/update`, `https://wp.nexon.com/news/notice`)를 수집해 이력을 저장하고, 자연어 질문에 대해 **정확도 우선**으로 답하는 로컬 우선 검색 서비스다.

## 목표
- 공식 패치노트 원문과 메타데이터를 지속 수집
- 패치노트 이력 전체 보관
- 자연어 질의 지원
- **최신 우선 규칙**: 같은 주제의 반복 안내는 기본적으로 최신 기준을 우선 답변
- **누적 보존 규칙**: 이벤트, 클래스 변경, 신규 월드 오픈은 비슷해 보여도 히스토리를 누적해 답변
- 매주 **수요일 오전** 신규 패치노트 체크 및 반영

## 현재 구현
- SQLite 기반 원문/청크/태그 저장
- `update` / `notice` 다중 게시판 수집 지원
- `event_records` 기반 canonical 이벤트 레코드 추출
- 로컬 sparse TF-IDF + dense LSA 하이브리드 검색
- sparse/dense 인덱스 프로세스 캐시
- 질의 분석 `QueryPlan` 1회 계산
- 규칙 기반 재랭킹
  - 기본 `prefer_latest`
  - 이벤트/클래스/월드 오픈 계열 `preserve_history`
  - 이벤트성 history 질의에서 `event_record` 우선 정렬
- CLI와 FastAPI `POST /query`, `GET /query/debug`
- 수집 후 인덱스 자동 재빌드
- 변경 범위 중심 검증 스크립트

## 디렉터리 기준
- `README.md` — 프로젝트 개요와 구현 우선순위
- `HANDOFF.md` — 현재 구현 상태, 데이터 현황, 운영 규칙, 다음 작업
- `architecture.md` — 시스템 설계와 질의 처리 규칙
- `schema.sql` — 최소 스키마
- `.env.example` — 로컬 실행용 환경 변수 예시
- `docs/ingestion-strategy.md` — 수집/정규화 전략
- `docs/review-workflow.md` — 변경 범위 중심 검증 절차
- `docs/query-optimization-plan.md` — 검색 최적화 기준과 정확도 보호선
- `docs/team-start-here.md` — 팀원용 빠른 시작 문서

## 핵심 데이터 계층
- `patch_notes`: 원문, 메타데이터
  - `source_board`로 `update` / `notice` 구분
- `patch_note_chunks`: 섹션/문단 청크
- `topic_tags`: 토픽 태그와 정책 플래그
- `event_records`: `class_change`, `attendance_event`, `boosting_event`, `transfer_event`, `season_event`, `world_open_event` 등 구조화 이벤트 레코드

## 답변 정책 예시
- "지금 거래소 수수료가 어떻게 돼?" → 최신 문서 기준으로 현재 규칙 우선 답변
- "최근 향사수 변경 내역 정리해줘" → 클래스 변경 이력을 날짜순 누적 요약
- "월드 오픈 히스토리 알려줘" → 신규 월드 오픈은 과거 포함 누적 정리
- "이번 이벤트 뭐 있었어?" → 이벤트는 기간/보상/시작일 기준으로 다건 정리

## 실행
```bash
py -3 -m patchnote_prasia.cli status
py -3 -m patchnote_prasia.cli enrich --force
py -3 -m patchnote_prasia.cli search "클래스 체인지 진행 기간 알려줘"
uvicorn patchnote_prasia.api:app --reload
```

## 운영 메모
- 사용자 요청이 `프라시아`로 시작하면 다른 일반 소스보다 이 프로젝트 폴더(`patchnote-prasia`)를 먼저 참고한다.
- 우선순위는 `README.md` → `HANDOFF.md` → `architecture.md` → 필요한 코드/DB 순서다.
- 불필요한 전체 리커시브 검색은 피하고, 알려진 문서/파일부터 확인한다.

`.env`에서 `NEXON_BOARD_TARGETS=update:2830,notice:2829`처럼 설정하면 다중 게시판 수집이 가능합니다.

현재 메인 DB에는 `update 104건`, `notice 1218건`, 총 `1322건`이 적재되어 있습니다.

현재 회귀 보호선:
- `2025년 클래스 체인지 진행 기간 정리해줘` gold query set
- 캐시 재사용 / 파일 변경 시 cache invalidation 테스트
- 문서 숫자 / board parity / 최신 run 검증 스크립트

## 남은 작업
1. 검색 응답 문장 품질 고도화
2. 이벤트 슬롯 추출 정밀도 개선
3. 2단계 retrieval 전환
4. 수요일 스케줄러/배치 자동화
5. 필요 시 OpenAI 또는 sentence-transformers 계열 dense backend 확장

## 과하게 만들지 않기
초기 버전에서는 아래는 미뤄도 된다.
- 복잡한 분산 큐
- 다중 워커
- 실시간 스트리밍 파이프라인
- 과도한 마이크로서비스 분리

로컬에서 한 프로세스 또는 2개 프로세스(수집기 / 질의 서비스) 정도면 충분하다.
