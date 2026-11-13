import { randomBytes } from "node:crypto";

/** Random lower-case identifier for storage keys (not derived from user input). */
export function createId(bytes = 12): string {
  return randomBytes(bytes).toString("hex");
}
