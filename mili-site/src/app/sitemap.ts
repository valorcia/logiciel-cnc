import type { MetadataRoute } from "next";
import { db } from "@/lib/db";
import { isLocale, localePath, locales, localeTags } from "@/lib/i18n/config";
import { baseUrl } from "@/lib/seo";
import { getSettings } from "@/lib/settings";

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = baseUrl();
  const settings = await getSettings();
  const now = new Date();
  // The product page only exists — and is only announced — once revealed.
  const paths = ["/", "/challenge", "/journal", "/contact", "/privacy", "/terms", "/cookies", ...(settings.mode === "REVEAL" ? ["/milli"] : [])];

  const entries: MetadataRoute.Sitemap = paths.flatMap((path) =>
    locales.map((locale) => ({
      url: `${base}${localePath(locale, path)}`,
      lastModified: now,
      changeFrequency: path === "/" ? ("daily" as const) : ("weekly" as const),
      priority: path === "/" ? 1 : path === "/milli" ? 0.9 : 0.5,
      alternates: { languages: Object.fromEntries(locales.map((l) => [localeTags[l], `${base}${localePath(l, path)}`])) },
    })),
  );

  const articles = await db.article.findMany({
    where: { OR: [{ status: "PUBLISHED", OR: [{ publishAt: null }, { publishAt: { lte: now } }] }, { status: "SCHEDULED", publishAt: { lte: now } }] },
    select: { locale: true, slug: true, updatedAt: true },
  });
  for (const article of articles) {
    if (!isLocale(article.locale)) continue;
    const same = articles.filter((a) => a.slug === article.slug && isLocale(a.locale));
    entries.push({
      url: `${base}${localePath(article.locale, `/journal/${article.slug}`)}`,
      lastModified: article.updatedAt,
      changeFrequency: "monthly",
      priority: 0.6,
      alternates: { languages: Object.fromEntries(same.map((a) => [localeTags[a.locale as keyof typeof localeTags], `${base}${localePath(a.locale, `/journal/${a.slug}`)}`])) },
    });
  }
  return entries;
}
