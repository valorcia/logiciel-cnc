/**
 * File-type detection by content, not by the name the browser sent.
 * Pure functions, unit-tested with real file headers.
 */

export type DetectedFile = { ext: string; mime: string };

const startsWith = (buf: Uint8Array, bytes: number[], offset = 0) => bytes.every((b, i) => buf[offset + i] === b);
const ascii = (buf: Uint8Array, start: number, end: number) => Buffer.from(buf.subarray(start, end)).toString("latin1");

function looksLikeText(buf: Uint8Array): boolean {
  const sample = buf.subarray(0, Math.min(buf.length, 4096));
  for (const byte of sample) {
    if (byte === 0) return false;
    if (byte < 9 || (byte > 13 && byte < 32)) return false;
  }
  return sample.length > 0;
}

function isBinaryStl(buf: Uint8Array): boolean {
  if (buf.length < 84) return false;
  const triangles = new DataView(buf.buffer, buf.byteOffset, buf.byteLength).getUint32(80, true);
  return triangles > 0 && buf.length === 84 + triangles * 50;
}

function isObj(buf: Uint8Array): boolean {
  if (!looksLikeText(buf)) return false;
  const lines = ascii(buf, 0, Math.min(buf.length, 16384)).split(/\r?\n/).slice(0, 400);
  const known = /^(v|vt|vn|vp|f|l|o|g|s|mtllib|usemtl)\s/;
  let vertices = 0;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    if (!known.test(line)) return false;
    if (/^v\s+-?[\d.]/.test(line)) vertices++;
  }
  return vertices >= 3;
}

/** Returns the real type of a buffer among the formats MILLI accepts, or null. */
export function detectFile(buf: Uint8Array): DetectedFile | null {
  if (startsWith(buf, [0x25, 0x50, 0x44, 0x46, 0x2d])) return { ext: "pdf", mime: "application/pdf" };
  if (startsWith(buf, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return { ext: "png", mime: "image/png" };
  if (startsWith(buf, [0xff, 0xd8, 0xff])) return { ext: "jpg", mime: "image/jpeg" };
  if (startsWith(buf, [0x52, 0x49, 0x46, 0x46]) && ascii(buf, 8, 12) === "WEBP") return { ext: "webp", mime: "image/webp" };
  const head = ascii(buf, 0, Math.min(buf.length, 512));
  if (/^\s*ISO-10303-21;/.test(head) && looksLikeText(buf)) return { ext: "step", mime: "model/step" };
  if (/^\s*solid\b/.test(head) && looksLikeText(buf) && /facet\s+normal/.test(ascii(buf, 0, Math.min(buf.length, 4096)))) {
    return { ext: "stl", mime: "model/stl" };
  }
  if (isBinaryStl(buf)) return { ext: "stl", mime: "model/stl" };
  if (isObj(buf)) return { ext: "obj", mime: "model/obj" };
  return null;
}

const EXTENSION_ALIASES: Record<string, string> = { jpeg: "jpg", stp: "step" };

export function extensionOf(fileName: string): string {
  const ext = fileName.toLowerCase().match(/\.([a-z0-9]{1,8})$/)?.[1] ?? "";
  return EXTENSION_ALIASES[ext] ?? ext;
}

export type FileCheck =
  | { ok: true; file: DetectedFile; safeName: string }
  | { ok: false; error: "too_large" | "empty" | "type_not_allowed" | "extension_mismatch" };

/**
 * Validates an upload: size, declared extension in the allow-list, real content
 * of an allowed type, and the two agreeing with each other.
 */
export function checkUpload(buf: Uint8Array, fileName: string, allowed: readonly string[], maxBytes: number): FileCheck {
  if (buf.length === 0) return { ok: false, error: "empty" };
  if (buf.length > maxBytes) return { ok: false, error: "too_large" };
  const declared = extensionOf(fileName);
  if (!allowed.includes(declared)) return { ok: false, error: "type_not_allowed" };
  const detected = detectFile(buf);
  if (!detected || !allowed.includes(detected.ext)) return { ok: false, error: "type_not_allowed" };
  if (detected.ext !== declared) return { ok: false, error: "extension_mismatch" };
  const safeName = fileName.replace(/[^\w.\- ]+/g, "_").slice(-120);
  return { ok: true, file: detected, safeName };
}

export const CHALLENGE_FILE_TYPES = ["step", "stl", "obj", "pdf", "jpg", "png"] as const;
export const IMAGE_FILE_TYPES = ["jpg", "png", "webp"] as const;
