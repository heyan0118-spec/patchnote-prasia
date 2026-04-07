from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchnote_prasia.config import PROJECT_ROOT, database
from patchnote_prasia.review_checks import compare_doc_counts, dump_json


if __name__ == "__main__":
    print(dump_json(compare_doc_counts(PROJECT_ROOT, database.path)))
