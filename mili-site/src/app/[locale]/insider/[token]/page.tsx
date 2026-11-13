import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { InsiderData } from "@/components/site/insider-data";
import { InsiderShare } from "@/components/site/insider-share";
import { StatusPage } from "@/components/site/page-shell";
import { Link } from "@/i18n/navigation";
import { db } from "@/lib/db";
import { pickText } from "@/lib/i18n/config";
import { referralShareUrl, referralUrl, SHARE_CHANNELS } from "@/lib/links";
import { getSettings } from "@/lib/settings";
import { leaderboard, referralRank, referralStats, subscriberFromToken } from "@/lib/subscribers";

export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };
export const dynamic = "force-dynamic";

type Props = { params: Promise<{ locale: string; token: string }> };

export default async function InsiderPage({ params }: Props) {
  const { locale, token } = await params;
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "insider" });
  const e = await getTranslations({ locale, namespace: "errors" });
  const sub = await subscriberFromToken(token);

  if (!sub) return <StatusPage title={t("title")}><p>{t("invalid")}</p><Link href="/#join" className="btn btn-primary mt-9">MILLI</Link></StatusPage>;
  if (sub.status === "PENDING") return <StatusPage title={t("pendingTitle")}><p>{t("pendingText")}</p></StatusPage>;

  const [stats, rewards, settings] = await Promise.all([
    referralStats(sub.id),
    db.referralReward.findMany({ where: { active: true }, orderBy: { threshold: "asc" } }),
    getSettings(),
  ]);
  const [rank, top] = await Promise.all([
    referralRank(sub.id, stats.points),
    settings.leaderboardEnabled ? leaderboard(10) : Promise.resolve([]),
  ]);
  const next = rewards.find((r) => r.threshold > stats.points);
  const previous = [...rewards].reverse().find((r) => r.threshold <= stats.points);
  const span = next ? next.threshold - (previous?.threshold ?? 0) : 1;
  const progress = next ? Math.min(100, Math.round(((stats.points - (previous?.threshold ?? 0)) / span) * 100)) : 100;
  const urls = Object.fromEntries(SHARE_CHANNELS.map((c) => [c, referralShareUrl(sub.referralCode, c)])) as Record<(typeof SHARE_CHANNELS)[number], string>;
  const cleanToken = decodeURIComponent(token);

  return (
    <div className="shell pb-28 pt-[calc(var(--header-h)+4rem)]">
      <p className="eyebrow mb-5">{t("title")}</p>
      <h1 className="display display-lg">{sub.firstName ? t("hello", { name: sub.firstName }) : t("helloAnon")}</h1>
      <p className="mt-4 font-mono text-sm text-ash">{t("id")} · <span className="text-cyan">{sub.publicId}</span>{previous ? <> · <span className="text-white">{previous.name}</span></> : null}</p>

      <dl className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          [t("referrals"), String(stats.points)],
          [t("pending"), String(stats.pending)],
          [t("review"), String(stats.underReview)],
          [t("rank"), rank ? `#${rank}` : t("rankNone")],
        ].map(([label, value]) => (
          <div key={label} className="panel p-6">
            <dt className="text-xs uppercase tracking-[0.16em] text-smoke">{label}</dt>
            <dd className="mt-3 text-5xl font-semibold tracking-tight tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <section className="panel mt-4 p-6 sm:p-8" aria-labelledby="progress-title">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="progress-title" className="text-xs uppercase tracking-[0.16em] text-smoke">{t("next")}</h2>
          <p className="text-sm text-white">
            {next ? t("nextText", { remaining: next.threshold - stats.points, name: next.name }) : t("allDone")}
          </p>
        </div>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-graphite" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label={t("progress")}>
          <div className="h-full rounded-full bg-gradient-to-r from-cyan to-violet transition-[width] duration-700" style={{ width: `${progress}%` }} />
        </div>
      </section>

      <section className="mt-16 grid gap-10 lg:grid-cols-[0.8fr_1.2fr]">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">{t("linkTitle")}</h2>
          <p className="mt-3 max-w-sm text-ash">{t("linkText")}</p>
        </div>
        <InsiderShare
          link={referralUrl(sub.referralCode)} urls={urls}
          labels={{ copy: t("copy"), copied: t("copied"), share: t("share"), text: t("shareText"), subject: t("shareSubject") }}
        />
      </section>

      {rewards.length > 0 && (
        <section className="mt-20">
          <h2 className="text-3xl font-semibold tracking-tight">{t("rewards")}</h2>
          <ul className="mt-8 grid gap-4 md:grid-cols-3">
            {rewards.map((reward) => {
              const reached = stats.points >= reward.threshold;
              return (
                <li key={reward.id} className={`panel p-6 ${reached ? "border-cyan/60" : ""}`}>
                  <p className="font-mono text-xs uppercase tracking-[0.18em] text-smoke">{reward.threshold} · {reached ? <span className="text-cyan">{t("reached")}</span> : t("referrals")}</p>
                  <h3 className="mt-4 text-2xl font-semibold tracking-tight">{reward.name}</h3>
                  {pickText(reward.description, locale) && <p className="mt-2 text-sm leading-relaxed text-ash">{pickText(reward.description, locale)}</p>}
                </li>
              );
            })}
          </ul>
          <p className="mt-5 text-xs text-smoke">{t("rewardsNote")}</p>
        </section>
      )}

      {top.length > 0 && (
        <section className="mt-20 max-w-xl">
          <h2 className="text-3xl font-semibold tracking-tight">{t("leaderboard")}</h2>
          <ol className="mt-6 border-t border-line">
            {top.map((row) => (
              <li key={row.rank} className="flex items-center justify-between border-b border-line py-3.5 font-mono text-sm">
                <span><span className="mr-4 text-smoke">{String(row.rank).padStart(2, "0")}</span>{row.label}</span>
                <span className="tabular-nums text-cyan">{row.points}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="mt-20 border-t border-line pt-10">
        <h2 className="text-xl font-semibold tracking-tight">{t("data")}</h2>
        <p className="mb-6 mt-2 text-sm text-ash">{t("dataText")}</p>
        <InsiderData
          token={cleanToken} subscribed={sub.status === "CONFIRMED"}
          labels={{
            export: t("export"), unsubscribe: t("unsubscribe"), unsubscribed: t("unsubscribed"), delete: t("delete"), deleteConfirm: t("deleteConfirm"),
            deleteYes: t("deleteYes"), deleteNo: t("deleteNo"), deletedTitle: t("deletedTitle"), deletedText: t("deletedText"), error: e("generic"),
          }}
        />
      </section>
    </div>
  );
}
