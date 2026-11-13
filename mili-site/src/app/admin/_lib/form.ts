import { locales, type Locale } from "@/lib/i18n/config";

/** Helpers to read admin forms. Everything is trimmed; empty strings become null where it matters. */
export const str = (fd: FormData, key: string): string => {
  const v = fd.get(key);
  return typeof v === "string" ? v.trim() : "";
};
export const optional = (fd: FormData, key: string): string | null => str(fd, key) || null;
export const bool = (fd: FormData, key: string): boolean => fd.get(key) === "on" || fd.get(key) === "true";
export const int = (fd: FormData, key: string, fallback = 0): number => {
  const n = Number.parseInt(str(fd, key), 10);
  return Number.isFinite(n) ? n : fallback;
};
export const optionalInt = (fd: FormData, key: string): number | null => {
  const raw = str(fd, key);
  if (!raw) return null;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : null;
};

/** `<input type="datetime-local">` values are entered and stored as UTC. */
export const utcDate = (fd: FormData, key: string): Date | null => {
  const raw = str(fd, key);
  if (!raw) return null;
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}${raw.length === 10 ? "T00:00" : ""}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
};
export const toInputDateTime = (date: Date | null | undefined): string => (date ? date.toISOString().slice(0, 16) : "");
export const toInputDate = (date: Date | null | undefined): string => (date ? date.toISOString().slice(0, 10) : "");

/** Reads `name.en`, `name.fr`, … into a `{ en, fr, … }` map, dropping empty languages. */
export function localized(fd: FormData, name: string): Partial<Record<Locale, string>> {
  const out: Partial<Record<Locale, string>> = {};
  for (const locale of locales) {
    const value = str(fd, `${name}.${locale}`);
    if (value) out[locale] = value;
  }
  return out;
}

export function httpsUrl(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}
