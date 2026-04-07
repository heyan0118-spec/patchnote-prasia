from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchnote_prasia.config import database, nexon_api
from patchnote_prasia.review_checks import board_parity, dump_json

DEFAULT_BOARD_IDS = {
    "update": "2830",
    "notice": "2829",
}


def _default_board_id(board_key: str) -> str | None:
    for key, board_id in nexon_api.board_targets:
        if key == board_key:
            return board_id
    return DEFAULT_BOARD_IDS.get(board_key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", required=True, help="board key, e.g. update or notice")
    parser.add_argument("--board-id", default=None, help="override board id")
    args = parser.parse_args()

    board_id = args.board_id or _default_board_id(args.board)
    if board_id is None:
        raise SystemExit(f"Unknown board key: {args.board}")

    print(dump_json(board_parity(args.board, board_id, database.path)))
