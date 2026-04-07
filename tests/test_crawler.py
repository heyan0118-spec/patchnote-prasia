from datetime import datetime, timezone, timedelta

from patchnote_prasia.crawler import _parse_threads, fetch_board_list, fetch_detail


KST = timezone(timedelta(hours=9))


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if isinstance(self.payload, list):
            index = min(len(self.calls) - 1, len(self.payload) - 1)
            return _DummyResponse(self.payload[index])
        return _DummyResponse(self.payload)


def test_parse_threads_uses_board_specific_notice_url():
    items = _parse_threads(
        {
            "threads": [
                {
                    "threadId": 12345,
                    "title": "공지 제목",
                    "createDate": int(datetime(2026, 3, 29, tzinfo=KST).timestamp()),
                }
            ]
        },
        board_key="notice",
        board_id="2829",
    )

    assert items[0].board_key == "notice"
    assert items[0].board_id == "2829"
    assert items[0].url == "https://wp.nexon.com/news/notice/12345"


def test_fetch_detail_uses_board_specific_notice_url():
    client = _DummyClient(
        {
            "threadId": 54321,
            "title": "공지 제목",
            "createDate": int(datetime(2026, 3, 29, tzinfo=KST).timestamp()),
            "content": "<p>공지 본문</p>",
        }
    )

    detail = fetch_detail(client, "54321", board_key="notice", board_id="2829")

    assert detail.board_key == "notice"
    assert detail.board_id == "2829"
    assert detail.url == "https://wp.nexon.com/news/notice/54321"


def test_fetch_board_list_limits_requests_when_max_items_is_set():
    client = _DummyClient(
        {
            "threads": [
                {
                    "threadId": 100,
                    "title": "공지 1",
                    "createDate": int(datetime(2026, 3, 29, tzinfo=KST).timestamp()),
                },
                {
                    "threadId": 101,
                    "title": "공지 2",
                    "createDate": int(datetime(2026, 3, 28, tzinfo=KST).timestamp()),
                },
            ],
            "totalElements": 200,
        }
    )

    items = fetch_board_list(
        client,
        board_key="notice",
        board_id="2829",
        max_items=1,
    )

    assert len(items) == 1
    assert len(client.calls) == 1
    assert client.calls[0]["kwargs"]["params"]["pageSize"] == 1


def test_fetch_board_list_uses_page_no_with_block_markers_for_follow_up_page():
    client = _DummyClient(
        [
            {
                "threads": [
                    {
                        "threadId": 100,
                        "title": "공지 1",
                        "createDate": int(datetime(2026, 3, 29, tzinfo=KST).timestamp()),
                    }
                ],
                "totalElements": 2,
                "blockStartKey": ["253402300799", "9223372036854775807"],
                "blockStartNo": 1,
            },
            {
                "threads": [
                    {
                        "threadId": 101,
                        "title": "공지 2",
                        "createDate": int(datetime(2026, 3, 28, tzinfo=KST).timestamp()),
                    }
                ],
                "totalElements": 2,
                "blockStartKey": ["253402300799", "9223372036854775807"],
                "blockStartNo": 2,
            },
        ]
    )

    items = fetch_board_list(
        client,
        board_key="notice",
        board_id="2829",
    )

    assert [item.thread_id for item in items] == ["100", "101"]
    assert len(client.calls) == 2
    second_params = client.calls[1]["kwargs"]["params"]
    assert second_params["pageNo"] == 2
    assert second_params["blockStartNo"] == 1
    assert second_params["blockStartKey"] == ["253402300799", "9223372036854775807"]
