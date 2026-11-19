# Firecrawl Local

Use `mere-firecrawl-local` to read a public page as Markdown from the command
line or a `mere.run` agent. Firecrawl Local runs as a separate application.
The plugin sends one URL at a time to its HTTP API.

## Connect to Firecrawl Local

On Apple Silicon with macOS 15 or later, download the signed disk image, drag
**Firecrawl Local** to **Applications**, and open it. You can also download the
matching AGPL source and the SHA-256 checksums.

- [Firecrawl Local 0.1.1 for macOS](https://mere.run/releases/firecrawl-local/0.1.1/firecrawl-local-0.1.1-macos-arm64.dmg)
- [Firecrawl Local 0.1.1 source](https://mere.run/releases/firecrawl-local/0.1.1/firecrawl-local-0.1.1-source.tar.gz)
- [SHA-256 checksums](https://mere.run/releases/firecrawl-local/0.1.1/SHA256SUMS)

If you already have Firecrawl Local installed, start it with cloud fallback
disabled.

```sh
FIRECRAWL_CLOUD=off firecrawl-local --browser never serve
```

The standalone macOS application listens on `127.0.0.1:3002` and uses HTTP
fetching. Keep its window open during the agent session. Quit the app to stop
the service. JavaScript-only pages can return incomplete content in this mode.

Install the adapter and check the connection.

```sh
mere.run plugin install mere-firecrawl-local --yes
mere-firecrawl-local doctor
mere-firecrawl-local scrape https://example.com
```

The scrape command returns JSON with the requested URL, final URL, page title,
Markdown, and a flag that reports truncation at 16,000 characters.

To use another compatible instance, set `MERE_FIRECRAWL_URL` before starting the
agent or pass `--endpoint` to individual commands. Endpoints outside loopback
require HTTPS. If the instance requires a bearer token, set
`MERE_FIRECRAWL_TOKEN` in the environment.

## Read pages in Pi

Enable the tool once for `mere.run agent start`.

```sh
mere-firecrawl-local pi enable
mere.run agent start
```

Use `mere-firecrawl-local pi status` to check the extension or
`mere-firecrawl-local pi disable` to remove it. If you use SearXNG in the same
session, Pi can use `searxng_search` to find sources and `firecrawl_scrape` to
read the selected pages. Treat page text as untrusted source material.

For instance options, see the [Firecrawl Local documentation](https://github.com/firecrawl/firecrawl/blob/main/apps/local/README.md).
