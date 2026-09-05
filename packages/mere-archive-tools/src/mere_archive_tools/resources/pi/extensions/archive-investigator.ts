import { readFile, writeFile, rename } from "node:fs/promises";
import { appendFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { sanitize, boundedRequest } from "../lib/archive-contract.ts";

const requestDirectory = process.env.MERE_ARCHIVE_REQUEST_DIRECTORY;
const tracePath = process.env.MERE_ARCHIVE_SEARCH_TRACE;
const maxSearches = Number.parseInt(process.env.MERE_ARCHIVE_MAX_SEARCHES ?? "4", 10);
const eventsPath = process.env.MERE_ARCHIVE_EVENTS;
let searchCount = 0;

function required(value: string | undefined, name: string): string {
  if (!value) throw new Error(`${name} isn't set; launch through mere-archive-tools investigate`);
  return value;
}

function event(name: string, fields: Record<string, string | number> = {}): void {
  if (eventsPath) appendFileSync(eventsPath, `${JSON.stringify({ event: name, ...fields })}\n`, "utf8");
}


function response(payload: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

export default async function archiveInvestigator(pi: ExtensionAPI) {
  const prior = await readFile(required(tracePath, "MERE_ARCHIVE_SEARCH_TRACE"), "utf8")
    .catch((error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return ""; throw error; });
  searchCount = prior.split("\n").filter(Boolean).length;
  pi.on("session_start", () => { event("session_start"); });
  pi.on("before_provider_request", (request) => {
    const payload = request.payload as Record<string, unknown>;
    event("provider_request", {
      requestedOutputTokens: Number(payload.max_completion_tokens ?? payload.max_tokens ?? 0),
      messageCount: Array.isArray(payload.messages) ? payload.messages.length : 0,
    });
    // Bound generation without overriding the runtime capability contract.
    return boundedRequest(payload, searchCount, maxSearches, process.env.MERE_ARCHIVE_FINAL_JSON === "1",
      process.env.MERE_ARCHIVE_REPAIR === "1");
  });
  pi.on("after_provider_response", (response) => { event("provider_response", { status: response.status }); });
  pi.on("message_end", (message) => {
    if (message.message.role === "assistant") {
      event("assistant_complete", {
        outputTokens: message.message.usage.output,
        inputTokens: message.message.usage.input,
        cacheReadTokens: message.message.usage.cacheRead,
        stopReason: message.message.stopReason,
      });
    }
  });
  let firstToken = true;
  pi.on("message_update", () => {
    if (firstToken) { event("first_token"); firstToken = false; }
  });
  pi.registerTool({
    name: "archive_search",
    label: "Search the archive",
    description:
      "Search the bound PII-reduced archive. Refine terms, document types, vendors, dates, or synonyms when one search doesn't cover the question.",
    parameters: Type.Object({
      query: Type.String({ minLength: 2, maxLength: 500 }),
      purpose: Type.String({ minLength: 2, maxLength: 240 }),
    }),
    execute: async (_id, params) => {
      if (searchCount >= maxSearches) {
        throw new Error(`archive_search reached its ${maxSearches}-search limit`);
      }
      searchCount += 1;
      event("search_start");
      const directory = required(requestDirectory, "MERE_ARCHIVE_REQUEST_DIRECTORY");
      const sequence = searchCount;
      const request = join(directory, `request-${sequence}.json`);
      await writeFile(`${request}.tmp`, JSON.stringify({ query: params.query }), "utf8");
      await rename(`${request}.tmp`, request);
      const responsePath = join(directory, `response-${sequence}.json`);
      // The launcher owns deadlines, search budgets, tracing, and process cleanup.
      let encoded: string | undefined;
      while (encoded === undefined) {
        encoded = await readFile(responsePath, "utf8")
          .catch((error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return undefined; throw error; });
        if (encoded === undefined) await setTimeout(50);
      }
      const sanitized = sanitize(JSON.parse(encoded) as Record<string, unknown>);
      return response({ ...sanitized, remainingSearches: maxSearches - searchCount });
    },
  });
}
