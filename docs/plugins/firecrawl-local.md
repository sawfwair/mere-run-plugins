# Firecrawl Local

Use `mere-firecrawl-local` to read a public page as Markdown from the command
line or a `mere.run` agent. Firecrawl Local runs as a separate application.
The plugin sends one URL at a time to its HTTP API.

## Install the adapter and start Firecrawl

On Apple Silicon with macOS 15 or later, run these commands to install the
signed adapter, start Firecrawl Local, and read a page.

```sh
mere.run plugin install mere-firecrawl-local --yes
mere.run plugin doctor mere-firecrawl-local
mere.run plugin run mere-firecrawl-local -- scrape https://example.com
```

Setup reuses a healthy Firecrawl Local instance. Otherwise, it opens an
existing Mere-signed Firecrawl Local app or downloads and verifies the
separate app before installing it in `~/Applications`. Open Firecrawl Local
again from Finder whenever you need to restart the service. Quit the app to
stop it. It listens on `127.0.0.1:3002` with Firecrawl Cloud fallback and
browser rendering disabled. JavaScript-only pages can return incomplete content.

To rerun setup, use `mere.run plugin run mere-firecrawl-local -- setup --yes`.
To install or start Firecrawl yourself, use the standalone application or
configure a compatible endpoint before installing the adapter.

- [Firecrawl Local 0.1.1 for macOS](https://mere.run/releases/firecrawl-local/0.1.1/firecrawl-local-0.1.1-macos-arm64.dmg)
- [Firecrawl Local 0.1.1 source](https://mere.run/releases/firecrawl-local/0.1.1/firecrawl-local-0.1.1-source.tar.gz)
- [SHA-256 checksums](https://mere.run/releases/firecrawl-local/0.1.1/SHA256SUMS)

The scrape command returns JSON with the requested URL, final URL, page title,
Markdown, and a truncation flag. By default it returns up to 16,000 characters
of Markdown. To retrieve the complete Markdown from Firecrawl, pass `--full`.

```sh
mere.run plugin run mere-firecrawl-local -- scrape --full https://example.com
```

To use another compatible instance, set `MERE_FIRECRAWL_URL` before installing
the adapter or starting the agent. You can also pass `--endpoint` to individual adapter commands. Endpoints outside loopback
require HTTPS. If the instance requires a bearer token, set
`MERE_FIRECRAWL_TOKEN` in the environment.

## Read pages in Pi

Enable the tool once for `mere.run agent start`.

```sh
mere.run plugin run mere-firecrawl-local -- pi enable
mere.run agent start
```

If you enabled the Pi tool from a source install, enable it again after you
install the signed bundle.

Run `mere.run plugin run mere-firecrawl-local -- pi status` to check the
extension or replace `status` with `disable` to remove it. If you use SearXNG in the same
session, Pi can use `searxng_search` to find sources and `firecrawl_scrape` to
read the selected pages. Each successful read returns a `sourceId` for citing
that page. Long pages return a preview and headings. Use `firecrawl_find` with
the source ID and a phrase to read matching passages with line numbers from
the complete page. You can also look up a page with its requested URL or
verified redirect URL. For Gmail help articles, the shorter article URL
can identify a page read with desktop and English locale parameters.

Pi keeps up to eight recently read pages available for lookup. To search
within an older page, read it again. Treat page text as untrusted source material.

For instance options, see the [Firecrawl Local documentation](https://github.com/firecrawl/firecrawl/blob/main/apps/local/README.md).
