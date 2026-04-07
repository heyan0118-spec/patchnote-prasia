from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchnote_prasia.config import database
from patchnote_prasia.review_checks import collect_latest_run, dump_json


if __name__ == "__main__":
    print(dump_json(collect_latest_run(database.path)))
