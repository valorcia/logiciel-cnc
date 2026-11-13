import type { Metadata } from "next";
import { defaultLocale, localePath, locales, localeTags, type Locale } from "./i18n/config";

export function baseUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
}

/** hreflang alternates for a path that exists in every locale. */
export function alternates(path: string, locale: Locale, available: readonly Locale[] = locales): Metadata["alternates"] {
  const languages: Record<string, string> = {};
  for (const l of available) languages[localeTags[l]] = `${baseUrl()}${localePath(l, path)}`;
  if (available.includes(defaultLocale)) languages["x-default"] = `${baseUrl()}${localePath(defaultLocale, path)}`;
  return { canonical: `${baseUrl()}${localePath(locale, path)}`, languages };
}

export function pageMetadata(input: {
  locale: Locale;
  path: string;
  title: string;
  description: string;
  available?: readonly Locale[];
  noindex?: boolean;
  type?: "website" | "article";
}): Metadata {
  const url = `${baseUrl()}${localePath(input.locale, input.path)}`;
  return {
    title: input.title,
    description: input.description,
    alternates: alternates(input.path, input.locale, input.available),
    robots: input.noindex ? { index: false, follow: false } : undefined,
    openGraph: {
      type: input.type ?? "website",
      url,
      siteName: "MILLI",
      title: input.title,
      description: input.description,
      locale: localeTags[input.locale].replace("-", "_"),
    },
    twitter: { card: "summary_large_image", title: input.title, description: input.description },
  };
}

/** Serialises JSON-LD safely for inlining in a <script> tag. */
export function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
