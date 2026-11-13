import type { Metadata } from "next";
import { getFormatter, getTranslations, setRequestLocale } from "next-intl/server";
import { PageHeader } from "@/components/site/page-shell";
import { Link } from "@/i18n/navigation";
import { publishedArticles } from "@/lib/content";
import type { Locale } from "@/lib/i18n/config";
import { pageMetadata } from "@/lib/seo";

export const revalidate = 60;
const CATEGORIES = ["CNC_TECHNOLOGY", "FIVE_AXIS_MACHINING", "MAKER_PROJECTS", "ENGINEERING", "MILLI_NEWS"] as const;
type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ category?: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "journal" });
  return pageMetadata({ locale: locale as Locale, path: "/journal", title: t("title"), description: t("subtitle") });
}

export default async function JournalPage({ params, searchParams }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const { category } = await searchParams;
  const active = CATEGORIES.find((c) => c === category);
  const t = await getTranslations({ locale, namespace: "journal" });
  const format = await getFormatter({ locale });
  const articles = await publishedArticles(locale, active);
  const chip = (on: boolean) => `rounded-full border px-4 py-2 text-xs font-medium uppercase tracking-[0.14em] transition ${on ? "border-white bg-white text-void" : "border-line text-ash hover:border-white hover:text-white"}`;

  return (
    <>
      <PageHeader title={t("title")} text={t("subtitle")} />
      <div className="shell pb-28">
        <nav aria-label={t("title")} className="mb-12 flex flex-wrap gap-2">
          <Link href="/journal" className={chip(!active)}>{t("all")}</Link>
          {CATEGORIES.map((c) => (
            <Link key={c} href={{ pathname: "/journal", query: { category: c } }} className={chip(active === c)}>{t(`categories.${c}`)}</Link>
          ))}
        </nav>
        {articles.length === 0 ? (
          <p className="panel px-6 py-16 text-center text-ash">{t("empty")}</p>
        ) : (
          <ul className="grid gap-x-6 gap-y-12 md:grid-cols-2 xl:grid-cols-3">
            {articles.map((a) => (
              <li key={a.id}>
                <Link href={`/journal/${a.slug}`} className="group block">
                  {a.coverId ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={`/media/${a.coverId}`} alt="" loading="lazy" decoding="async" className="aspect-[16/10] w-full rounded-xl border border-line object-cover transition duration-500 group-hover:opacity-85" />
                  ) : (
                    <div aria-hidden className="panel glow-cyan aspect-[16/10] w-full" />
                  )}
                  <p className="mt-5 text-[0.6875rem] uppercase tracking-[0.18em] text-smoke">
                    {t(`categories.${a.category}` as "categories.MILLI_NEWS")} · {format.dateTime(a.publishAt ?? a.createdAt, { dateStyle: "medium", timeZone: "UTC" })}
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold leading-snug tracking-tight transition group-hover:text-cyan">{a.title}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-ash">{a.excerpt}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
