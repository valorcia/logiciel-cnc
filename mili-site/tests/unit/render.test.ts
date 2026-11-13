import { describe, expect, it } from "vitest";
import { escapeHtml, interpolate, layout, renderMarkdown, renderText } from "@/lib/email/render";

describe("email rendering", () => {
  it("escapes HTML so an editor cannot inject markup", () => {
    const html = renderMarkdown(`Hello <script>alert(1)</script> & "you"`);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&amp;");
  });

  it("renders headings, emphasis, lists and links", () => {
    const html = renderMarkdown("# Title\n\n**bold** and *italic*\n\n- one\n- two\n\n[site](https://milli.test)");
    expect(html).toContain("<h1");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
    expect(html.match(/<li/g)).toHaveLength(2);
    expect(html).toContain('href="https://milli.test"');
  });

  it("refuses dangerous link and button schemes", () => {
    const html = renderMarkdown("[x](javascript:alert(1))\n\n[[Click|javascript:alert(1)]]\n\n[[Go|https://ok.test/a?b=1&c=2]]");
    expect(html).not.toContain("javascript:");
    expect(html).toContain('href="https://ok.test/a?b=1&amp;c=2"');
  });

  it("interpolates variables and drops unknown ones", () => {
    expect(interpolate("Hi {{ firstName }} {{nope}}!", { firstName: "Ana" })).toBe("Hi Ana !");
  });

  it("neutralises markup characters in free-text variables but keeps URLs intact", () => {
    const out = interpolate("{{name}} {{url}}", { name: "**[x](http://e.vil)**", url: "https://milli.test/i/A_B*C" }, { markdownSafe: true });
    expect(out).toBe("x(http://e.vil) https://milli.test/i/A_B*C");
  });

  it("produces a plain-text alternative", () => {
    expect(renderText("# Title\n\n**Go** [here](https://a.test)\n\n[[Join|https://b.test]]")).toBe(
      "Title\n\nGo here (https://a.test)\n\nJoin: https://b.test",
    );
  });

  it("puts the unsubscribe link and the legal identity in the footer", () => {
    const html = layout({
      locale: "en", subject: "S", preheader: "P", bodyHtml: "<p>x</p>", reason: "Because.",
      unsubscribeLabel: "Unsubscribe", unsubscribeUrl: "https://milli.test/u?t=1", legalName: "MILLI SAS", postalAddress: "1 rue <X>",
    });
    expect(html).toContain('href="https://milli.test/u?t=1"');
    expect(html).toContain("MILLI SAS");
    expect(html).toContain("1 rue &lt;X&gt;");
    expect(escapeHtml("'")).toBe("&#39;");
  });
});
