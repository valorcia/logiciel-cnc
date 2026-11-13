import "server-only";
import { db } from "../db";
import type { Locale } from "./config";

type Messages = { [key: string]: string | Messages };

async function baseMessages(locale: Locale): Promise<Messages> {
  return (await import(`../../../messages/${locale}.json`)).default as Messages;
}

function setPath(target: Messages, path: string, value: string): void {
  const parts = path.split(".");
  let node = target;
  for (let i = 0; i < parts.length - 1; i++) {
    const next = node[parts[i]];
    if (typeof next !== "object" || next === null) return; // overrides only replace existing keys
    node = next;
  }
  const leaf = parts[parts.length - 1];
  if (typeof node[leaf] === "string") node[leaf] = value;
}

function fillMissing(target: Messages, fallback: Messages): void {
  for (const [key, value] of Object.entries(fallback)) {
    if (typeof value === "object") {
      if (typeof target[key] !== "object" || target[key] === null) target[key] = {};
      fillMissing(target[key] as Messages, value);
    } else if (typeof target[key] !== "string") {
      target[key] = value;
    }
  }
}

/**
 * Messages for a locale: the JSON file, completed with English for any missing
 * key, then the overrides saved by administrators in /admin/content.
 */
export async function loadMessages(locale: Locale): Promise<Messages> {
  const messages = structuredClone(await baseMessages(locale));
  if (locale !== "en") fillMissing(messages, await baseMessages("en"));
  try {
    const overrides = await db.contentOverride.findMany({ where: { locale } });
    for (const o of overrides) setPath(messages, o.key, o.value);
  } catch (err) {
    // The public site must keep rendering its default copy if the database is briefly unreachable.
    console.error("[i18n] could not load content overrides", err);
  }
  return messages;
}

/** Flat list of every translatable key with its default English value (for the content editor). */
export async function flatMessages(locale: Locale): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  const walk = (node: Messages, prefix: string) => {
    for (const [key, value] of Object.entries(node)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (typeof value === "string") out[path] = value;
      else walk(value, path);
    }
  };
  walk(await baseMessages(locale), "");
  return out;
}
