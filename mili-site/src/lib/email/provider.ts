import "server-only";
import { Resend } from "resend";
import { env } from "../env";

export type OutgoingEmail = {
  to: string;
  subject: string;
  html: string;
  text: string;
  headers?: Record<string, string>;
};

export type SendResult =
  | { status: "SENT"; providerId: string }
  | { status: "FAILED"; error: string }
  /** No RESEND_API_KEY configured: nothing left this server. Recorded as such, never as sent. */
  | { status: "NOT_SENT_NO_PROVIDER" };

let client: Resend | null | undefined;

function resend(): Resend | null {
  if (client !== undefined) return client;
  const key = env().RESEND_API_KEY;
  client = key ? new Resend(key) : null;
  return client;
}

export function emailProviderConfigured(): boolean {
  return Boolean(env().RESEND_API_KEY);
}

export async function sendEmail(message: OutgoingEmail): Promise<SendResult> {
  const api = resend();
  if (!api) {
    if (env().NODE_ENV !== "test") {
      console.info(`[email] no provider configured — not sent: "${message.subject}" → ${message.to.replace(/^(.).*@/, "$1***@")}`);
    }
    if (env().NODE_ENV === "development") await writeDevOutbox(message);
    return { status: "NOT_SENT_NO_PROVIDER" };
  }
  try {
    const { data, error } = await api.emails.send({
      from: env().EMAIL_FROM,
      to: message.to,
      subject: message.subject,
      html: message.html,
      text: message.text,
      headers: message.headers,
      replyTo: env().EMAIL_REPLY_TO,
    });
    if (error || !data) return { status: "FAILED", error: error?.message ?? "Unknown provider error" };
    return { status: "SENT", providerId: data.id };
  } catch (err) {
    return { status: "FAILED", error: err instanceof Error ? err.message : String(err) };
  }
}

/** Sends up to 100 messages in one API call. Results are returned in input order. */
export async function sendEmailBatch(messages: OutgoingEmail[]): Promise<SendResult[]> {
  const api = resend();
  if (!api) return messages.map(() => ({ status: "NOT_SENT_NO_PROVIDER" as const }));
  if (messages.length === 0) return [];
  try {
    const { data, error } = await api.batch.send(
      messages.map((m) => ({
        from: env().EMAIL_FROM,
        to: m.to,
        subject: m.subject,
        html: m.html,
        text: m.text,
        headers: m.headers,
        replyTo: env().EMAIL_REPLY_TO,
      })),
    );
    if (error || !data) {
      const reason = error?.message ?? "Unknown provider error";
      return messages.map(() => ({ status: "FAILED" as const, error: reason }));
    }
    return messages.map((_, i) => {
      const id = data.data[i]?.id;
      return id ? { status: "SENT" as const, providerId: id } : { status: "FAILED" as const, error: "No id returned" };
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    return messages.map(() => ({ status: "FAILED" as const, error: reason }));
  }
}

/**
 * Development only: with no provider configured, the message is written to
 * .storage/outbox/ so the confirmation link can be opened locally. Never runs
 * in production, where an unsent e-mail stays unsent and is recorded as such.
 */
async function writeDevOutbox(message: OutgoingEmail): Promise<void> {
  try {
    const { mkdir, writeFile } = await import("node:fs/promises");
    const path = await import("node:path");
    const dir = path.join(process.cwd(), ".storage", "outbox");
    await mkdir(dir, { recursive: true });
    const name = `${Date.now()}-${message.to.replace(/[^a-z0-9@.-]/gi, "_")}`;
    await writeFile(path.join(dir, `${name}.html`), message.html);
    await writeFile(path.join(dir, `${name}.txt`), `To: ${message.to}\nSubject: ${message.subject}\n\n${message.text}`);
  } catch {}
}
