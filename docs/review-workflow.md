# Review Workflow

전체 재검토를 줄이고 `변경된 부분 중심으로 재증명`하기 위한 운영 규칙이다.

## 원칙
- 코드 수정 후에는 수정 파일과 직접 영향 범위만 다시 검토한다.
- 전체 테스트는 마일스톤 종료 시점에만 1회 실행한다.
- DB/API 사실 확인은 반복 쿼리 대신 검증 스크립트 출력 1회로 대체한다.
- 문서 수정 후에는 수정한 문단과 숫자 블록만 다시 확인한다.
- 이전에 닫힌 이슈도, 직접 수정한 파일이나 그 영향 범위가 바뀌면 다시 열 수 있다.

## 기본 절차
1. 변경 파일 식별
2. 관련 테스트만 실행
3. 운영 사실 확인
4. 필요한 경우에만 전체 테스트

## 검증 스크립트
```bash
py -3 scripts/check_counts.py
py -3 scripts/check_latest_run.py
py -3 scripts/check_board_parity.py --board update
py -3 scripts/check_board_parity.py --board notice
py -3 scripts/check_docs_consistency.py
```

## 권장 사용
- ingestion 변경:
  - 관련 테스트
  - `check_latest_run.py`
  - `check_board_parity.py`
- 문서 숫자 수정:
  - `check_docs_consistency.py`
- 데이터 현황 보고:
  - `check_counts.py`
