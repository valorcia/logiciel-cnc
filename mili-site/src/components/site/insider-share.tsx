"use client";

import { useState } from "react";

type Props = {
  link: string;
  urls: Record<"whatsapp" | "facebook" | "x" | "reddit" | "email" | "copy", string>;
  labels: { copy: string; copied: string; share: string; text: string; subject: string };
};

const enc = encodeURIComponent;

export function InsiderShare({ link, urls, labels }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(urls.copy);
    } catch {
      const input = document.getElementById("insider-link") as HTMLInputElement | null;
      input?.select();
      document.execCommand("copy");
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2200);
  };
  const channels = [
    { key: "whatsapp", label: "WhatsApp", href: `https://wa.me/?text=${enc(`${labels.text} ${urls.whatsapp}`)}` },
    { key: "facebook", label: "Facebook", href: `https://www.facebook.com/sharer/sharer.php?u=${enc(urls.facebook)}` },
    { key: "x", label: "X", href: `https://twitter.com/intent/tweet?text=${enc(labels.text)}&url=${enc(urls.x)}` },
    { key: "reddit", label: "Reddit", href: `https://www.reddit.com/submit?url=${enc(urls.reddit)}&title=${enc(labels.text)}` },
    { key: "email", label: "E-mail", href: `mailto:?subject=${enc(labels.subject)}&body=${enc(`${labels.text}\n\n${urls.email}`)}` },
  ];

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input id="insider-link" readOnly value={link} aria-label={labels.copy} onFocus={(e) => e.currentTarget.select()} className="field flex-1 font-mono text-sm" />
        <button type="button" onClick={copy} className="btn btn-primary flex-none">
          <span aria-live="polite">{copied ? labels.copied : labels.copy}</span>
        </button>
      </div>
      <ul className="mt-5 flex flex-wrap gap-2" aria-label={labels.share}>
        {channels.map((c) => (
          <li key={c.key}>
            <a href={c.href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center rounded-full border border-line px-5 text-sm text-white transition hover:border-white">
              {c.label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
