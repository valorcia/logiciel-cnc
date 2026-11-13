/**
 * Small, dependency-free Markdown renderer for administrator-written content
 * (journal articles, product sections). Everything is HTML-escaped first; the
 * only tags that can come out are the ones generated here.
 *
 * Supported: ## / ### headings, paragraphs, - and 1. lists, > quotes,
 * **bold**, *italic*, `code`, [links](https://… or /path), ![images](/media/ID).
 */

const escapeHtml = (v: string) =>
  v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

function safeHref(raw: string): string | null {
  const url = raw.replace(/&amp;/g, "&").trim();
  if (/^\/(?!\/)/.test(url) || url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "mailto:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function inline(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/!\[([^\]]*)\]\((\/media\/[a-z0-9]+)\)/g, '<img src="$2" alt="$1" loading="lazy" decoding="async">');
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, url: string) => {
    const href = safeHref(url);
    if (!href) return label;
    const external = href.startsWith("https:");
    return `<a href="${escapeHtml(href)}"${external ? ' rel="noopener noreferrer" target="_blank"' : ""}>${label}</a>`;
  });
  return out;
}

export function renderSiteMarkdown(source: string): string {
  const blocks = source.replace(/\r\n/g, "\n").trim().split(/\n{2,}/);
  const html: string[] = [];
  for (const raw of blocks) {
    const block = raw.trim();
    if (!block) continue;
    if (block.startsWith("### ")) { html.push(`<h3>${inline(block.slice(4))}</h3>`); continue; }
    if (block.startsWith("## ")) { html.push(`<h2>${inline(block.slice(3))}</h2>`); continue; }
    if (block.startsWith("# ")) { html.push(`<h2>${inline(block.slice(2))}</h2>`); continue; }
    const lines = block.split("\n").map((l) => l.trim());
    if (lines.every((l) => l.startsWith("- "))) { html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`); continue; }
    if (lines.every((l) => /^\d+\.\s/.test(l))) { html.push(`<ol>${lines.map((l) => `<li>${inline(l.replace(/^\d+\.\s/, ""))}</li>`).join("")}</ol>`); continue; }
    if (lines.every((l) => l.startsWith(">"))) { html.push(`<blockquote>${lines.map((l) => inline(l.replace(/^>\s?/, ""))).join("<br>")}</blockquote>`); continue; }
    html.push(`<p>${lines.map(inline).join("<br>")}</p>`);
  }
  return html.join("\n");
}

/** Plain-text excerpt for meta descriptions. */
export function excerpt(source: string, max = 160): string {
  const text = source.replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[#>*`]/g, "").replace(/\s+/g, " ").trim();
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}
