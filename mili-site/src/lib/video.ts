/**
 * Video sources. Streaming providers are embedded in an iframe that is only
 * created when the visitor presses play (no third-party request before that);
 * direct files use the native player with preload="none".
 */

export type VideoSource =
  | { kind: "embed"; provider: string; src: string; thumbnail?: string }
  | { kind: "file"; src: string };

const IFRAME_HOSTS = [
  "iframe.mediadelivery.net",
  "iframe.videodelivery.net",
  "player.mux.com",
];

export function parseVideoUrl(raw: string): VideoSource | null {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  const host = url.hostname.replace(/^www\./, "");

  if (host === "youtube.com" || host === "m.youtube.com" || host === "youtube-nocookie.com") {
    const id = url.searchParams.get("v") ?? url.pathname.match(/^\/(?:embed|shorts)\/([\w-]{6,})/)?.[1];
    return id && /^[\w-]{6,20}$/.test(id) ? youtube(id) : null;
  }
  if (host === "youtu.be") {
    const id = url.pathname.slice(1);
    return /^[\w-]{6,20}$/.test(id) ? youtube(id) : null;
  }
  if (host === "vimeo.com" || host === "player.vimeo.com") {
    const id = url.pathname.match(/(\d{6,12})/)?.[1];
    return id ? { kind: "embed", provider: "vimeo", src: `https://player.vimeo.com/video/${id}?autoplay=1&dnt=1` } : null;
  }
  if (IFRAME_HOSTS.includes(host) || host.endsWith(".cloudflarestream.com")) {
    return { kind: "embed", provider: host, src: url.toString() };
  }
  if (/\.(mp4|webm)$/i.test(url.pathname)) return { kind: "file", src: url.toString() };
  return null;
}

function youtube(id: string): VideoSource {
  return {
    kind: "embed",
    provider: "youtube",
    src: `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0&modestbranding=1`,
    thumbnail: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
  };
}

export function formatDuration(totalSec: number | null | undefined): string | null {
  if (!totalSec || totalSec <= 0) return null;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
