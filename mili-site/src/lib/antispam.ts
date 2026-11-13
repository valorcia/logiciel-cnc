import "server-only";
import { sign, verify } from "./crypto";

const MIN_AGE_MS = 1500;
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

/** A signed timestamp handed to the browser when a form is displayed. */
export function newFormToken(now = Date.now()): string {
  return sign("form", { t: now });
}

/**
 * A submission is plausible when its token is authentic, the form was open for
 * at least a moment (bots post instantly) and the hidden honeypot is empty.
 */
export function plausibleSubmission(formData: FormData, now = Date.now()): boolean {
  if (String(formData.get("website") ?? "").trim() !== "") return false;
  const payload = verify<{ t: number }>("form", String(formData.get("ft") ?? ""));
  if (!payload || typeof payload.t !== "number") return false;
  const age = now - payload.t;
  return age >= MIN_AGE_MS && age <= MAX_AGE_MS;
}
