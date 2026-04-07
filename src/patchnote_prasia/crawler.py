"""넥슨 커뮤니티 API를 통한 패치노트 수집."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import httpx
from bs4 import BeautifulSoup

from .analyze import normalize_plain_text
from .config import nexon_api

KST = timezone(timedelta(hours=9))


@dataclass
class PatchListItem:
    """목록 API에서 추출한 패치노트 요약."""

    thread_id: str
    board_key: str
    board_id: str
    title: str
    published_at: datetime
    url: str


@dataclass
class PatchDetail:
    """상세 API에서 추출한 패치노트 전문."""

    thread_id: str
    board_key: str
    board_id: str
    title: str
    published_at: datetime
    url: str
    raw_html: str
    plain_text: str
    content_hash: str


def _api_headers() -> dict[str, str]:
    return {
        "x-inface-api-key": nexon_api.api_key,
        "community-id": nexon_api.community_id,
        "User-Agent": nexon_api.user_agent,
    }


def _epoch_to_datetime(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=KST)


def _board_url_segment(board_key: str) -> str:
    return board_key


# ── 목록 수집 ──────────────────────────────────────────────


def _parse_threads(data: dict, *, board_key: str, board_id: str) -> list[PatchListItem]:
    items: list[PatchListItem] = []
    for t in data.get("threads", []):
        items.append(
            PatchListItem(
                thread_id=str(t["threadId"]),
                board_key=board_key,
                board_id=board_id,
                title=t["title"],
                published_at=_epoch_to_datetime(t["createDate"]),
                url=f"https://wp.nexon.com/news/{_board_url_segment(board_key)}/{t['threadId']}",
            )
        )
    return items


def fetch_board_list(
    client: httpx.Client,
    *,
    board_key: str,
    board_id: str,
    max_items: int | None = None,
) -> list[PatchListItem]:
    """전체 목록을 가져온다.

    넥슨 API는 pageNo=1만 지원하므로 pageSize=100으로 최대한 가져온 뒤,
    남은 항목은 blockStartKey 기반으로 추가 요청한다.
    """
    PAGE_SIZE = 100  # API 최대 허용 값
    requested_page_size = min(PAGE_SIZE, max_items) if max_items is not None else PAGE_SIZE

    page_no = 1
    params: dict[str, object] = {
        "paginationType": "PAGING",
        "pageSize": requested_page_size,
        "blockSize": requested_page_size,
        "communityId": nexon_api.community_id,
        "boardId": board_id,
        "reqStr": "npsnUser",
        "pageNo": page_no,
    }
    resp = client.get(
        f"{nexon_api.base_url}/board/{board_id}/threadsV2",
        params=params,
    )
    resp.encoding = "utf-8"
    resp.raise_for_status()
    data = resp.json()

    all_items = _parse_threads(data, board_key=board_key, board_id=board_id)
    total = int(data.get("totalElements", len(all_items)))

    # blockStartKey를 이용해 나머지 가져오기
    seen_ids = {it.thread_id for it in all_items}
    while len(all_items) < total:
        if max_items is not None and len(all_items) >= max_items:
            break
        threads = data.get("threads", [])
        if not threads:
            break
        block_start_key = data.get("blockStartKey")
        block_start_no = data.get("blockStartNo")
        if not block_start_key or block_start_no is None:
            break
        page_no += 1

        time.sleep(0.5)
        params_next: dict[str, object] = {
            "paginationType": "PAGING",
            "pageSize": requested_page_size,
            "blockSize": requested_page_size,
            "communityId": nexon_api.community_id,
            "boardId": board_id,
            "reqStr": "npsnUser",
            "pageNo": page_no,
            "blockStartNo": block_start_no,
        }
        params_next["blockStartKey"] = block_start_key
        resp = client.get(
            f"{nexon_api.base_url}/board/{board_id}/threadsV2",
            params=params_next,
        )
        resp.raise_for_status()
        data = resp.json()
        new_items = _parse_threads(data, board_key=board_key, board_id=board_id)
        if not new_items:
            break
        # 중복 제거
        added = 0
        for it in new_items:
            if it.thread_id not in seen_ids:
                seen_ids.add(it.thread_id)
                all_items.append(it)
                added += 1
                if max_items is not None and len(all_items) >= max_items:
                    break
        if added == 0:
            break

    if max_items is not None:
        all_items = all_items[:max_items]

    return all_items


def fetch_all_list(
    client: httpx.Client, *, max_items: int | None = None
) -> list[PatchListItem]:
    items: list[PatchListItem] = []
    for board_key, board_id in nexon_api.board_targets:
        board_items = fetch_board_list(
            client,
            board_key=board_key,
            board_id=board_id,
            max_items=max_items,
        )
        items.extend(board_items)
    items.sort(key=lambda item: item.published_at, reverse=True)
    if max_items is not None:
        return items[:max_items]
    return items


# ── 상세 수집 ──────────────────────────────────────────────


def _html_to_plain(html: str) -> str:
    """HTML 본문을 정제된 텍스트로 변환한다."""
    soup = BeautifulSoup(html, "lxml")
    # 이미지 alt 텍스트 보존
    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        if alt:
            img.replace_with(f"[이미지: {alt}]")
        else:
            img.decompose()
    return normalize_plain_text(soup.get_text(separator="\n", strip=True))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def fetch_detail(
    client: httpx.Client,
    thread_id: str,
    *,
    board_key: str = "update",
    board_id: str | None = None,
) -> PatchDetail:
    """개별 패치노트 전문을 가져온다."""
    params = {
        "threadId": thread_id,
        "country": "KR",
        "reqStr": "npsnUser",
    }
    resp = client.get(
        f"{nexon_api.base_url}/thread/{thread_id}",
        params=params,
    )
    resp.encoding = "utf-8"  # 명시적 인코딩 설정
    resp.raise_for_status()
    t = resp.json()

    raw_html = t.get("content", "")
    plain = _html_to_plain(raw_html)

    return PatchDetail(
        thread_id=str(t["threadId"]),
        board_key=board_key,
        board_id=board_id or nexon_api.board_id,
        title=t["title"],
        published_at=_epoch_to_datetime(t["createDate"]),
        url=f"https://wp.nexon.com/news/{_board_url_segment(board_key)}/{t['threadId']}",
        raw_html=raw_html,
        plain_text=plain,
        content_hash=_content_hash(plain),
    )


def make_client() -> httpx.Client:
    """API 호출용 httpx 클라이언트를 생성한다."""
    return httpx.Client(
        headers=_api_headers(),
        timeout=30.0,
    )
