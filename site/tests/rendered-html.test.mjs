import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("https://plugins.mere.run/", {
      headers: { accept: "text/html", host: "plugins.mere.run" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the plugins product page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>mere\.run plugins — Local AI, extended<\/title>/i);
  assert.match(html, /Local AI,/);
  assert.match(html, /extended\./);
  assert.match(html, /Twelve companion plugins/);
  assert.match(html, /VFX Tools/);
  assert.match(html, /Perform/);
  assert.match(html, /RunPod Runner/);
  assert.match(html, /Document Tools/);
  assert.match(html, /Power you can inspect/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("publishes complete social metadata", async () => {
  const response = await render();
  const html = await response.text();

  assert.match(html, /property="og:image" content="https:\/\/plugins\.mere\.run\/og\.png"/i);
  assert.match(html, /name="twitter:card" content="summary_large_image"/i);
  assert.match(html, /name="description" content="Official companion plugins for mere\.run/i);
});
