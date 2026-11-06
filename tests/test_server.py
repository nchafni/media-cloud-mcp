"""Tool tests over an in-memory MCP connection.

Only the HTTP layer is replaced, so the real `mediacloud` client still runs. That catches
drift in its method signatures and its date handling.
"""

import datetime as dt
import json
import sys
from typing import Any
from unittest.mock import MagicMock

import mediacloud.api
import mediacloud.error
import pytest
import requests
from mcp import Client, StdioServerParameters
from mcp_types import TextContent

from media_cloud_mcp.client import reset_clients
from media_cloud_mcp.server import mcp

pytestmark = pytest.mark.anyio

SCOPE = {
    "query": '"climate change"',
    "start_date": "2023-11-01",
    "end_date": "2023-12-01",
    "collection_ids": [34412234],
}
STORY = {
    "id": "abc",
    "title": "A story",
    "url": "https://example.com/a",
    "language": "en",
    "media_name": "example.com",
    "media_url": "example.com",
    "publish_date": "2023-11-02 00:00:00",
    "indexed_date": "2023-11-03T04:05:06.123456+00:00",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_clients():
    reset_clients()
    yield
    reset_clients()


@pytest.fixture
def api(monkeypatch):
    """Replace the HTTP layer with a mock keyed on endpoint."""
    monkeypatch.setenv("MC_API_KEY", "test-key")
    responses: dict[str, Any] = {}
    calls: list[tuple[str, dict | None]] = []

    def fake_query(self, endpoint, params=None, method="GET"):
        calls.append((endpoint, params))
        response = responses[endpoint]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(mediacloud.api.BaseApi, "_query", fake_query)
    mock = MagicMock()
    mock.responses = responses
    mock.calls = calls
    return mock


def api_error(status: int, note: str | None = "details") -> mediacloud.error.APIResponseError:
    response = MagicMock(status_code=status)
    return mediacloud.error.APIResponseError(response, {}, {"note": note})


async def call(name: str, arguments: dict[str, Any] | None = None):
    async with Client(mcp) as client:
        return await client.call_tool(name, arguments or {})


def error_text(result) -> str:
    assert result.is_error
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def test_all_tools_are_listed_and_read_only():
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "check_connection",
        "count_stories",
        "count_stories_over_time",
        "count_stories_by_source_over_time",
        "list_stories",
        "sample_stories",
        "get_story",
        "top_words",
        "top_sources",
        "top_languages",
        "search_collections",
        "get_collection",
        "search_sources",
        "get_source",
        "list_feeds",
    }
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.description


async def test_query_guide_resource():
    async with Client(mcp) as client:
        result = await client.read_resource("mediacloud://query-guide")
    assert "article_title" in result.contents[0].text


async def test_count_stories_adds_ratio_and_sends_scope(api):
    api.responses["search/total-count"] = {"count": {"relevant": 25, "total": 100}}
    result = await call("count_stories", SCOPE)
    assert result.structured_content == {"relevant": 25, "total": 100, "ratio": 0.25}
    endpoint, params = api.calls[-1]
    assert endpoint == "search/total-count"
    assert params["start"] == "2023-11-01"
    assert params["end"] == "2023-12-01"
    assert params["cs"] == ("34412234",)


async def test_count_stories_with_empty_scope_has_no_ratio(api):
    api.responses["search/total-count"] = {"count": {"relevant": 0, "total": 0}}
    result = await call("count_stories", {**SCOPE, "collection_ids": None})
    assert result.structured_content["ratio"] is None


async def test_count_over_time_serializes_dates(api):
    api.responses["search/count-over-time"] = {
        "count_over_time": {
            "counts": [{"date": "2023-11-01 00:00:00", "count": 1, "total_count": 2, "ratio": 0.5}]
        }
    }
    result = await call("count_stories_over_time", SCOPE)
    assert result.structured_content["counts"][0]["date"] == "2023-11-01"
    json.dumps(result.structured_content)


async def test_source_over_time_passes_interval_and_truncates(api):
    rows = [{"media_name": f"s{i}", "ratio": 0.1} for i in range(3)]
    api.responses["search/count-by-source-over-interval"] = {"source-interval-attention": rows}
    result = await call(
        "count_stories_by_source_over_time", {**SCOPE, "interval": "day", "max_rows": 2}
    )
    assert api.calls[-1][1]["interval"] == "day"
    content = result.structured_content
    assert len(content["rows"]) == 2
    assert content["total_rows"] == 3
    assert content["truncated"] is True


async def test_list_stories_maps_parameters_and_serializes_dates(api):
    api.responses["search/story-list"] = {
        "stories": [dict(STORY)],
        "pagination_token": "next",
    }
    result = await call(
        "list_stories",
        {
            **SCOPE,
            "page_size": 10,
            "sort_order": "asc",
            "randomized": True,
            "include_text": True,
            "pagination_token": "prev",
        },
    )
    assert not result.is_error
    params = api.calls[-1][1]
    assert params["page_size"] == 10
    assert params["sort_order"] == "asc"
    assert params["randomize"] == 1
    assert params["expanded"] == 1
    assert params["pagination_token"] == "prev"
    content = result.structured_content
    assert content["next_page_token"] == "next"
    assert content["stories"][0]["publish_date"] == "2023-11-02"
    assert content["stories"][0]["indexed_date"] == "2023-11-03T04:05:06.123456+00:00"


async def test_list_stories_defaults_to_a_bounded_page_without_text(api):
    api.responses["search/story-list"] = {"stories": [], "pagination_token": None}
    await call("list_stories", SCOPE)
    params = api.calls[-1][1]
    assert params["page_size"] == 100
    assert "expanded" not in params
    assert "randomize" not in params


async def test_sample_stories(api):
    api.responses["search/sample"] = {"sample": [dict(STORY)]}
    result = await call("sample_stories", {**SCOPE, "limit": 5})
    assert api.calls[-1][1]["limit"] == 5
    assert result.structured_content["stories"][0]["id"] == "abc"


async def test_get_story(api):
    api.responses["search/story"] = {"story": {"id": "abc", "title": "A story"}}
    result = await call("get_story", {"story_id": "abc"})
    assert api.calls[-1][1]["storyId"] == "abc"
    assert result.structured_content["title"] == "A story"


@pytest.mark.parametrize(
    ("tool", "endpoint", "response_key"),
    [
        ("top_words", "search/words", "words"),
        ("top_sources", "search/sources", "sources"),
        ("top_languages", "search/languages", "languages"),
    ],
)
async def test_top_tools_enforce_limit_client_side(api, tool, endpoint, response_key):
    api.responses[endpoint] = {response_key: [{"n": i} for i in range(5)]}
    result = await call(tool, {**SCOPE, "limit": 2})
    assert api.calls[-1][1]["limit"] == 2
    content = result.structured_content
    assert len(content[response_key]) == 2
    assert content["truncated"] is True


async def test_search_collections_gives_next_offset(api):
    api.responses["sources/collections/"] = {
        "count": 30,
        "next": "https://search.mediacloud.org/api/sources/collections/?offset=10",
        "previous": None,
        "results": [{"id": 1, "name": "Nigeria - National"}],
    }
    result = await call("search_collections", {"name": "nigeria", "limit": 10})
    assert api.calls[-1][1] == {"limit": 10, "offset": 0, "name": "nigeria"}
    assert result.structured_content == {
        "count": 30,
        "results": [{"id": 1, "name": "Nigeria - National"}],
        "next_offset": 10,
    }


async def test_search_sources_last_page_has_no_next_offset(api):
    api.responses["sources/sources/"] = {"count": 1, "next": None, "results": [{"id": 2}]}
    result = await call("search_sources", {"collection_id": 7})
    assert api.calls[-1][1]["collection_id"] == 7
    assert result.structured_content["next_offset"] is None


async def test_get_collection_and_source(api):
    api.responses["sources/collections/5/"] = {"id": 5, "name": "C"}
    api.responses["sources/sources/2/"] = {"id": 2, "name": "washingtonpost.com"}
    assert (await call("get_collection", {"collection_id": 5})).structured_content["name"] == "C"
    source = await call("get_source", {"source_id": 2})
    assert source.structured_content["name"] == "washingtonpost.com"


async def test_list_feeds_converts_times_to_epoch(api):
    api.responses["sources/feeds/"] = {"count": 1, "next": None, "results": [{"id": 9}]}
    result = await call(
        "list_feeds", {"source_id": 2, "modified_since": "2022-08-01T00:00:00+00:00"}
    )
    params = api.calls[-1][1]
    assert params["source_id"] == 2
    assert params["modified_since"] == dt.datetime(2022, 8, 1, tzinfo=dt.UTC).timestamp()
    assert result.structured_content["results"] == [{"id": 9}]


async def test_check_connection(api):
    api.responses["search/api-params"] = {"params": {"query-rate": "10/m"}}
    result = await call("check_connection")
    assert result.structured_content["connected"] is True
    assert result.structured_content["api_params"]["params"]["query-rate"] == "10/m"


async def test_missing_api_key_is_explained(monkeypatch):
    monkeypatch.delenv("MC_API_KEY", raising=False)
    assert "MC_API_KEY is not set" in error_text(await call("count_stories", SCOPE))


async def test_reversed_dates_are_rejected_without_calling_api(api):
    result = await call("count_stories", {**SCOPE, "start_date": "2024-01-01"})
    assert "before start_date" in error_text(result)
    assert api.calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        {**SCOPE, "query": ""},
        {**SCOPE, "start_date": "not-a-date"},
        {**SCOPE, "collection_ids": ["x"]},
    ],
)
async def test_invalid_arguments_are_rejected_without_calling_api(api, arguments):
    assert (await call("count_stories", arguments)).is_error
    assert api.calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, "Check the query syntax"),
        (401, "Check that MC_API_KEY"),
        (403, "Check that MC_API_KEY"),
        (404, "no such item"),
        (429, "quota"),
        (500, "Try again later"),
    ],
)
async def test_api_errors_are_explained(api, status, expected):
    api.responses["search/total-count"] = api_error(status)
    text = error_text(await call("count_stories", SCOPE))
    assert expected in text
    assert f"HTTP {status}" in text
    assert "details" in text


async def test_long_error_details_are_cut(api):
    api.responses["search/total-count"] = api_error(502, "x" * 10_000)
    assert len(error_text(await call("count_stories", SCOPE))) < 700


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (requests.Timeout(), "timed out"),
        (requests.ConnectionError(), "Could not reach Media Cloud"),
    ],
)
async def test_network_errors_are_explained(api, error, expected):
    api.responses["search/total-count"] = error
    assert expected in error_text(await call("count_stories", SCOPE))


async def test_stdio_server_starts_without_an_api_key():
    # A stray print to stdout would corrupt the protocol, so go through the real transport.
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "media_cloud_mcp"], env={"MC_API_KEY": ""}
    )
    async with Client(params) as client:
        assert len((await client.list_tools()).tools) == 15
        result = await client.call_tool("count_stories", SCOPE)
    assert "MC_API_KEY is not set" in error_text(result)
