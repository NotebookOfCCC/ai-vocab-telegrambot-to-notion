"""Tests for NotionHandler.count_entries_per_db()"""
import pytest
from unittest.mock import MagicMock, patch


def _make_handler(db_ids):
    from shared.notion_handler import NotionHandler
    with patch("shared.notion_handler.Client"):
        handler = NotionHandler.__new__(NotionHandler)
        handler.client = MagicMock()
        handler.database_id = db_ids[0]
        handler.all_database_ids = db_ids
        handler._category_options = None
        return handler


def _make_page(title):
    return {
        "properties": {
            "English": {
                "type": "title",
                "title": [{"plain_text": title}]
            }
        }
    }


def test_count_single_db_two_entries():
    handler = _make_handler(["db1"])
    handler.client.databases.query.return_value = {
        "results": [_make_page("hello"), _make_page("world")],
        "has_more": False,
    }
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 2}


def test_count_skips_config_pages():
    handler = _make_handler(["db1"])
    handler.client.databases.query.return_value = {
        "results": [_make_page("hello"), _make_page("__CONFIG_review_schedule__")],
        "has_more": False,
    }
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 1}


def test_count_multiple_dbs():
    handler = _make_handler(["db1", "db2"])
    def query_side_effect(database_id, **kwargs):
        if database_id == "db1":
            return {"results": [_make_page("a"), _make_page("b"), _make_page("c")], "has_more": False}
        return {"results": [_make_page("x")], "has_more": False}
    handler.client.databases.query.side_effect = query_side_effect
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 3, "db2": 1}


def test_count_pagination():
    """Pagination: second page fetched when has_more is True."""
    handler = _make_handler(["db1"])
    call_count = [0]
    def query_side_effect(database_id, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "results": [_make_page("a"), _make_page("b")],
                "has_more": True,
                "next_cursor": "cursor123",
            }
        # Second call must include the cursor
        assert kwargs.get("start_cursor") == "cursor123"
        return {
            "results": [_make_page("c")],
            "has_more": False,
        }
    handler.client.databases.query.side_effect = query_side_effect
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 3}
    assert call_count[0] == 2


def test_count_api_error_returns_none():
    """API error mid-query returns None for that db, not a partial count."""
    handler = _make_handler(["db1"])
    handler.client.databases.query.side_effect = Exception("Notion 500")
    counts = handler.count_entries_per_db()
    assert counts == {"db1": None}


def test_count_empty_database():
    """Empty database returns 0."""
    handler = _make_handler(["db1"])
    handler.client.databases.query.return_value = {
        "results": [],
        "has_more": False,
    }
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 0}
