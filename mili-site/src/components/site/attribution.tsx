"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

const KEY = "milli_attr";
const UTM = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"] as const;

export type StoredAttribution = Partial<Record<(typeof UTM)[number], string>> & { referrer?: string; landing?: string };

/** First-touch attribution of this browser session (sessionStorage — no cookie). */
export function readAttribution(): StoredAttribution {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "{}") as StoredAttribution;
  } catch {
    return {};
  }
}

/**
 * Remembers where the visitor came from and reports one anonymous page view.
 * No cookie, no identifier: see src/lib/analytics.ts.
 */
export function Attribution({ locale }: { locale: string }) {
  const pathname = usePathname();
  useEffect(() => {
    let stored = readAttribution();
    if (!stored.landing) {
      const params = new URLSearchParams(window.location.search);
      stored = { landing: window.location.pathname, referrer: document.referrer || undefined };
      for (const key of UTM) {
        const value = params.get(key);
        if (value) stored[key] = value.slice(0, 100);
      }
      try {
        sessionStorage.setItem(KEY, JSON.stringify(stored));
      } catch {}
    }
    const send = () => {
      const body = JSON.stringify({ path: window.location.pathname, locale, ...stored });
      if (navigator.sendBeacon) navigator.sendBeacon("/api/track", new Blob([body], { type: "application/json" }));
      else void fetch("/api/track", { method: "POST", body, headers: { "content-type": "application/json" }, keepalive: true });
    };
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1200));
    const handle = idle(send);
    return () => (window.cancelIdleCallback ?? window.clearTimeout)(handle as number);
  }, [pathname, locale]);
  return null;
}
