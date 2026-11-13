/**
 * E-mail rendering: a deliberately small Markdown subset (so editors cannot inject
 * markup), variable interpolation, and a responsive dark layout.
 * Pure functions — no I/O — so they are unit-tested directly.
 */

export type EmailVars = Record<string, string>;

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Characters that carry meaning in our Markdown subset are neutralised in variable values. */
function neutralise(value: string): string {
  return value.replace(/[*\[\]#`|]/g, "");
}

/** Replaces {{name}} placeholders. Unknown variables become empty strings. */
export function interpolate(template: string, vars: EmailVars, opts: { markdownSafe?: boolean } = {}): string {
  return template.replace(/\{\{\s*([a-zA-Z][\w]*)\s*\}\}/g, (_, name: string) => {
    const value = vars[name] ?? "";
    // URLs are kept verbatim; free text is neutralised so it cannot become markup.
    return opts.markdownSafe && !/^https?:\/\//.test(value) ? neutralise(value) : value;
  });
}

function safeUrl(url: string): string | null {
  const trimmed = url.trim();
  return /^(https?:\/\/|mailto:)/i.test(trimmed) ? trimmed : null;
}

function inline(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label: string, url: string) => {
    const href = safeUrl(url.replace(/&amp;/g, "&"));
    return href ? `<a href="${escapeHtml(href)}" style="color:#00D9FF;text-decoration:underline;">${label}</a>` : label;
  });
  return out;
}

const P = 'style="margin:0 0 18px;font-size:16px;line-height:1.65;color:#D4D4D8;"';

/**
 * Supported syntax: `# H1`, `## H2`, paragraphs, `- ` lists, **bold**, *italic*,
 * [link](https://…) and a call-to-action on its own line: `[[Label|https://…]]`.
 */
export function renderMarkdown(source: string): string {
  const blocks = source.replace(/\r\n/g, "\n").trim().split(/\n{2,}/);
  const html: string[] = [];
  for (const raw of blocks) {
    const block = raw.trim();
    if (!block) continue;
    const button = block.match(/^\[\[([^|\]]+)\|([^\]]+)\]\]$/);
    if (button) {
      const href = safeUrl(button[2]);
      if (href) {
        html.push(
          `<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 26px;"><tr><td style="background:#00D9FF;border-radius:6px;">` +
            `<a href="${escapeHtml(href)}" style="display:inline-block;padding:14px 28px;font-size:14px;font-weight:700;letter-spacing:.08em;color:#050505;text-decoration:none;text-transform:uppercase;">${escapeHtml(button[1].trim())}</a>` +
            `</td></tr></table>`,
        );
      }
      continue;
    }
    if (block.startsWith("## ")) {
      html.push(`<h2 style="margin:28px 0 12px;font-size:20px;line-height:1.3;color:#FFFFFF;">${inline(block.slice(3))}</h2>`);
      continue;
    }
    if (block.startsWith("# ")) {
      html.push(`<h1 style="margin:0 0 20px;font-size:30px;line-height:1.15;letter-spacing:-.02em;color:#FFFFFF;">${inline(block.slice(2))}</h1>`);
      continue;
    }
    const lines = block.split("\n");
    if (lines.every((line) => line.trim().startsWith("- "))) {
      const items = lines.map((line) => `<li style="margin:0 0 8px;">${inline(line.trim().slice(2))}</li>`).join("");
      html.push(`<ul style="margin:0 0 18px;padding-left:22px;font-size:16px;line-height:1.6;color:#D4D4D8;">${items}</ul>`);
      continue;
    }
    html.push(`<p ${P}>${lines.map(inline).join("<br>")}</p>`);
  }
  return html.join("\n");
}

/** Plain-text alternative, derived from the same Markdown source. */
export function renderText(source: string): string {
  return source
    .replace(/\r\n/g, "\n")
    .replace(/^\[\[([^|\]]+)\|([^\]]+)\]\]$/gm, "$1: $2")
    .replace(/^#{1,2}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, "$1 ($2)")
    .trim();
}

export type LayoutInput = {
  locale: string;
  subject: string;
  preheader: string;
  bodyHtml: string;
  /** Footer line explaining why the recipient gets this e-mail. */
  reason: string;
  unsubscribeLabel?: string;
  unsubscribeUrl?: string;
  legalName?: string | null;
  postalAddress?: string | null;
};

export function layout(input: LayoutInput): string {
  const legal = [input.legalName, input.postalAddress].filter(Boolean).map((v) => escapeHtml(v as string)).join(" · ");
  const unsubscribe =
    input.unsubscribeUrl && input.unsubscribeLabel
      ? `<a href="${escapeHtml(input.unsubscribeUrl)}" style="color:#A1A1AA;text-decoration:underline;">${escapeHtml(input.unsubscribeLabel)}</a>`
      : "";
  return `<!doctype html>
<html lang="${escapeHtml(input.locale)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>${escapeHtml(input.subject)}</title>
</head>
<body style="margin:0;padding:0;background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">${escapeHtml(input.preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#050505;">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;">
<tr><td style="padding:0 8px 28px;font-size:18px;font-weight:700;letter-spacing:.32em;color:#FFFFFF;">MILI</td></tr>
<tr><td style="background:#111318;border:1px solid #1F2229;border-radius:12px;padding:36px 32px 22px;">
${input.bodyHtml}
</td></tr>
<tr><td style="padding:24px 8px 0;font-size:12px;line-height:1.6;color:#71717A;">
${escapeHtml(input.reason)}${unsubscribe ? `<br>${unsubscribe}` : ""}${legal ? `<br>${legal}` : ""}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>`;
}
