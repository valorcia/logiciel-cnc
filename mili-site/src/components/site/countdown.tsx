"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

type Props = { target: string; compact?: boolean };

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Countdown to an absolute instant. The server clock is fetched once so a
 * wrong device clock cannot shift it; the device's time zone only affects the
 * human-readable date underneath. Reaching zero reveals nothing by itself.
 */
export function Countdown({ target, compact = false }: Props) {
  const t = useTranslations("countdown");
  const format = useFormatter();
  const targetMs = new Date(target).getTime();
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    fetch("/api/time", { cache: "no-store" })
      .then((r) => r.json())
      .then((data: { now: number }) => {
        if (cancelled) return;
        const rtt = Date.now() - started;
        setOffset(data.now + rtt / 2 - Date.now());
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const tick = () => setNow(Date.now() + offset);
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [offset]);

  // Server render and first client render show the same placeholder: no hydration mismatch.
  const remaining = now === null ? null : Math.max(0, targetMs - now);

  if (remaining === 0) {
    return (
      <div role="status" className="text-center">
        <p className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("zeroTitle")}</p>
        <p className="mt-2 text-sm text-ash">{t("zeroText")}</p>
      </div>
    );
  }

  const total = remaining === null ? null : Math.floor(remaining / 1000);
  const units: [string, string][] = [
    [total === null ? "--" : String(Math.floor(total / 86400)).padStart(2, "0"), t("days")],
    [total === null ? "--" : pad(Math.floor((total % 86400) / 3600)), t("hours")],
    [total === null ? "--" : pad(Math.floor((total % 3600) / 60)), t("minutes")],
    [total === null ? "--" : pad(total % 60), t("seconds")],
  ];

  return (
    <div className="text-center">
      {!compact && <p className="eyebrow mb-4">{t("caption")}</p>}
      <div
        className="inline-grid grid-cols-4 gap-2 sm:gap-4"
        role="timer"
        aria-label={units.map(([value, label]) => `${value} ${label}`).join(", ")}
      >
        {units.map(([value, label]) => (
          <div key={label} className="min-w-[4.25rem] rounded-xl border border-line bg-carbon/60 px-2 py-3 backdrop-blur-sm sm:min-w-24 sm:px-4 sm:py-4" aria-hidden>
            <div className="font-mono text-3xl font-medium tabular-nums tracking-tight sm:text-5xl">
              <span key={value} className="tick">{value}</span>
            </div>
            <div className="mt-1.5 text-[0.625rem] uppercase tracking-[0.2em] text-ash sm:text-xs">{label}</div>
          </div>
        ))}
      </div>
      {!compact && now !== null && (
        <p className="mt-4 text-xs text-smoke">
          {t("localTime", { date: format.dateTime(new Date(targetMs), { dateStyle: "long", timeStyle: "short" }) })}
        </p>
      )}
    </div>
  );
}
