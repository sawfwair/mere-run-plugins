import assert from "node:assert/strict";
import { test } from "node:test";
import { sanitize, boundedRequest } from "../src/mere_archive_tools/resources/pi/lib/archive-contract.ts";

test("archive adapter preserves returned relative paths and omits absolute paths", () => {
  const result = sanitize({
    contractVersion: "mere.run/archive-search.v1", query: "repair", piiReductionApplied: true,
    storageTier: "safe-content", database: "/private/archive.sqlite3",
    results: [{rank: 1, snippet: "A reduced snippet", paths: [
      {path: "/private/source/repair.pdf", relativePath: "Maintenance/repair.pdf", available: true},
      {path: "/private/source/copy.pdf", relativePath: "Backups/copy.pdf", available: false},
    ]}],
  });
  assert.deepEqual(result.results[0].paths, ["Maintenance/repair.pdf", "Backups/copy.pdf"]);
  assert.equal(result.results[0].snippet, "A reduced snippet");
  assert.ok(!JSON.stringify(result).includes("/private"));
});

test("malformed path records fail instead of silently losing citations", () => {
  for (const paths of [["file.pdf"], [{}], null]) {
    assert.throws(() => sanitize({results:[{paths}]}));
  }
});

test("exhausted search budget transitions to final JSON without more tools", () => {
  const payload = {messages: [{role: "user", content: "A question"}], tools: [{type:"function"}],
    tool_choice: "auto", max_completion_tokens: 4096};
  const searching = boundedRequest(payload, 3, 4, true);
  assert.deepEqual(searching.tools, payload.tools);
  const final = boundedRequest(payload, 4, 4, true);
  assert.equal(final.tools, undefined);
  assert.equal(final.tool_choice, undefined);
  assert.equal(final.max_tokens, undefined);
  assert.equal(final.max_completion_tokens, 4096);
  assert.deepEqual(final.response_format, {type:"json_object"});
  assert.equal(final.messages.length, 2);
  assert.equal(boundedRequest(payload, 4, 4, false).response_format, undefined);
  const repair = boundedRequest(payload, 1, 4, true, true);
  assert.equal(repair.tools, undefined);
  assert.deepEqual(repair.response_format, {type:"json_object"});
  assert.match(repair.messages[1].content, /Repair the rejected response/);
  assert.deepEqual(payload.tools, [{type:"function"}]);
});
