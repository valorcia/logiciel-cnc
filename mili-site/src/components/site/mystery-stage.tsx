"use client";

import { useEffect, useRef } from "react";

type Props = { hint: string; classified: string; known: string[]; axisLabels: string[] };

/**
 * "Partial reveal": a light follows the pointer across a classified sheet.
 * What it uncovers is only what is already public; every other line is a
 * redaction bar with no text behind it — there is nothing to extract.
 */
export function MysteryStage({ hint, classified, known, axisLabels }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let auto = true;
    const set = (x: number, y: number) => {
      el.style.setProperty("--mx", `${x}%`);
      el.style.setProperty("--my", `${y}%`);
    };
    set(50, 38);
    if (reduce) return;

    const start = performance.now();
    const loop = (now: number) => {
      if (auto) {
        const t = (now - start) / 1000;
        set(50 + 34 * Math.sin(t * 0.55), 48 + 30 * Math.sin(t * 0.38 + 1.2));
      }
      raf = requestAnimationFrame(loop);
    };
    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      auto = false;
      set(((e.clientX - rect.left) / rect.width) * 100, ((e.clientY - rect.top) / rect.height) * 100);
    };
    const onLeave = () => {
      auto = true;
    };
    const io = new IntersectionObserver(([entry]) => {
      cancelAnimationFrame(raf);
      if (entry.isIntersecting) raf = requestAnimationFrame(loop);
    });
    io.observe(el);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  const widths = ["72%", "54%", "86%", "40%", "64%"];

  return (
    <div
      ref={ref}
      className="panel relative overflow-hidden p-6 font-mono text-sm sm:p-8"
      style={{ "--mx": "50%", "--my": "38%" } as React.CSSProperties}
    >
      <div className="mb-6 flex items-center justify-between text-[0.6875rem] uppercase tracking-[0.22em] text-smoke">
        <span>MILI / 000</span>
        <span className="text-cyan">{classified}</span>
      </div>

      <ul className="space-y-4">
        {axisLabels.map((label, i) => (
          <li key={label} className="flex items-center gap-4">
            <span className="w-20 shrink-0 text-smoke">{label}</span>
            <span aria-hidden className="redacted block h-3.5" style={{ width: widths[i] }}>&nbsp;</span>
          </li>
        ))}
      </ul>

      <div className="mt-8 border-t border-line pt-6">
        <ul className="flex flex-wrap gap-2">
          {known.map((item) => (
            <li key={item} className="rounded-full border border-line px-3.5 py-1.5 text-xs text-white">{item}</li>
          ))}
        </ul>
        <p className="mt-6 text-xs text-smoke">{hint}</p>
      </div>

      {/* The travelling light. Purely visual: it uncovers no hidden text. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(14rem circle at var(--mx) var(--my), rgb(0 217 255 / 0.16), transparent 70%)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 mix-blend-overlay"
        style={{ background: "radial-gradient(9rem circle at var(--mx) var(--my), rgb(255 255 255 / 0.5), transparent 70%)" }}
      />
    </div>
  );
}
