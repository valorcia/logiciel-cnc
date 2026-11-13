import "server-only";
import { headers } from "next/headers";
import { ipHash } from "./crypto";

export type RequestMeta = { ip: string; ipHash: string; userAgent: string; country: string | null };

/** Request metadata for abuse prevention. Only the hashed IP is ever persisted. */
export async function requestMeta(): Promise<RequestMeta> {
  const h = await headers();
  const forwarded = h.get("x-forwarded-for")?.split(",")[0]?.trim();
  const ip = forwarded || h.get("x-real-ip") || "0.0.0.0";
  const country = h.get("x-vercel-ip-country") || h.get("cf-ipcountry");
  return {
    ip,
    ipHash: ipHash(ip),
    userAgent: (h.get("user-agent") ?? "").slice(0, 300),
    country: country && /^[A-Z]{2}$/.test(country) ? country : null,
  };
}
