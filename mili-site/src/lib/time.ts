/** Current time for server-rendered pages (kept out of component bodies, which must stay pure). */
export const nowMs = (): number => Date.now();
