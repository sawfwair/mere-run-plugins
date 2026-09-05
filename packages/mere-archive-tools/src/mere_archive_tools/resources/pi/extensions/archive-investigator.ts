import { execFile } from "node:child_process";
import { appendFile } from "node:fs/promises";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const database = process.env.MERE_ARCHIVE_DATABASE;
const tracePath = process.env.MERE_ARCHIVE_SEARCH_TRACE;
const maxSearches = Number.parseInt(process.env.MERE_ARCHIVE_MAX_SEARCHES ?? "4", 10);
const top = Number.parseInt(process.env.MERE_ARCHIVE_SEARCH_TOP ?? "5", 10);
const replacement = process.env.MERE_ARCHIVE_REPLACEMENT ?? "[{label}]";
let searchCount = 0;

function required(value: string | undefined, name: string): string {
  if (!value) throw new Error(`${name} isn't set; launch through mere-archive-tools investigate`);
  return value;
}

function pluginCommand(): string[] {
  const encoded = process.env.MERE_ARCHIVE_TOOLS_COMMAND_JSON;
  if (!encoded) return ["mere-archive-tools"];
  const value = JSON.parse(encoded) as unknown;
  if (!Array.isArray(value) || !value.length || !value.every((item) => typeof item === "string")) {
    throw new Error("MERE_ARCHIVE_TOOLS_COMMAND_JSON must contain a nonempty string array");
  }
  return value;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function sanitize(raw: Record<string, unknown>) {
  const results = Array.isArray(raw.results) ? raw.results : [];
  return {
    contractVersion: raw.contractVersion,
    query: raw.query,
    piiReductionApplied: raw.piiReductionApplied,
    storageTier: raw.storageTier,
    results: results.map((item) => {
      const result = item as Record<string, unknown>;
      return {
        rank: result.rank,
        score: result.score,
        modality: result.modality,
        kind: result.kind,
        snippet: result.snippet,
        keywords: result.keywords,
        paths: stringArray(result.paths),
      };
    }),
  };
}

function response(payload: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

export default function archiveInvestigator(pi: ExtensionAPI) {
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
      const command = pluginCommand();
      const args = [
        ...command.slice(1),
        "search",
        "--database",
        required(database, "MERE_ARCHIVE_DATABASE"),
        "--query",
        params.query,
        "--top",
        String(top),
        "--replacement",
        replacement,
      ];
      const { stdout, stderr } = await execFileAsync(command[0], args, {
        cwd: process.cwd(),
        timeout: 60_000,
        maxBuffer: 4 * 1024 * 1024,
        env: process.env,
      });
      if (stderr.trim()) process.stderr.write(stderr);
      const sanitized = sanitize(JSON.parse(stdout) as Record<string, unknown>);
      const resultPaths = sanitized.results.flatMap((item) => item.paths);
      const trace = {
        sequence: searchCount,
        query: sanitized.query,
        purpose: params.purpose,
        resultPaths: [...new Set(resultPaths)],
      };
      await appendFile(required(tracePath, "MERE_ARCHIVE_SEARCH_TRACE"), `${JSON.stringify(trace)}\n`, "utf8");
      return response(sanitized);
    },
  });
}
