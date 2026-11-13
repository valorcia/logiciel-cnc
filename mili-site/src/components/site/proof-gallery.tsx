"use client";

import { useMemo, useState } from "react";
import type { PublicProof } from "@/lib/content";
import { VideoPlayer } from "./video-player";

type Item = PublicProof & { durationLabel: string | null; dateLabel: string | null; categoryLabel: string };
type Props = { items: Item[]; labels: { all: string; validated: string; play: string } };

export function ProofGallery({ items, labels }: Props) {
  const categories = useMemo(() => {
    const seen = new Map<string, string>();
    for (const item of items) seen.set(item.category, item.categoryLabel);
    return [...seen.entries()];
  }, [items]);
  const [active, setActive] = useState<string | null>(null);
  const shown = active ? items.filter((i) => i.category === active) : items;

  return (
    <div>
      {categories.length > 1 && (
        <div className="mb-10 flex flex-wrap justify-center gap-2" role="group" aria-label={labels.all}>
          {[[null, labels.all] as const, ...categories.map(([k, l]) => [k, l] as const)].map(([key, label]) => (
            <button
              key={key ?? "all"} type="button" onClick={() => setActive(key)} aria-pressed={active === key}
              className={`rounded-full border px-4 py-2 text-xs font-medium uppercase tracking-[0.14em] transition ${active === key ? "border-white bg-white text-void" : "border-line text-ash hover:border-white hover:text-white"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <ul className="grid gap-x-6 gap-y-12 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((item) => (
          <li key={item.id}>
            <VideoPlayer
              video={item.video}
              poster={item.posterId ? `/media/${item.posterId}` : item.video.kind === "embed" ? (item.video.thumbnail ?? null) : null}
              title={item.title} playLabel={labels.play} duration={item.durationLabel}
              badge={
                <span className="inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-[0.6875rem] font-medium text-cyan backdrop-blur">
                  <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden><path d="M3 8.5l3.2 3.2L13 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  {labels.validated}
                </span>
              }
            />
            <p className="mt-4 text-[0.6875rem] uppercase tracking-[0.18em] text-smoke">
              {item.categoryLabel}{item.dateLabel ? ` · ${item.dateLabel}` : ""}
            </p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight">{item.title}</h3>
            {item.description && <p className="mt-2 text-sm leading-relaxed text-ash">{item.description}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
