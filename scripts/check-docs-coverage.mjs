import { readFile, readdir } from "node:fs/promises";

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

const pageNameForPlugin = (id) => {
  if (id === "mere-doc-tools") return "document-tools.md";
  if (id === "mere-runpod") return "runpod.md";
  return `${id.replace(/^mere-/, "")}.md`;
};

const failures = [];
for (const plugin of catalog.plugins) {
  const pageName = pageNameForPlugin(plugin.id);
  const page = corpus.get(pageName);
  if (!page) {
    failures.push(`${plugin.id}: missing docs/plugins/${pageName}`);
  } else if (!page.includes(plugin.id)) {
    failures.push(
      `${plugin.id}: docs/plugins/${pageName} does not name the catalog ID`,
    );
  }
}

const contractReference = await readFile(
  new URL("docs/reference/contracts.md", repoRoot),
  "utf8",
);
const contractFiles = (await readdir(new URL("contracts/", repoRoot))).filter(
  (name) => name.endsWith(".schema.json"),
);
for (const contractFile of contractFiles) {
  if (!contractReference.includes(contractFile)) {
    failures.push(`${contractFile}: missing from docs/reference/contracts.md`);
  }
}

const docsHome = await readFile(new URL("docs/index.md", repoRoot), "utf8");
const pluginIndex = corpus.get("index.md") ?? "";
const catalogCount = catalog.plugins.length;
if (!docsHome.includes(`${catalogCount} official companion commands`)) {
  failures.push(`docs/index.md: missing catalog count ${catalogCount}`);
}
if (!pluginIndex.includes(`${catalogCount} official companion executables`)) {
  failures.push(`docs/plugins/index.md: missing catalog count ${catalogCount}`);
}

const guideFiles = (await readdir(new URL("docs/guide/", repoRoot))).filter(
  (name) => name.endsWith(".md"),
);
const referenceFiles = (
  await readdir(new URL("docs/reference/", repoRoot))
).filter((name) => name.endsWith(".md"));
const operationsFiles = (
  await readdir(new URL("docs/operations/", repoRoot))
).filter((name) => name.endsWith(".md"));
const recipeFiles = (await readdir(new URL("docs/recipes/", repoRoot))).filter(
  (name) => name.endsWith(".md"),
);
const proseFiles = [
  ["docs/index.md", docsHome],
  ...[...corpus].map(([name, value]) => [`docs/plugins/${name}`, value]),
];
for (const [directory, names] of [
  ["docs/guide/", guideFiles],
  ["docs/reference/", referenceFiles],
  ["docs/operations/", operationsFiles],
  ["docs/recipes/", recipeFiles],
]) {
  for (const name of names) {
    proseFiles.push([
      `${directory}${name}`,
      await readFile(new URL(`${directory}${name}`, repoRoot), "utf8"),
    ]);
  }
}
for (const [name, content] of proseFiles) {
  if (content.includes("mere.run models ")) {
    failures.push(`${name}: use the singular 'mere.run model' command group`);
  }
  if (name !== "docs/index.md") {
    const headings = content.match(/^#{1,6} .+$/gm) ?? [];
    const levelOneHeadings = headings.filter((heading) =>
      heading.startsWith("# "),
    );
    if (levelOneHeadings.length !== 1) {
      failures.push(`${name}: expected exactly one level-one heading`);
    }
    if (headings.some((heading) => /^#{2,6} \d+\./.test(heading))) {
      failures.push(`${name}: remove sequence numbers from headings`);
    }
  }
}

if (failures.length > 0) {
  const report = failures.map((item) => `- ${item}`).join("\n");
  console.error(`Documentation coverage failed:\n${report}`);
  process.exit(1);
}

console.log(
  `Docs coverage OK: ${catalogCount} plugin pages and ` +
    `${contractFiles.length} contract schemas documented.`,
);
