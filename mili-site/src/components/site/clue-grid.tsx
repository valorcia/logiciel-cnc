"use client";

import { useEffect, useState } from "react";
import type { PublicClue } from "@/lib/content";
import { VideoPlayer } from "./video-player";

type Item = PublicClue & { label: string; lockLabel: string };
type Props = { items: Item[]; labels: { locked: string; fresh: string; watch: string } };

const KEY = "milli_clues_seen";

/** A clue the visitor has not seen yet plays its unlock animation once. */
export function ClueGrid({ items, labels }: Props) {
  const [fresh, setFresh] = useState<number[]>([]);

  useEffect(() => {
    const unlocked = items.filter((i) => i.unlocked).map((i) => i.number);
    let seen: number[] | null = null;
    try {
      const raw = localStorage.getItem(KEY);
      seen = raw ? (JSON.parse(raw) as number[]) : null;
    } catch {}
    // First visit: everything currently open is simply "the state of things", not news.
    if (seen) {
      const known = seen;
      queueMicrotask(() => setFresh(unlocked.filter((n) => !known.includes(n))));
    }
    try {
      localStorage.setItem(KEY, JSON.stringify(unlocked));
    } catch {}
  }, [items]);

  return (
    <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((clue) => {
        const isFresh = fresh.includes(clue.number);
        return (
          <li
            key={clue.number}
            className={`panel relative flex min-h-64 flex-col overflow-hidden p-6 sm:p-7 ${clue.unlocked ? "" : "opacity-80"} ${isFresh ? "clue-unlock" : ""}`}
          >
            {isFresh && <span aria-hidden className="scanline" />}
            <div className="flex items-center justify-between font-mono text-[0.6875rem] uppercase tracking-[0.2em]">
              <span className={clue.unlocked ? "text-cyan" : "text-smoke"}>{clue.label}</span>
              {isFresh ? (
                <span className="rounded-full bg-cyan px-2 py-0.5 font-sans text-[0.625rem] font-semibold tracking-[0.12em] text-void">{labels.fresh}</span>
              ) : !clue.unlocked ? (
                <span className="inline-flex items-center gap-1.5 text-smoke">
                  <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden><path d="M4.5 7V5a3.5 3.5 0 017 0v2M3.5 7h9v6.5h-9z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" /></svg>
                  {labels.locked}
                </span>
              ) : null}
            </div>

            {clue.unlocked ? (
              <div className="mt-8 flex flex-1 flex-col">
                <h3 className="text-2xl font-semibold leading-tight tracking-tight">{clue.title}</h3>
                {clue.content && <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ash">{clue.content}</p>}
                {clue.imageId && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`/media/${clue.imageId}`} alt="" loading="lazy" decoding="async" className="mt-5 aspect-video w-full rounded-lg object-cover" />
                )}
                {clue.video && (
                  <div className="mt-5">
                    <VideoPlayer video={clue.video} title={clue.title ?? clue.label} playLabel={labels.watch} />
                  </div>
                )}
              </div>
            ) : (
              /* Locked: the server sent no title and no content — only bars. */
              <div className="mt-8 flex flex-1 flex-col" aria-hidden>
                <span className="redacted block h-6 w-4/5">&nbsp;</span>
                <span className="redacted mt-4 block h-3 w-full">&nbsp;</span>
                <span className="redacted mt-2.5 block h-3 w-2/3">&nbsp;</span>
              </div>
            )}
            {!clue.unlocked && <p className="mt-6 text-xs text-smoke">{clue.lockLabel}</p>}
          </li>
        );
      })}
    </ol>
  );
}
