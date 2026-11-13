import "server-only";
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { env } from "./env";

/** URL-safe random token. 32 bytes = 256 bits of entropy. */
export function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

/** Tokens are stored hashed: a database leak must not yield usable links. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function hmac(purpose: string, value: string): string {
  return createHmac("sha256", env().APP_SECRET).update(`${purpose}:${value}`).digest("base64url");
}

/** Pseudonymous, stable identifier for an IP address. The raw IP is never stored. */
export function ipHash(ip: string): string {
  return hmac("ip", ip).slice(0, 32);
}

/** Daily-rotating visitor hash for cookieless analytics (cannot be linked across days). */
export function visitorHash(ip: string, userAgent: string, day: string): string {
  return hmac(`visit:${day}`, `${ip}|${userAgent}`).slice(0, 32);
}

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

/** Compact signed payload: base64url(json).signature — used for form timing and vote identities. */
export function sign(purpose: string, payload: Record<string, unknown>): string {
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${body}.${hmac(purpose, body)}`;
}

export function verify<T extends Record<string, unknown>>(purpose: string, token: string | undefined | null): T | null {
  if (!token) return null;
  const [body, signature] = token.split(".");
  if (!body || !signature || !safeEqual(signature, hmac(purpose, body))) return null;
  try {
    return JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as T;
  } catch {
    return null;
  }
}

const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I

export function randomCode(length: number): string {
  const bytes = randomBytes(length);
  let out = "";
  for (let i = 0; i < length; i++) out += CODE_ALPHABET[bytes[i] % CODE_ALPHABET.length];
  return out;
}
