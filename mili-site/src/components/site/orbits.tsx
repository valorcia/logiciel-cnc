"use client";

import { useEffect, useRef } from "react";

/**
 * Five independent motions, deliberately abstract: five points on five orbits.
 * It evokes "five axes" and says nothing about the machine's real kinematics.
 */
const ORBITS = [
  { rx: 62, ry: 26, tilt: -18, period: 17, color: "#00D9FF", phase: 0.1 },
  { rx: 98, ry: 61, tilt: 24, period: 26, color: "#FFFFFF", phase: 0.45 },
  { rx: 105, ry: 134, tilt: -40, period: 34, color: "#7856FF", phase: 0.7 },
  { rx: 170, ry: 58, tilt: 62, period: 43, color: "#FFFFFF", phase: 0.25 },
  { rx: 206, ry: 103, tilt: 8, period: 55, color: "#00D9FF", phase: 0.85 },
];

const at = (o: (typeof ORBITS)[number], turns: number) => {
  const a = turns * Math.PI * 2;
  return { x: o.rx * Math.cos(a), y: o.ry * Math.sin(a) };
};

export function Orbits({ label }: { label: string }) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!svg || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const dots = [...svg.querySelectorAll<SVGGElement>("[data-dot]")];
    let raf = 0;
    const frame = (now: number) => {
      const t = now / 1000;
      dots.forEach((dot, i) => {
        const o = ORBITS[i];
        const p = at(o, o.phase + (i % 2 ? -1 : 1) * (t / o.period));
        dot.setAttribute("transform", `translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`);
      });
      raf = requestAnimationFrame(frame);
    };
    const io = new IntersectionObserver(([entry]) => {
      cancelAnimationFrame(raf);
      if (entry.isIntersecting) raf = requestAnimationFrame(frame);
    });
    io.observe(svg);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, []);

  return (
    <svg ref={ref} viewBox="-240 -240 480 480" className="relative h-full w-full" role="img" aria-label={label}>
      {ORBITS.map((o, i) => {
        const p = at(o, o.phase);
        return (
          <g key={i} transform={`rotate(${o.tilt})`}>
            <ellipse rx={o.rx} ry={o.ry} fill="none" stroke="#2a2d36" strokeWidth="1" />
            <g data-dot transform={`translate(${p.x.toFixed(2)} ${p.y.toFixed(2)})`}>
              <circle r="10" fill={o.color} opacity="0.14" />
              <circle r="3.4" fill={o.color} />
            </g>
            <text x={o.rx + 10} y="-6" fill="#71717a" fontSize="9" letterSpacing="2" fontFamily="var(--font-mono)">
              {String(i + 1).padStart(2, "0")}
            </text>
          </g>
        );
      })}
      <circle r="2.5" fill="#fff" className="pulse-dot" />
    </svg>
  );
}
