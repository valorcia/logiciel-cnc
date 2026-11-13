import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { formatUsd } from "@/lib/settings";
import type { SiteSettings } from "@/generated/prisma/client";
import { Countdown } from "./countdown";
import { Particles } from "./particles";

/**
 * Full-screen opening. The three-beat intro ("5 AXES." → "$1,499." → "IMPOSSIBLE?")
 * is pure CSS: it plays before hydration, costs no JavaScript, and the real
 * <h1> is in the HTML from the first byte.
 */
export async function Hero({ locale, settings }: { locale: string; settings: SiteSettings }) {
  const t = await getTranslations({ locale, namespace: "hero" });
  const price = formatUsd(settings.plannedPriceCents);
  const words = [t("word1"), ...(settings.showPlannedPrice ? [`${price}.`] : []), t("word3")];
  const showCountdown = settings.countdownEnabled && settings.launchAt;

  return (
    <section className="relative isolate flex min-h-svh flex-col overflow-hidden bg-void">
      <div aria-hidden className="glow-cyan pointer-events-none absolute inset-x-0 top-[12%] mx-auto h-[70vh] max-w-5xl" />
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_100%,rgb(120_86_255/0.10),transparent_60%)]" />
      <Particles />

      {/* Intro beats — decorative repetition of what the page states below. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 z-10">
        {words.map((word) => (
          <p key={word} className="intro-word display display-hero px-4 text-center">
            {word}
          </p>
        ))}
      </div>

      <div className="shell relative z-20 flex flex-1 flex-col items-center justify-center pb-10 pt-28 text-center">
        <div className="intro-final">
          <p className="eyebrow mb-6">
            {t("word1").replace(/\.$/, "")}
            {settings.showPlannedPrice && <> · {price}</>} · <span className="text-white">{t("word3")}</span>
          </p>
          <h1 className="display display-hero">
            <span className="text-gradient">{t("title")}</span>
          </h1>
          <p className="lede mx-auto mt-7 max-w-xl">{t("subtitle")}</p>
        </div>

        <div className="intro-late mt-10 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row">
          <Link href="/#join" className="btn btn-primary w-full sm:w-auto">{t("ctaPrimary")}</Link>
          <Link href="/#mystery" className="btn btn-ghost w-full sm:w-auto">{t("ctaSecondary")}</Link>
        </div>

        {showCountdown && (
          <div className="intro-late mt-14">
            <Countdown target={settings.launchAt!.toISOString()} />
          </div>
        )}

        {settings.showPlannedPrice && (
          <p className="intro-late mt-10 max-w-md text-xs leading-relaxed text-smoke">
            {price} — {t("priceNote")}
          </p>
        )}
      </div>

      <div aria-hidden className="intro-late relative z-20 flex justify-center pb-7">
        <span className="eyebrow flex flex-col items-center gap-2 text-[0.625rem]">
          {t("scroll")}
          <span className="block h-8 w-px bg-gradient-to-b from-ash to-transparent" />
        </span>
      </div>
    </section>
  );
}
