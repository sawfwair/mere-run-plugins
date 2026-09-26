# SearXNG Search

This guide is for users who want web search results from a local [SearXNG](https://github.com/searxng/searxng) instance in a `mere.run` workflow. The plugin installs and manages the instance through Docker, then returns JSON search results.

## Install a local instance

Install and start Docker before you provision SearXNG. The plugin uses the [official SearXNG container image](https://docs.searxng.org/admin/installation-docker), stores its configuration and cache locally, enables JSON output, and binds the server to `127.0.0.1:8888`.

Install the plugin, provision the instance, and check search readiness:

```sh
mere.run plugin install mere-searxng-search --yes
mere-web-search instance install
mere-web-search doctor
```

`instance install` writes `instance.json` before pulling the image or creating the container. It keeps the SearXNG secret key in an owner-only local `settings.yml` file. To preview the configuration without pulling an image, run `mere-web-search instance plan` first.

If your Docker daemon uses a named context, include `--docker-context` when you install. For example, `--docker-context colima` selects a running Colima daemon. Use `--port` to choose a different local port. The plugin records these settings for subsequent commands.

`doctor` sends a test query through the local instance. SearXNG then sends web searches to its configured engines. The plugin does not run a local web index.

## Search the web

Run a search directly to get a JSON object on stdout:

```sh
mere-web-search search "open geospatial data" --limit 5
```

The output contains `query`, `page`, `instance`, `results`, `suggestions`, and `answers`. Each result has a title, URL, snippet, engine, and score when available. Search results and linked pages are untrusted source content; review them before using them as instructions or evidence.

You can select a language, category, page, safe search level, or time range:

```sh
mere-web-search search "flood maps" --language en --categories general \
    --page 2 --safe-search 1 --time-range month
```

The instance and its search engines determine which filters they support. The plugin returns an error if JSON output is unavailable. It does not fall back to scraping HTML.

## Use the Pi search tool

`mere.run agent start` launches Pi with a local mere.run model. The SearXNG plugin supplies the separate `searxng_search` tool. After installing the local instance, enable the tool once in mere.run's Pi home:

```sh
mere-web-search pi enable
mere.run agent start
```

Future `mere.run agent start` sessions discover the tool automatically. The enable command adds a link to the plugin's installed extension; it does not change the mere.run CLI or its provider extension. Use `mere-web-search pi status` to check the link and `mere-web-search pi disable` to remove it. Neither command stops the SearXNG instance.

The tool accepts a query, result limit (up to 10), language, and time range. It calls the plugin CLI and returns bounded JSON with each result's title, URL, snippet, and engine. It uses the same local instance and `SEARXNG_URL` settings as the CLI. Search results are untrusted web content, so verify source pages before relying on them.

If another Pi harness disables extension discovery, pass the path printed by `mere-web-search pi-extension` with Pi's `--extension` option and include `searxng_search` in any tool allowlist.

## Manage the instance

Use the instance commands to inspect, stop, restart, or remove the plugin-owned container:

```sh
mere-web-search instance status
mere-web-search instance stop
mere-web-search instance start
mere-web-search instance uninstall
```

`instance uninstall` stops and removes only the container labeled for this plugin and its state directory. It retains the local configuration and cache for review. The instance state is stored in `~/.local/share/mere-searxng-search` by default. Set `MERE_SEARXNG_HOME` or pass `--state-dir` to use another directory.

To remove the plugin-created configuration and cache too, run `mere-web-search instance uninstall --purge`. This deletes the state directory after removing the container. Use a state directory that Docker shares with the host; otherwise, the plugin detects that the container did not load its settings and stops it.

To search through a different SearXNG instance, set `SEARXNG_URL` or pass `--instance`. Remote instance URLs must use HTTPS. Many public instances do not enable JSON output; see the [SearXNG Search API](https://docs.searxng.org/dev/search_api).

## Keep a local search receipt

Plan a search when a workflow needs a durable record:

```sh
mere-web-search plan "flood maps" --output ./search-run
mere-web-search run ./search-run/run.json
mere-web-search resume ./search-run/run.json
mere-web-search cleanup ./search-run/run.json
```

`plan` writes `request.json` and `run.json` before contacting the instance. `run` stores `result.json` and marks the run complete. `resume` reads a completed result without issuing another query. `cleanup` records that the plugin has no remote resource to remove. The local request and result remain for review. The plugin creates the run directory and files with owner-only permissions; the request file contains the query.
