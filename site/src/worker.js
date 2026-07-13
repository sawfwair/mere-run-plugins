const CONTENT_SIGNAL = "ai-train=no, search=yes, ai-input=yes";

const HOME_MARKDOWN = `---
title: mere.run plugins — Production workflows for local AI
description: Official companion plugins for mere.run. VFX, realtime performance, production tracking, private document workflows, automation, and user-owned GPU training.
image: https://plugins.mere.run/og.png
---

# mere.run plugins

Production workflows for local AI.

Official companion executables extend the work around the local \`mere.run\`
runtime without moving canonical model behavior into a hosted service.

## Install

- \`mere.run plugin list\`
- \`mere.run plugin install mere-vfx-tools\`
- \`mere.run plugin install mere-perform\`
- \`mere.run plugin install mere-runpod\`

## Official plugins

- VFX Tools
- Perform
- Image Tools
- Animatic Tools
- ShotGrid Tools
- RunPod Runner
- Document Tools
- Media Scrub
- Dataset Tools
- Transcript Tools
- Image Compose
- Batch Runner

## Contract

Every provider plugin exposes \`manifest --json\`, \`doctor\`, \`plan\`, \`run\`,
\`resume\`, and \`cleanup\`. Remote resources stay user-controlled and terminate
by default unless an explicit keep/debug flag is passed.

## Links

- [Live catalog](https://plugins.mere.run/catalog/plugins.v1.json)
- [Plugin contract](https://github.com/sawfwair/mere-run-plugins/blob/main/docs/plugins/contract.md)
- [Source](https://github.com/sawfwair/mere-run-plugins)
- [mere.run](https://mere.run)
`;

const wantsMarkdown = (request) =>
  (request.headers.get("Accept") || "")
    .split(",")
    .some((part) => part.trim().toLowerCase().startsWith("text/markdown"));

const withHeaders = (response) => {
  const headers = new Headers(response.headers);
  headers.set("Content-Signal", CONTENT_SIGNAL);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if ((url.pathname === "/" || url.pathname === "/index.html") && wantsMarkdown(request)) {
      return new Response(HOME_MARKDOWN, {
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Content-Signal": CONTENT_SIGNAL,
          "x-markdown-tokens": String(Math.ceil(HOME_MARKDOWN.length / 4)),
          Vary: "Accept",
        },
      });
    }

    return withHeaders(await env.ASSETS.fetch(request));
  },
};
