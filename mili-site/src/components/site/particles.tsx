"use client";

import { useEffect, useRef } from "react";

/**
 * Very discreet metallic dust. Starts after the page is idle, pauses when the
 * hero is off screen or the tab is hidden, and never runs for visitors who
 * prefer reduced motion.
 */
export function Particles({ density = 0.00006 }: { density?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    type P = { x: number; y: number; z: number; vx: number; vy: number; tw: number; hue: 0 | 1 | 2 };
    let particles: P[] = [];
    let width = 0, height = 0, raf = 0, running = false, visible = true, last = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.min(150, Math.max(36, Math.round(width * height * density)));
      particles = Array.from({ length: count }, () => {
        const roll = Math.random();
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          z: 0.25 + Math.random() * 0.75,
          vx: (Math.random() - 0.5) * 0.05,
          vy: -0.02 - Math.random() * 0.06,
          tw: Math.random() * Math.PI * 2,
          hue: roll > 0.94 ? 1 : roll > 0.9 ? 2 : 0,
        };
      });
    };

    const frame = (now: number) => {
      const dt = Math.min(48, now - (last || now));
      last = now;
      ctx.clearRect(0, 0, width, height);
      for (const p of particles) {
        p.x += p.vx * dt * p.z;
        p.y += p.vy * dt * p.z;
        p.tw += 0.0012 * dt;
        if (p.y < -4) { p.y = height + 4; p.x = Math.random() * width; }
        if (p.x < -4) p.x = width + 4;
        if (p.x > width + 4) p.x = -4;
        const glint = 0.5 + 0.5 * Math.sin(p.tw);
        const alpha = (0.1 + 0.42 * glint) * p.z;
        ctx.fillStyle =
          p.hue === 1 ? `rgba(0,217,255,${alpha})` : p.hue === 2 ? `rgba(120,86,255,${alpha})` : `rgba(210,214,222,${alpha * 0.75})`;
        const r = 0.5 + p.z * 0.9;
        ctx.fillRect(p.x, p.y, r, r);
      }
      if (running) raf = requestAnimationFrame(frame);
    };

    const start = () => {
      if (running || !visible || document.hidden) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
      else stop();
    });
    const onVisibility = () => (document.hidden ? stop() : start());
    const onResize = () => resize();

    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
    const handle = idle(() => {
      resize();
      io.observe(canvas);
      document.addEventListener("visibilitychange", onVisibility);
      window.addEventListener("resize", onResize);
      start();
    });

    return () => {
      (window.cancelIdleCallback ?? window.clearTimeout)(handle as number);
      stop();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
    };
  }, [density]);

  return <canvas ref={ref} aria-hidden className="pointer-events-none absolute inset-0 h-full w-full" />;
}
