import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { revealContent } from "@/lib/content";
import type { SiteSettings } from "@/generated/prisma/client";
import { nowMs } from "@/lib/time";
import { Countdown } from "./countdown";
import { VideoPlayer } from "./video-player";

/** Home page opening once an administrator has switched the site to Reveal mode. */
export async function RevealHome({ locale, settings }: { locale: string; settings: SiteSettings }) {
  const t = await getTranslations({ locale, namespace: "reveal" });
  const content = await revealContent(locale);
  if (!content) return null;
  const upcoming = settings.countdownEnabled && settings.launchAt && settings.launchAt.getTime() > nowMs();

  return (
    <section className="relative isolate flex min-h-svh flex-col justify-center overflow-hidden bg-void pb-16 pt-28">
      <div aria-hidden className="glow-cyan pointer-events-none absolute inset-x-0 top-[8%] mx-auto h-[70vh] max-w-5xl" />
      <div className="shell relative text-center">
        <p className="eyebrow mb-6">{t("homeTitle")}</p>
        <h1 className="display display-hero"><span className="text-gradient">{t("heroTitle")}</span></h1>
        <p className="lede mx-auto mt-7 max-w-xl">{t("homeText")}</p>
        <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
          {settings.kickstarterUrl ? (
            <a href={settings.kickstarterUrl} rel="noopener" className="btn btn-primary w-full sm:w-auto">{t("cta")}</a>
          ) : (
            <span className="btn btn-ghost w-full sm:w-auto" aria-disabled="true">{t("ctaSoon")}</span>
          )}
          <Link href="/mili" className="btn btn-ghost w-full sm:w-auto">{t("discover")}</Link>
        </div>
        {upcoming && (
          <div className="mt-14 flex justify-center"><Countdown target={settings.launchAt!.toISOString()} /></div>
        )}
        {content.filmUrl ? (
          <div className="mx-auto mt-16 max-w-5xl">
            <VideoPlayer video={content.filmUrl} title={t("watch")} playLabel={t("watch")} poster={content.heroImageId ? `/media/${content.heroImageId}` : null} />
          </div>
        ) : content.heroImageId ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`/media/${content.heroImageId}`} alt="MILI" fetchPriority="high" className="mx-auto mt-16 aspect-[16/9] w-full max-w-6xl rounded-2xl border border-line object-cover" />
        ) : null}
      </div>
    </section>
  );
}
