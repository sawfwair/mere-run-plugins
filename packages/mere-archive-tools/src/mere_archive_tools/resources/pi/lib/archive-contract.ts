function relativePaths(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error("Archive result paths must be an array");
  return value.map((item) => {
    if (!item || typeof item !== "object" || !("relativePath" in item) || typeof item.relativePath !== "string") {
      throw new Error("Archive result is missing relativePath");
    }
    return item.relativePath as string;
  });
}


export function sanitize(raw: Record<string, unknown>) {
  const results = Array.isArray(raw.results) ? raw.results : [];
  return {
    query: raw.query,
    results: results.map((item) => {
      const result = item as Record<string, unknown>;
      return {
        snippet: result.snippet,
        paths: relativePaths(result.paths),
      };
    }),
  };
}


export function boundedRequest(
  payload: Record<string, unknown>, searchCount: number, maxSearches: number, supportsJSON: boolean, repair = false,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...payload, temperature: 0 };
  if (!repair && searchCount < maxSearches) return next;
  delete next.tools;
  delete next.tool_choice;
  if (supportsJSON) next.response_format = { type: "json_object" };
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  next.messages = [...messages, {
    role: "user",
    content: (repair ? "Repair the rejected response using the supplied archive evidence. " : "The archive search budget is exhausted. ") +
      "Return the final mere.run/archive-investigation.v1 JSON object now, with answer and claims. Cite only returned paths. Mark unsupported facts unresolved: silence about coverage is not evidence of exclusion, and an invoice line is not evidence of reimbursement. Do not request another tool.",
  }];
  return next;
}
