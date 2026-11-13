"use client";

import { useEffect } from "react";

/**
 * Fades `[data-reveal]` elements in as they enter the viewport. One observer
 * for the whole site; a MutationObserver picks up content that streams in or
 * arrives with a client-side navigation after this component mounted.
 */
export function RevealObserver() {
  useEffect(() => {
    if (!("IntersectionObserver" in window)) {
      document.documentElement.classList.add("no-js");
      return;
    }
    const seen = new WeakSet<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          // Also settle anything the visitor has already scrolled past (anchor jumps, End key).
          if (entry.isIntersecting || entry.boundingClientRect.bottom < 0) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.01 },
    );
    const scan = () => {
      document.querySelectorAll("[data-reveal]:not(.is-visible)").forEach((node) => {
        if (seen.has(node)) return;
        seen.add(node);
        io.observe(node);
      });
    };
    scan();
    let queued = false;
    const mo = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        scan();
      });
    });
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, []);
  return null;
}
