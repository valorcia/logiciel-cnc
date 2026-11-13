import "server-only";
import { db } from "./db";
import type { SiteSettings } from "@/generated/prisma/client";

export type SocialLinks = Partial<Record<"x" | "youtube" | "instagram" | "facebook" | "reddit" | "tiktok" | "discord", string>>;

/** The singleton settings row, created on first read. */
export async function getSettings(): Promise<SiteSettings> {
  const existing = await db.siteSettings.findUnique({ where: { id: 1 } });
  if (existing) return existing;
  return db.siteSettings.upsert({ where: { id: 1 }, update: {}, create: { id: 1 } });
}

/**
 * The only gate for confidential content. Every loader that returns reveal-only
 * data must call this on the server; hiding things in the UI is not a gate.
 */
export async function isRevealed(): Promise<boolean> {
  const settings = await getSettings();
  return settings.mode === "REVEAL";
}

export function socialLinks(settings: SiteSettings): SocialLinks {
  const raw = settings.socialLinks;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: SocialLinks = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === "string" && /^https:\/\//.test(value)) out[key as keyof SocialLinks] = value;
  }
  return out;
}

export function formatUsd(cents: number, locale = "en-US"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(cents / 100);
}
