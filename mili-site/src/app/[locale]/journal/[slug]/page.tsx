import type { Metadata } from "next";
import { getFormatter, getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { Link } from "@/i18n/navigation";
import { publishedArticle } from "@/lib/content";
import { db } from "@/lib/db";
import { isLocale, type Locale } from "@/lib/i18n/config";
import { renderSiteMarkdown } from "@/lib/markdown";
import { baseUrl, jsonLd, pageMetadata } from "@/lib/seo";

export const revalidate = 60;
type Props = { params: Promise<{ locale: string; slug: string }> };

/** Locales in which an article with this slug is live — drives hreflang. */
async function siblings(slug: string): Promise<Locale[]> {
  const now = new Date();
  const rows = await db.article.findMany({
    where: { slug, OR: [{ status: "PUBLISHED", OR: [{ publishAt: null }, { publishAt: { lte: now } }] }, { status: "SCHEDULED", publishAt: { lte: now } }] },
    select: { locale: true },
  });
  return rows.map((r) => r.locale).filter(isLocale);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  const article = await publishedArticle(locale, slug);
  if (!article) return { robots: { index: false, follow: false } };
  const meta = pageMetadata({
    locale: locale as Locale, path: `/journal/${slug}`, type: "article", available: await siblings(slug),
    title: article.seoTitle || article.title, description: article.seoDescription || article.excerpt,
  });
  if (article.coverId) meta.openGraph = { ...meta.openGraph, images: [`/media/${article.coverId}`] };
  return meta;
}

export default async function ArticlePage({ params }: Props) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const article = await publishedArticle(locale, slug);
  if (!article) notFound();
  const t = await getTranslations({ locale, namespace: "journal" });
  const format = await getFormatter({ locale });
  const date = article.publishAt ?? article.createdAt;
  const schema = {
    "@context": "https://schema.org", "@type": "Article", headline: article.title, description: article.excerpt,
    datePublished: date.toISOString(), dateModified: article.updatedAt.toISOString(), inLanguage: locale,
    author: { "@type": "Organization", name: article.authorName }, publisher: { "@type": "Organization", name: "MILI", url: baseUrl() },
    ...(article.coverId ? { image: `${baseUrl()}/media/${article.coverId}` } : {}),
  };

  return (
    <article className="shell pb-28 pt-[calc(var(--header-h)+4rem)]">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(schema) }} />
      <div className="mx-auto max-w-3xl">
        <Link href="/journal" className="text-sm text-ash underline underline-offset-4 hover:text-white">← {t("back")}</Link>
        <p className="eyebrow mb-5 mt-10">{t(`categories.${article.category}` as "categories.MILI_NEWS")}</p>
        <h1 className="display display-lg">{article.title}</h1>
        <p className="mt-6 text-sm text-smoke">
          {t("by", { author: article.authorName })} · {t("published", { date: format.dateTime(date, { dateStyle: "long", timeZone: "UTC" }) })}
        </p>
        {article.coverId && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`/media/${article.coverId}`} alt="" fetchPriority="high" className="mt-10 aspect-[16/9] w-full rounded-2xl border border-line object-cover" />
        )}
        <div className="prose-mili mt-12" dangerouslySetInnerHTML={{ __html: renderSiteMarkdown(article.body) }} />
        <div className="mt-16 border-t border-line pt-10">
          <Link href="/#join" className="btn btn-primary">MILI Insider List</Link>
        </div>
      </div>
    </article>
  );
}
