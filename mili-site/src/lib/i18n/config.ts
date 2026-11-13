export const locales = ["en", "fr", "de", "es", "ja"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

export const localeNames: Record<Locale, string> = {
  en: "English",
  fr: "Français",
  de: "Deutsch",
  es: "Español",
  ja: "日本語",
};

/** BCP 47 tags used for hreflang and Open Graph. */
export const localeTags: Record<Locale, string> = {
  en: "en-US",
  fr: "fr-FR",
  de: "de-DE",
  es: "es-ES",
  ja: "ja-JP",
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (locales as readonly string[]).includes(value);
}

export type LocalizedText = Partial<Record<Locale, string>>;

/** Reads a localised JSON column, falling back to English, then to any value. */
export function pickText(value: unknown, locale: string): string {
  if (!value || typeof value !== "object") return typeof value === "string" ? value : "";
  const map = value as Record<string, unknown>;
  const candidate = map[locale] ?? map[defaultLocale] ?? Object.values(map).find((v) => typeof v === "string" && v);
  return typeof candidate === "string" ? candidate : "";
}

/** Path for a locale under the "as-needed" prefix strategy (English has no prefix). */
export function localePath(locale: string, path = "/"): string {
  const clean = path === "/" ? "" : path.startsWith("/") ? path : `/${path}`;
  return locale === defaultLocale ? clean || "/" : `/${locale}${clean}`;
}
