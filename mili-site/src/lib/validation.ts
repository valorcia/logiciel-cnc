import { z } from "zod";
import { locales } from "./i18n/config";

/** A short list of throwaway-mail domains. Extend it from the admin if abuse appears. */
const DISPOSABLE = new Set([
  "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com",
  "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com", "maildrop.cc", "throwawaymail.com",
]);

export function isDisposableEmail(email: string): boolean {
  return DISPOSABLE.has(email.split("@")[1]?.toLowerCase() ?? "");
}

/**
 * Canonical form used only to detect duplicate sign-ups and self-referrals:
 * lower-case, "+tag" removed, and dots removed for Gmail addresses.
 */
export function normalizeEmail(email: string): string {
  const [rawLocal, rawDomain] = email.trim().toLowerCase().split("@");
  if (!rawLocal || !rawDomain) return email.trim().toLowerCase();
  const domain = rawDomain === "googlemail.com" ? "gmail.com" : rawDomain;
  let local = rawLocal.split("+")[0];
  if (domain === "gmail.com") local = local.replace(/\./g, "");
  return `${local}@${domain}`;
}

const email = z.string().trim().toLowerCase().min(5).max(254).email();
const localeField = z.enum(locales).default("en");

export const subscribeSchema = z.object({
  email,
  firstName: z.string().trim().max(60).optional().transform((v) => v || undefined),
  country: z.string().trim().toUpperCase().regex(/^[A-Z]{2}$/).optional().or(z.literal("").transform(() => undefined)),
  locale: localeField,
  consent: z.literal(true, { message: "consent_required" }),
});

export const challengeCategories = [
  "ART_DESIGN", "ENGINEERING", "ROBOTICS", "AUTOMOTIVE", "AEROSPACE", "JEWELRY", "EDUCATION", "OTHER",
] as const;

export const challengeSchema = z.object({
  name: z.string().trim().min(2).max(80),
  email,
  description: z.string().trim().min(20).max(2000),
  category: z.enum(challengeCategories),
  locale: localeField,
  consent: z.literal(true, { message: "consent_required" }),
});

export const inquiryKinds = [
  "GENERAL", "PRESS", "PARTNERSHIP", "GDPR_ACCESS", "GDPR_DELETION", "GDPR_RECTIFICATION", "GDPR_OBJECTION",
] as const;

export const inquirySchema = z.object({
  kind: z.enum(inquiryKinds),
  name: z.string().trim().max(80).optional().transform((v) => v || undefined),
  email,
  message: z.string().trim().min(10).max(4000),
  locale: localeField,
});

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"] as const;
export type Utm = Partial<Record<"utmSource" | "utmMedium" | "utmCampaign" | "utmTerm" | "utmContent", string>>;

/** Extracts and sanitises UTM parameters from any key/value source. */
export function parseUtm(get: (key: string) => string | null | undefined): Utm {
  const out: Utm = {};
  for (const key of UTM_KEYS) {
    const value = get(key)?.trim().slice(0, 100);
    if (value && /^[\w .~+-]+$/.test(value)) {
      const camel = key.replace(/_(\w)/, (_, c: string) => c.toUpperCase()) as keyof Utm;
      out[camel] = value;
    }
  }
  return out;
}
