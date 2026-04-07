import os
import sys
import logging
from pathlib import Path

# Add src to PYTHONPATH
src_path = str(Path(__file__).parent.parent / "src")
sys.path.insert(0, src_path)

from patchnote_prasia.db import get_connection, init_db
from patchnote_prasia.ingest import run_ingestion
from patchnote_prasia.enrich import run_enrichment
from patchnote_prasia.vector_index import build_vector_index
from patchnote_prasia.dense_index import build_dense_index

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamFileHandler if hasattr(logging, 'StreamFileHandler') else logging.StreamHandler(sys.stdout),
        logging.FileHandler("ingestion_master.log", encoding="utf-8")
    ]
)
log = logging.getLogger("master_ingest")

def main():
    try:
        log.info("=== [1단계] DB 초기화 시작 ===")
        conn = get_connection()
        init_db(conn)
        conn.close()
        log.info("DB 초기화 완료.")

        log.info("=== [2단계] 전체 데이터 수집 시작 (약 15~20분 소요) ===")
        ingest_result = run_ingestion(run_type="manual")
        log.info(f"수집 결과: {ingest_result['status']} (신규: {ingest_result.get('inserted', 0)})")

        log.info("=== [3단계] 데이터 분석 및 청크 생성 시작 ===")
        enrich_result = run_enrichment(force=True)
        log.info(f"분석 완료: {enrich_result['processed']}건 처리됨")

        log.info("=== [4단계] 검색 인덱스 빌드 시작 ===")
        vector_idx = build_vector_index()
        dense_idx = build_dense_index()
        log.info(f"인덱스 빌드 완료: Sparse {len(vector_idx.documents)} / Dense {len(dense_idx.chunk_ids)}")

        log.info("=== [성공] 모든 작업이 완료되었습니다! ===")
        print("\n[SUCCESS] 이제 대시보드에서 깨끗한 한글 데이터를 검색하실 수 있습니다.")

    except Exception as e:
        log.error(f"작업 중 오류 발생: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
