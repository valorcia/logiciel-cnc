import "server-only";
import { hmac, safeEqual } from "./crypto";
import { siteUrl } from "./env";
import { localePath } from "./i18n/config";

type Identity = { id: string; publicId: string; tokenVersion: number };

/** Signature that authorises a subscriber's personal links. Derived, never stored. */
export function manageSignature(sub: { id: string; tokenVersion: number }): string {
  return hmac("manage", `${sub.id}:${sub.tokenVersion}`).slice(0, 32);
}

export function insiderToken(sub: Identity): string {
  return `${sub.publicId}.${manageSignature(sub)}`;
}

export function parseInsiderToken(token: string): { publicId: string; signature: string } | null {
  const match = decodeURIComponent(token).match(/^(MILI-[A-Z0-9]{8})\.([A-Za-z0-9_-]{32})$/);
  return match ? { publicId: match[1], signature: match[2] } : null;
}

export function verifyManageSignature(sub: { id: string; tokenVersion: number }, signature: string): boolean {
  return safeEqual(manageSignature(sub), signature);
}

export function insiderUrl(sub: Identity, locale: string): string {
  return `${siteUrl()}${localePath(locale, `/insider/${insiderToken(sub)}`)}`;
}

export function unsubscribeUrl(sub: Identity, locale: string): string {
  return `${siteUrl()}${localePath(locale, "/unsubscribe")}?t=${encodeURIComponent(insiderToken(sub))}`;
}

/** RFC 8058 one-click endpoint, referenced by the List-Unsubscribe header. */
export function oneClickUnsubscribeUrl(sub: Identity): string {
  return `${siteUrl()}/api/unsubscribe?t=${encodeURIComponent(insiderToken(sub))}`;
}

export function confirmUrl(token: string, locale: string): string {
  return `${siteUrl()}${localePath(locale, "/confirm")}?token=${encodeURIComponent(token)}`;
}

export function referralUrl(code: string): string {
  return `${siteUrl()}/invite/${code}`;
}

export const SHARE_CHANNELS = ["whatsapp", "facebook", "x", "reddit", "email", "copy"] as const;
export type ShareChannel = (typeof SHARE_CHANNELS)[number];

/** Referral link tagged with UTM parameters for the channel it is shared on. */
export function referralShareUrl(code: string, channel: ShareChannel): string {
  const params = new URLSearchParams({ utm_source: channel, utm_medium: "referral", utm_campaign: "insider-invite" });
  return `${referralUrl(code)}?${params.toString()}`;
}
