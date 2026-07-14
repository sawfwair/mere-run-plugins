import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

// Every plugin in the public catalog must be documented somewhere under
// docs/plugins/. "Documented" means at least one page mentions the plugin id.
const repoRoot = new URL("../", import.meta.url);
const catalog = JSON.parse(
  await readFile(new URL("catalog/plugins.v1.json", repoRoot), "utf8"),
);

const docsDir = new URL("docs/plugins/", repoRoot);
const pages = (await readdir(docsDir)).filter((name) => name.endsWith(".md"));
const corpus = new Map();
for (const page of pages) {
  corpus.set(page, await readFile(new URL(page, docsDir), "utf8"));
}

const uncovered = [];
for (const plugin of catalog.plugins) {
  const covered = [...corpus.values()].some((text) => text.includes(plugin.id));
  if (!covered) uncovered.push(plugin.id);
}

if (uncovered.length > 0) {
  console.error(
    `Docs coverage failed: no page under docs/plugins/ mentions: ${uncovered.join(", ")}`,
  );
  process.exit(1);
}

console.log(
  `Docs coverage OK: ${catalog.plugins.length} plugins covered across ${pages.length} pages.`,
);
