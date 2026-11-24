export interface ScrapedPage {
  requestedUrl: string;
  url: string;
  title: string | null;
  markdown: string;
  truncated: boolean;
}

interface Source {
  id: string;
  page: ScrapedPage;
  urls: Set<string>;
}

const INLINE_LIMIT = 13_000;
const SOURCE_LIMIT = 8;
const STOP_WORDS = new Set(["about", "from", "into", "that", "the", "this", "what", "which", "with"]);

function urlKey(value: string): string | undefined {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return undefined;
  }
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return undefined;
  url.hash = "";
  const query = new URLSearchParams();
  const googleArticle = url.hostname === "support.google.com" &&
    /^\/(?:mail|a(?:\/users)?)\/answer\/\d+\/?$/.test(url.pathname);
  for (const [name, value] of url.searchParams) {
    const lower = name.toLowerCase();
    if (lower.startsWith("utm_") || ["gclid", "dclid", "fbclid", "msclkid"].includes(lower)) continue;
    if (url.hostname === "slack.com" && name === "nojsmode" && value === "1") continue;
    if (googleArticle && ((name === "hl" && /^en(?:-[a-z]{2})?$/i.test(value)) ||
        (name === "co" && value === "GENIE.Platform=Desktop"))) continue;
    query.append(name, value);
  }
  url.search = query.toString();
  return url.href;
}

function excerpt(line: string, query: string, limit: number): string {
  const match = line.toLowerCase().indexOf(query);
  const offset = match > 120 ? match - 120 : 0;
  return (offset ? "…" : "") + line.slice(offset, offset + limit) +
    (line.length > offset + limit ? "…" : "");
}

export function findPassages(markdown: string, phrase: string) {
  const query = phrase.trim().toLowerCase();
  if (!query) return [];
  const tokens = [...new Set(query.match(/[\p{L}\p{N}]+/gu) ?? [])]
    .filter((word) => !STOP_WORDS.has(word));
  const lines = markdown.split(/\r?\n/);
  const candidates = [];
  for (const [index, line] of lines.entries()) {
    if (!line.trim() || /^\s*(?:[-*]\s+)?\[[^\]]+\]\([^)]+\)\s*$/.test(line)) continue;
    const text = line.toLowerCase();
    const hits = tokens.filter((word) => text.includes(word)).length;
    const direct = text.includes(query);
    if (!direct && hits === 0) continue;
    candidates.push({ index, score: tokens.length * Number(direct) + hits });
  }
  candidates.sort((left, right) => right.score - left.score || left.index - right.index);
  const matches = [];
  const centers: number[] = [];
  for (const { index } of candidates) {
    if (centers.some((center) => Math.abs(index - center) < 5)) continue;
    centers.push(index);
    const start = Math.max(0, index - 2);
    const end = Math.min(lines.length, index + 3);
    const text = lines.slice(start, end)
      .map((line, relative) => excerpt(line, query, start + relative === index ? 720 : 180)).join("\n");
    matches.push({ startLine: start + 1, endLine: end, text });
    if (matches.length === 4) break;
  }
  return matches;
}

export class PageEvidence {
  private nextId = 1;
  private sources = new Map<string, Source>();

  add(page: ScrapedPage) {
    const key = urlKey(page.url);
    const existing = [...this.sources.values()].find((source) =>
      key !== undefined && urlKey(source.page.url) === key && source.page.markdown === page.markdown);
    const source = existing ?? { id: `W${this.nextId++}`, page, urls: new Set<string>() };
    source.urls.add(page.requestedUrl);
    source.urls.add(page.url);
    this.sources.delete(source.id);
    this.sources.set(source.id, source);
    if (this.sources.size > SOURCE_LIMIT) {
      const oldest = this.sources.keys().next();
      if (!oldest.done) this.sources.delete(oldest.value);
    }
    const long = page.markdown.length > INLINE_LIMIT;
    const { markup, headings } = long ? this.preview(page.markdown) : { markup: page.markdown, headings: [] };
    return {
      ...page, markdown: markup, truncated: page.truncated || long,
      sourceId: source.id, alternateUrls: [...source.urls],
      ...(long ? { headings, next: "Use firecrawl_find with this source ID to read passages from the complete page." } : {}),
    };
  }

  find(reference: string, query: string) {
    const source = this.resolve(reference.trim());
    this.sources.delete(source.id);
    this.sources.set(source.id, source);
    return {
      sourceId: source.id, url: source.page.url, title: source.page.title,
      matches: findPassages(source.page.markdown, query),
    };
  }

  private resolve(reference: string): Source {
    const source = this.sources.get(reference);
    if (source) return source;
    const entries = [...this.sources.values()];
    const exact = entries.filter(({ urls }) => urls.has(reference));
    if (exact.length === 1) return exact[0];
    const key = urlKey(reference);
    const equivalent = entries.filter(({ urls }) =>
      key !== undefined && [...urls].some((url) => urlKey(url) === key));
    if (exact.length === 0 && equivalent.length === 1) return equivalent[0];
    throw new Error("Use the source ID from firecrawl_scrape. Read the page again if it has left the page cache.");
  }

  private preview(markdown: string) {
    const headings: string[] = [];
    for (const line of markdown.split(/\r?\n/)) {
      if (/^#{1,6}\s/.test(line)) {
        headings.push(line.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").slice(0, 180));
        if (headings.length === 40) break;
      }
    }
    return { markup: markdown.slice(0, 4000), headings };
  }
}
