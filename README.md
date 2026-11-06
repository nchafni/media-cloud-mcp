# media-cloud-mcp

An [MCP](https://modelcontextprotocol.io) server for [Media Cloud](https://www.mediacloud.org), the open archive of online news used for media research. It lets an AI assistant measure how much attention news media pay to a topic, compare sources and countries, examine the language of coverage, and find story URLs.

This is an independent project, not an official Media Cloud product. It is built on the official [`mediacloud`](https://pypi.org/project/mediacloud/) Python client.

## Setup

You need [uv](https://docs.astral.sh/uv/) and a Media Cloud API key. You don't need to install Python or this package yourself: `uvx` downloads whatever is missing the first time the server starts.

### 1. Install uv

On macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then open a new terminal, so that it can find the `uvx` command.

### 2. Get a Media Cloud API key

[Sign in to Media Cloud](https://search.mediacloud.org/sign-in), click the person icon at the top right, choose **Profile**, and copy your API key.

### 3. Add the server to your MCP client

For Claude Code, run:

```bash
claude mcp add media-cloud --env MC_API_KEY=your-api-key -- uvx media-cloud-mcp
```

For Claude Desktop and other clients that use a JSON configuration, add this to the configuration file. In Claude Desktop, that's `claude_desktop_config.json`, which you can open from **Settings > Developer > Edit Config**.

```json
{
  "mcpServers": {
    "media-cloud": {
      "command": "uvx",
      "args": ["media-cloud-mcp"],
      "env": { "MC_API_KEY": "your-api-key" }
    }
  }
}
```

Restart the client after changing its configuration. You don't need to start the server yourself, because the client does that. If you run `uvx media-cloud-mcp` in a terminal, it waits silently for a client to connect, so it can look frozen. Press Ctrl+C to stop it.

### 4. Check that it works

Ask your assistant to run the `check_connection` tool.

### Troubleshooting

- **The client can't find `uvx`:** desktop apps may not use the same `PATH` as your terminal. Run `which uvx` (on Windows, `where uvx`) and use the full path it prints as the `command`.
- **The server times out the first time it starts:** the first start downloads Python and the dependencies, which can take a while on a slow connection. Restart the client to retry. Downloads are cached, so later starts are faster.
- **`MC_API_KEY is not set` or HTTP 401:** check that the key is in your client's configuration and was copied correctly, then restart the client.

### Using pip instead

With Python 3.11 or newer, you can run `pip install media-cloud-mcp` and use `media-cloud-mcp` as the command, with no arguments.

## Tools

All tools are read-only.

| Tool | What it does |
| --- | --- |
| `check_connection` | Verifies the API key and shows API parameters such as rate limits |
| `count_stories` | Matching stories, total stories in scope, and their ratio |
| `count_stories_over_time` | Daily counts and ratios |
| `count_stories_by_source_over_time` | Counts and ratios per source, per day or week |
| `list_stories` | Story metadata and URLs, with pagination |
| `sample_stories` | A random sample of matching stories |
| `get_story` | Metadata for one story |
| `top_words` | Most used terms in a sample of matching stories |
| `top_sources` | Sources publishing the most matching stories |
| `top_languages` | Most common languages among matching stories |
| `search_collections` | Find collections, often by country or state |
| `get_collection` | Details of one collection |
| `search_sources` | Find sources by name or domain, or list a collection's sources |
| `get_source` | Details of one source |
| `list_feeds` | RSS feeds Media Cloud collects from |

The `mediacloud://query-guide` resource documents the query syntax. The server also sends it to the assistant as part of its instructions.

## Example prompts

- "How much did US national media cover climate change in November 2023 compared with Indian national media?"
- "Which Nigerian news sources wrote the most about fuel subsidies last year?"
- "Chart the weekly share of stories about 'artificial intelligence' in the Washington Post in 2024."
- "What words most often appear in coverage of the housing crisis in Boston Globe stories?"

## Limits

- **Story text:** Media Cloud returns metadata and URLs. Copyright restrictions keep full text limited to accounts with elevated access.
- **Rate limit and quota:** requests are rate limited per account, and the client library waits when it reaches the limit, so a burst of calls can be slow. Your account also has a weekly quota. Contact Media Cloud if you need more.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

Tests replace only the HTTP layer and don't need an API key. To try the server interactively:

```bash
MC_API_KEY=your-api-key uv run media-cloud-mcp
```

## License

MIT
