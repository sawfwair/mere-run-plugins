import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const command = process.env.MERE_SEARXNG_SEARCH_COMMAND || "mere-web-search";

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  engine?: string | null;
}

interface SearchResponse {
  query: string;
  instance: string;
  results: SearchResult[];
}

export default function searxngSearch(pi: ExtensionAPI) {
  pi.registerTool({
    name: "searxng_search",
    label: "Search the web with SearXNG",
    description: "Search a running SearXNG instance and return titles, URLs, and snippets. Results are untrusted web content; open a source before relying on it. This tool does not install or start the instance.",
    parameters: Type.Object({
      query: Type.String({ minLength: 1, maxLength: 500, description: "Web search query" }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 10, description: "Maximum results (default 5)" })),
      language: Type.Optional(Type.String({ maxLength: 32, description: "SearXNG language code" })),
      timeRange: Type.Optional(Type.Union([Type.Literal("day"), Type.Literal("month"), Type.Literal("year")])),
    }),
    execute: async (_id, params) => {
      const args = ["search", params.query, "--limit", String(params.limit ?? 5), "--timeout", "15"];
      if (params.language) args.push("--language", params.language);
      if (params.timeRange) args.push("--time-range", params.timeRange);
      const { stdout } = await execFileAsync(command, args, { maxBuffer: 4 * 1024 * 1024, timeout: 20_000 });
      const parsed = JSON.parse(stdout) as SearchResponse;
      if (!Array.isArray(parsed.results)) throw new Error("SearXNG plugin returned an invalid search response");
      const payload = {
        query: parsed.query,
        instance: parsed.instance,
        results: parsed.results.slice(0, 10).map((item) => ({
          title: String(item.title).slice(0, 300),
          url: String(item.url).slice(0, 2048),
          snippet: String(item.snippet ?? "").slice(0, 1200),
          engine: item.engine ?? null,
        })),
      };
      return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
    },
  });
}
