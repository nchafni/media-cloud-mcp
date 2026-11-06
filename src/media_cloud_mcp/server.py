"""MCP tools for the Media Cloud search and directory APIs."""

import argparse
import datetime as dt
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from media_cloud_mcp import __version__
from media_cloud_mcp.client import (
    get_directory_api,
    get_search_api,
    to_jsonable,
    translate_errors,
)
from media_cloud_mcp.guide import QUERY_GUIDE, SERVER_INSTRUCTIONS

mcp = MCPServer(
    name="media-cloud",
    title="Media Cloud",
    instructions=SERVER_INSTRUCTIONS,
    website_url="https://www.mediacloud.org",
    version=__version__,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

Query = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            'Boolean query, e.g. "climate change" AND policy. AND/OR/NOT must be capitalized and '
            "phrases need double quotes. Use * to match all stories. Full syntax is in the "
            "mediacloud://query-guide resource."
        ),
    ),
]
StartDate = Annotated[dt.date, Field(description="First publication date, YYYY-MM-DD.")]
EndDate = Annotated[dt.date, Field(description="Last publication date, YYYY-MM-DD.")]
CollectionIds = Annotated[
    list[int] | None,
    Field(description="Collections to search. Find IDs with search_collections."),
]
SourceIds = Annotated[
    list[int] | None,
    Field(description="Media sources to search. Find IDs with search_sources."),
]
Platform = Annotated[
    Literal["online_news", "youtube", "twitter", "reddit"] | None,
    Field(description="Only include this platform."),
]
Offset = Annotated[int, Field(ge=0, description="Results to skip. Use next_offset from a reply.")]


def _search_args(
    query: str,
    start_date: dt.date,
    end_date: dt.date,
    collection_ids: list[int] | None,
    source_ids: list[int] | None,
) -> dict[str, Any]:
    if end_date < start_date:
        raise ToolError(f"end_date ({end_date}) is before start_date ({start_date}).")
    # The client library calls len() on both ID lists, so None would crash it.
    return {
        "query": query,
        "start_date": start_date,
        "end_date": end_date,
        "collection_ids": collection_ids or [],
        "source_ids": source_ids or [],
    }


def _offset_page(page: dict[str, Any], limit: int, offset: int) -> dict[str, Any]:
    return {
        "count": page.get("count"),
        "results": to_jsonable(page.get("results", [])),
        "next_offset": offset + limit if page.get("next") else None,
    }


def _truncated(key: str, rows: list[Any], limit: int) -> dict[str, Any]:
    # Not every endpoint honors a limit, and some have none, so enforce it here.
    return {
        key: to_jsonable(rows[:limit]),
        "total_rows": len(rows),
        "truncated": len(rows) > limit,
    }


@mcp.tool(title="Check connection", annotations=READ_ONLY)
@translate_errors
def check_connection() -> dict[str, Any]:
    """Verify that the API key works and show the server's API parameters, such as rate limits."""
    return {"connected": True, "api_params": to_jsonable(get_search_api().api_params())}


@mcp.tool(title="Count stories", annotations=READ_ONLY)
@translate_errors
def count_stories(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
) -> dict[str, Any]:
    """Count stories matching a query.

    Returns `relevant` (stories matching), `total` (all stories in the same scope and dates) and
    `ratio` (relevant / total). Compare ratios, not raw counts, across sources or collections.
    """
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    counts = get_search_api().story_count(**args)
    relevant, total = counts.get("relevant", 0), counts.get("total", 0)
    return {"relevant": relevant, "total": total, "ratio": relevant / total if total else None}


@mcp.tool(title="Count stories over time", annotations=READ_ONLY)
@translate_errors
def count_stories_over_time(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
) -> dict[str, Any]:
    """Get daily counts for a query: date, count, total_count and ratio for each day."""
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    return {"counts": to_jsonable(get_search_api().story_count_over_time(**args))}


@mcp.tool(title="Count stories by source over time", annotations=READ_ONLY)
@translate_errors
def count_stories_by_source_over_time(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    interval: Annotated[Literal["day", "week"], Field(description="Time bucket size.")] = "week",
    max_rows: Annotated[int, Field(ge=1, le=5000, description="Most rows to return.")] = 500,
) -> dict[str, Any]:
    """Compare attention across sources: matching stories, total stories and ratio per bucket.

    Returns one row per source per time bucket, so a large collection can produce many rows.
    `truncated` says whether rows were dropped to fit `max_rows`.
    """
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    rows = get_search_api().stories_by_source_over_interval(**args, interval=interval)
    return _truncated("rows", rows, max_rows)


@mcp.tool(title="List stories", annotations=READ_ONLY)
@translate_errors
def list_stories(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    page_size: Annotated[int, Field(ge=1, le=1000, description="Stories per page.")] = 100,
    sort_order: Annotated[
        Literal["asc", "desc"] | None, Field(description="Order by publication date.")
    ] = None,
    randomized: Annotated[bool, Field(description="Return stories in random order.")] = False,
    include_text: Annotated[
        bool,
        Field(description="Include full text. Only works for accounts with elevated access."),
    ] = False,
    pagination_token: Annotated[
        str | None, Field(description="next_page_token from the previous page.")
    ] = None,
) -> dict[str, Any]:
    """List stories matching a query: ID, title, URL, publication date, language and source.

    Repeat with `pagination_token` to get more. `next_page_token` is null on the last page.
    """
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    stories, next_page_token = get_search_api().story_list(
        **args,
        page_size=page_size,
        sort_order=sort_order,
        randomized=randomized,
        expanded=include_text,
        pagination_token=pagination_token,
    )
    return {"stories": to_jsonable(stories), "next_page_token": next_page_token}


@mcp.tool(title="Sample stories", annotations=READ_ONLY)
@translate_errors
def sample_stories(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Stories to return.")] = 50,
) -> dict[str, Any]:
    """Get a random sample of stories matching a query, for a quick read of the coverage."""
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    return {"stories": to_jsonable(get_search_api().story_sample(**args, limit=limit))}


@mcp.tool(title="Get story", annotations=READ_ONLY)
@translate_errors
def get_story(
    story_id: Annotated[str, Field(min_length=1, description="Story ID from list_stories.")],
) -> dict[str, Any]:
    """Get one story's metadata. Full text is only included for accounts with elevated access."""
    return to_jsonable(get_search_api().story(story_id))


@mcp.tool(title="Top words", annotations=READ_ONLY)
@translate_errors
def top_words(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Terms to return.")] = 100,
) -> dict[str, Any]:
    """Get the most used terms in a sample of matching stories, to study framing.

    Terms are stemmed; each is shown in its most common form.
    """
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    return _truncated("words", get_search_api().words(**args, limit=limit), limit)


@mcp.tool(title="Top sources", annotations=READ_ONLY)
@translate_errors
def top_sources(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Sources to return.")] = 50,
) -> dict[str, Any]:
    """Get the media sources publishing the most stories that match a query."""
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    return _truncated("sources", get_search_api().sources(**args, limit=limit), limit)


@mcp.tool(title="Top languages", annotations=READ_ONLY)
@translate_errors
def top_languages(
    query: Query,
    start_date: StartDate,
    end_date: EndDate,
    collection_ids: CollectionIds = None,
    source_ids: SourceIds = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Languages to return.")] = 25,
) -> dict[str, Any]:
    """Get the most common languages among stories matching a query."""
    args = _search_args(query, start_date, end_date, collection_ids, source_ids)
    return _truncated("languages", get_search_api().languages(**args, limit=limit), limit)


@mcp.tool(title="Search collections", annotations=READ_ONLY)
@translate_errors
def search_collections(
    name: Annotated[
        str | None, Field(description="Text to find in the name, e.g. nigeria.")
    ] = None,
    platform: Platform = None,
    source_id: Annotated[
        int | None, Field(description="Only collections with this source.")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Results per page.")] = 25,
    offset: Offset = 0,
) -> dict[str, Any]:
    """Find collections, which are groups of sources, often by country or state."""
    page = get_directory_api().collection_list(
        name=name, platform=platform, source_id=source_id, limit=limit, offset=offset
    )
    return _offset_page(page, limit, offset)


@mcp.tool(title="Get collection", annotations=READ_ONLY)
@translate_errors
def get_collection(
    collection_id: Annotated[int, Field(description="Collection ID.")],
) -> dict[str, Any]:
    """Get details of one collection."""
    return to_jsonable(get_directory_api().collection(collection_id))


@mcp.tool(title="Search sources", annotations=READ_ONLY)
@translate_errors
def search_sources(
    name: Annotated[
        str | None, Field(description="Name or domain to find, e.g. hindustantimes.com.")
    ] = None,
    platform: Platform = None,
    collection_id: Annotated[
        int | None, Field(description="Only sources in this collection.")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Results per page.")] = 25,
    offset: Offset = 0,
) -> dict[str, Any]:
    """Find media sources by name or domain, or list the sources in a collection."""
    page = get_directory_api().source_list(
        name=name, platform=platform, collection_id=collection_id, limit=limit, offset=offset
    )
    return _offset_page(page, limit, offset)


@mcp.tool(title="Get source", annotations=READ_ONLY)
@translate_errors
def get_source(source_id: Annotated[int, Field(description="Source ID.")]) -> dict[str, Any]:
    """Get details of one media source."""
    return to_jsonable(get_directory_api().source(source_id))


@mcp.tool(title="List feeds", annotations=READ_ONLY)
@translate_errors
def list_feeds(
    source_id: Annotated[int | None, Field(description="Only feeds of this source.")] = None,
    modified_since: Annotated[
        dt.datetime | None, Field(description="Only feeds modified after this ISO 8601 time.")
    ] = None,
    modified_before: Annotated[
        dt.datetime | None, Field(description="Only feeds modified before this ISO 8601 time.")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Results per page.")] = 25,
    offset: Offset = 0,
) -> dict[str, Any]:
    """List the RSS feeds Media Cloud collects from."""
    page = get_directory_api().feed_list(
        source_id=source_id,
        modified_since=modified_since,
        modified_before=modified_before,
        limit=limit,
        offset=offset,
    )
    return _offset_page(page, limit, offset)


@mcp.resource(
    "mediacloud://query-guide",
    name="query-guide",
    title="Media Cloud query guide",
    description="Query syntax, known collection and source IDs, and how to read results.",
    mime_type="text/markdown",
)
def query_guide() -> str:
    return QUERY_GUIDE


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="media-cloud-mcp",
        description=(
            "Run the Media Cloud MCP server over stdio. Reads the API key from MC_API_KEY."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
