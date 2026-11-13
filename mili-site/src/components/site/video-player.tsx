"use client";

import { useState } from "react";
import type { VideoSource } from "@/lib/video";

type Props = { video: VideoSource; poster?: string | null; title: string; playLabel: string; badge?: React.ReactNode; duration?: string | null };

/**
 * Nothing is requested from a third-party video host until the visitor presses
 * play: the iframe (or the <video> source) is created on click.
 */
export function VideoPlayer({ video, poster, title, playLabel, badge, duration }: Props) {
  const [playing, setPlaying] = useState(false);

  if (playing) {
    return (
      <div className="relative aspect-video overflow-hidden rounded-xl bg-black">
        {video.kind === "embed" ? (
          <iframe
            src={video.src} title={title} className="absolute inset-0 h-full w-full"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <video src={video.src} controls autoPlay playsInline className="absolute inset-0 h-full w-full" />
        )}
      </div>
    );
  }

  return (
    <button
      type="button" onClick={() => setPlaying(true)} aria-label={`${playLabel}: ${title}`}
      className="group relative block aspect-video w-full overflow-hidden rounded-xl border border-line bg-carbon text-left"
    >
      {poster ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={poster} alt="" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover opacity-80 transition duration-500 group-hover:scale-[1.03] group-hover:opacity-100" />
      ) : (
        <span aria-hidden className="glow-cyan absolute inset-0" />
      )}
      <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      <span aria-hidden className="absolute left-1/2 top-1/2 grid h-16 w-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/40 bg-black/40 backdrop-blur transition duration-300 group-hover:scale-110 group-hover:border-cyan">
        <svg viewBox="0 0 24 24" className="ml-1 h-6 w-6 fill-white"><path d="M8 5v14l11-7z" /></svg>
      </span>
      {badge && <span className="absolute left-3 top-3">{badge}</span>}
      {duration && <span className="absolute bottom-3 right-3 rounded bg-black/70 px-2 py-0.5 font-mono text-xs text-white">{duration}</span>}
    </button>
  );
}
