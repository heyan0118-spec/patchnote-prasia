# Query Optimization Plan

## Goal
- 검색/비교 요청이 많아져도 응답 시간을 줄인다.
- 최적화 때문에 이력 누락이나 기간 파싱 누락이 생기지 않게 한다.

## Accuracy Guard
- 최적화 전에 `gold query set`을 먼저 둔다.
- 대표 질의는 최신형 질문보다 정합성 리스크가 큰 이력/비교형 질의로 잡는다.
- 현재 1차 보호 케이스:
  - `2025년 클래스 체인지 진행 기간 정리해줘`
- 검증 기준:
  - 기대 회차 수가 모두 나와야 한다.
  - 각 회차의 `start_at`, `end_at`가 기대값과 일치해야 한다.
  - 상위 결과가 `event_record` 경로를 우선으로 유지해야 한다.

## Safe Optimizations First
1. index process cache
   - 요청마다 sparse/dense index 파일을 다시 읽지 않는다.
   - 파일 시그니처가 바뀌면 자동으로 새로 로드한다.
2. query plan 1회 계산
   - query tag, topic key, preserve-history 여부, question token을 한 번만 계산한다.
3. 질의 정규화 확장
   - 한국어 게임 용어의 붙여쓰기/띄어쓰기 변형을 자동 생성해 함께 검색한다.
   - 예: `백색증표` ↔ `백색 증표`, `클래스체인지` ↔ `클래스 체인지`
   - 원문 질의와 정규화 후보 질의 결과를 병합 재랭킹한다.
4. quality regression
   - 캐시/정규화 도입 후에도 gold query set 결과가 바뀌지 않아야 한다.

## Deferred Until Recall Guard Expands
- 후보를 공격적으로 줄이는 SQL 1차 retrieval
- dense/sparse brute-force 제거
- compare 전용 응답 모델
- excerpt 기본화

## Task Gate
- 각 최적화 태스크는 구현 후 아래를 통과해야 한다.
  - 관련 단위 테스트
  - gold query set 회귀 테스트
  - 서브 에이전트 2명 `CLEAN`
