import assert from "node:assert/strict";
import test from "node:test";
import { PageEvidence, findPassages } from "../src/mere_firecrawl_local/resources/pi/lib/page-evidence.ts";

function page(url, markdown, requestedUrl = url) {
  return { requestedUrl, url, title: "Vendor help", markdown, truncated: false };
}

test("short pages expose all Markdown including product import limits", () => {
  const evidence = new PageEvidence();
  const body = "# Import products\nYour product CSV can't exceed 15 MB.\n";
  const receipt = evidence.add(page("https://help.shopify.com/en/manual/products/import-export/import-products", body));

  assert.equal(receipt.markdown, body);
  assert.equal(receipt.truncated, false);
  assert.equal(evidence.find(receipt.sourceId, "15 MB").matches[0].startLine, 1);
});

test("long pages are searchable past the inline limit with their original line numbers", () => {
  const evidence = new PageEvidence();
  const raw = "# Earlier sections\n" + "Unrelated information.\n".repeat(1400)
    + "## Retention limits\nFor public repositories, the maximum is 90 days.\nPrivate repositories allow 400 days.\n";
  const receipt = evidence.add(page("https://docs.github.com/actions", raw));
  const reply = evidence.find(receipt.sourceId, "for public repositories");

  assert.equal(receipt.truncated, true);
  assert.equal(receipt.markdown.includes("90 days"), false);
  assert.ok(receipt.headings.includes("## Retention limits"));
  assert.ok(reply.matches[0].startLine > 1400);
  assert.match(reply.matches[0].text, /90 days.*\nPrivate repositories allow 400 days/);
});

test("a late match in a long line is still included", () => {
  const text = "Introduction. ".repeat(200) + "Administrator sets the attachment limit.";
  assert.match(findPassages(text, "administrator sets")[0].text, /Administrator sets the attachment limit/);
});

test("Gmail desktop citation accepts the equivalent article URL and preserves distinct variants", () => {
  const evidence = new PageEvidence();
  const canonical = "https://support.google.com/mail/answer/6584";
  const desktop = canonical + "?hl=en&co=GENIE.Platform%3DDesktop";
  const initial = evidence.add(page(desktop, "Workspace administrators set the attachment limit."));
  assert.equal(evidence.find(canonical, "administrators").sourceId, initial.sourceId);

  for (const url of [canonical + "?co=GENIE.Platform%3DAndroid", canonical + "?version=2",
      "https://another.example/mail/answer/6584"]) {
    assert.throws(() => evidence.find(url, "attachment limit"), /Use the source ID/);
  }
});

test("a captured redirect resolves to the same source and unverifiable URLs are rejected", () => {
  const evidence = new PageEvidence();
  const requested = "https://example.com/article";
  const final = "https://example.org/final";
  const body = "Only returned evidence can be cited.";
  const initial = evidence.add(page(final, body, requested));
  const duplicate = evidence.add(page(final, body, final + "?utm_source=search"));

  assert.equal(duplicate.sourceId, initial.sourceId);
  assert.equal(evidence.find(requested, "evidence").url, final);
  assert.throws(() => evidence.find("https://example.org/unread", "evidence"), /Use the source ID/);
});
