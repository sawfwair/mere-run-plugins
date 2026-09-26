# SearXNG Search

This guide is for users who want web search results from a [SearXNG](https://github.com/searxng/searxng) instance in a `mere.run` workflow. The plugin sends queries to the instance you select and returns JSON. It does not host or configure SearXNG.

## Prepare an instance

Use an instance that you control or trust. Its administrator must enable JSON output under `search.formats` in `settings.yml`. Many public instances turn off JSON output. See the [SearXNG Search API](https://docs.searxng.org/dev/search_api) for supported parameters.

Install the plugin and set your instance URL:

```sh
mere.run plugin install mere-searxng-search --yes
export SEARXNG_URL=https://search.example.org
mere-searxng-search doctor
```

`doctor` sends a test query. The instance receives every query that you send through this plugin. Remote instance URLs must use HTTPS; HTTP is accepted for local instances.

## Search the web

Run a search directly to get a JSON object on stdout:

```sh
mere-searxng-search search "open geospatial data" --limit 5
```

The output contains `query`, `page`, `instance`, `results`, `suggestions`, and `answers`. Each result has a title, URL, snippet, engine, and score when available. Search results and linked pages are untrusted source content; review them before using them as instructions or evidence.

You can select a language, category, page, safe search level, or time range:

```sh
mere-searxng-search search "flood maps" --language en --categories general \
    --page 2 --safe-search 1 --time-range month
```

The instance and its search engines determine which filters they support. The plugin returns an error if JSON output is unavailable. It does not fall back to scraping HTML.

## Keep a local search receipt

Plan a search when a workflow needs a durable record:

```sh
mere-searxng-search plan "flood maps" --output ./search-run
mere-searxng-search run ./search-run/run.json
mere-searxng-search resume ./search-run/run.json
mere-searxng-search cleanup ./search-run/run.json
```

`plan` writes `request.json` and `run.json` before contacting the instance. `run` stores `result.json` and marks the run complete. `resume` reads a completed result without issuing another query. `cleanup` records that the plugin has no remote resource to remove. The local request and result remain for review. The plugin creates the run directory and files with owner-only permissions; the request file contains the query.
