"""Usage guidance sent to the model, as server instructions and as a resource."""

QUERY_GUIDE = """\
# Media Cloud query syntax

Queries use Elasticsearch query-string syntax.

| Feature | Example | Notes |
| --- | --- | --- |
| Exact phrase | `"climate change"` | Double quotes |
| Hyphenated term | `"two-spirit"` | Must be in double quotes |
| Boolean | `gaza AND aid`, `gaza OR aid` | AND/OR must be capitalized |
| Implicit AND | `monkey banana` | Same as `monkey AND banana` |
| Negation | `gaza NOT hamas`, `gaza -hamas` | `NOT` or a `-` prefix |
| One-character wildcard | `wom?n` | Matches women, woman |
| Multi-character wildcard | `wom*` | Matches women, woman, womb |
| Fuzzy match | `Biden~` | Matches slight misspellings |
| Proximity | `"woman killed"~10` | Words within 10 words of each other |
| Title only | `article_title:biden` | Searches the headline field |
| Language | `* AND language:hi` | ISO 639-1 two-letter code |
| Everything | `*` | All stories in the scope and date range |

Regular expressions are not supported.

# Scoping a search

Pass `collection_ids` and/or `source_ids`. A source is usually one domain; a collection is a
group of sources. Find IDs with `search_collections` and `search_sources`. Unscoped queries are
allowed but slow and rarely meaningful, so prefer a collection.

Examples of known IDs:
- Collections: US National 34412234, India National 34412118, Nigeria National 38376341
- Sources: Washington Post 2, Boston Globe 21511

# Interpreting results

- Compare `ratio` (matching stories / all stories in the same scope and dates) rather than raw
  counts. Sources and collections differ greatly in volume.
- Media Cloud returns story metadata and URLs. Full text is restricted by copyright, so fetch the
  URL to read a story.
- `top_words` terms are stemmed and come from a sample of matching stories.
"""

SERVER_INSTRUCTIONS = f"""\
Media Cloud is an open archive of online news used for media research. Use these tools to measure
how much attention news media pay to a topic, see how it changes over time, compare sources or
countries, examine the language of coverage, and find story URLs.

Typical workflow: find a collection or source ID, run count_stories, then break it down with
count_stories_over_time, top_sources, top_words or list_stories. Calls are rate limited per
account and count against a weekly quota, so prefer counts before listing stories.

{QUERY_GUIDE}"""
