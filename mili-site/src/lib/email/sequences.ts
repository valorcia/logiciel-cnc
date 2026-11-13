import "server-only";
import { db } from "../db";
import { oneClickUnsubscribeUrl, unsubscribeUrl } from "../links";
import { getSettings } from "../settings";
import { sendEmailBatch } from "./provider";
import { buildEmail, findTemplate, sendToSubscriber, subscriberVars } from "./send";
import type { EmailStep, Subscriber } from "@/generated/prisma/client";

const MINUTE = 60_000;
/** A step that became due longer ago than this is considered missed and is not sent late. */
const WELCOME_GRACE_MIN = 72 * 60;
const LAUNCH_GRACE_MIN = 36 * 60;

export type SequenceReport = {
  step: string;
  due: number;
  sent: number;
  failed: number;
  notSent: number;
  skippedReason?: string;
};

/** The welcome e-mail (WELCOME step at offset 0) is sent right at confirmation, not by the cron. */
export async function sendImmediateWelcome(sub: Subscriber): Promise<void> {
  const step = await db.emailStep.findFirst({
    where: { series: "WELCOME", offsetMinutes: 0, active: true },
    orderBy: { sortOrder: "asc" },
  });
  if (step) await sendToSubscriber(sub, step.templateKey, { stepId: step.id });
}

async function dueSubscribers(step: EmailStep, now: Date, launchAt: Date | null, take: number): Promise<Subscriber[]> {
  const base = { status: "CONFIRMED" as const, marketingConsent: true, emailSends: { none: { stepId: step.id } } };
  if (step.series === "WELCOME") {
    const latest = new Date(now.getTime() - step.offsetMinutes * MINUTE);
    const earliest = new Date(latest.getTime() - WELCOME_GRACE_MIN * MINUTE);
    return db.subscriber.findMany({
      where: { ...base, confirmedAt: { lte: latest, gte: earliest } },
      orderBy: { confirmedAt: "asc" },
      take,
    });
  }
  if (!launchAt) return [];
  const dueAt = launchAt.getTime() + step.offsetMinutes * MINUTE;
  if (now.getTime() < dueAt || now.getTime() - dueAt > LAUNCH_GRACE_MIN * MINUTE) return [];
  return db.subscriber.findMany({ where: { ...base, confirmedAt: { lte: new Date(dueAt) } }, orderBy: { id: "asc" }, take });
}

/**
 * Sends every automation e-mail that is due. Idempotent: the unique
 * (subscriber, step) constraint guarantees a step is delivered at most once,
 * even if two cron invocations overlap.
 */
export async function processDueEmails(now = new Date(), maxPerStep = 1000): Promise<SequenceReport[]> {
  const settings = await getSettings();
  const steps = await db.emailStep.findMany({
    where: { active: true, series: { in: ["WELCOME", "PRELAUNCH", "LAUNCH"] } },
    orderBy: [{ series: "asc" }, { sortOrder: "asc" }],
  });
  const reports: SequenceReport[] = [];

  for (const step of steps) {
    const report: SequenceReport = { step: `${step.series}:${step.templateKey}`, due: 0, sent: 0, failed: 0, notSent: 0 };
    reports.push(report);

    // Launch e-mails carry the Kickstarter link: they wait for the approved reveal.
    if (step.series === "LAUNCH" && (settings.mode !== "REVEAL" || !settings.kickstarterUrl)) {
      report.skippedReason = "Reveal not approved or Kickstarter URL missing";
      continue;
    }

    const due = await dueSubscribers(step, now, settings.launchAt, maxPerStep);
    report.due = due.length;

    for (let i = 0; i < due.length; i += 100) {
      const chunk = due.slice(i, i + 100);
      const prepared: { sub: Subscriber; subject: string; locale: string; message: ReturnType<typeof buildEmail>["message"] }[] = [];
      for (const sub of chunk) {
        const template = await findTemplate(step.templateKey, sub.locale);
        if (!template) continue;
        const built = buildEmail(template, subscriberVars(sub, settings), settings, {
          url: unsubscribeUrl(sub, sub.locale),
          oneClickUrl: oneClickUnsubscribeUrl(sub),
        });
        prepared.push({ sub, subject: built.subject, locale: built.locale, message: built.message });
      }
      if (prepared.length === 0) {
        report.skippedReason = `Template "${step.templateKey}" not found`;
        break;
      }
      // Claim the deliveries first; rows that already exist belong to another run.
      const claimed = await db.emailSend.createManyAndReturn({
        data: prepared.map((p) => ({
          subscriberId: p.sub.id,
          stepId: step.id,
          templateKey: step.templateKey,
          locale: p.locale,
          subject: p.subject,
          kind: "AUTOMATION",
          status: "QUEUED" as const,
        })),
        skipDuplicates: true,
      });
      const bySubscriber = new Map(claimed.map((row) => [row.subscriberId, row.id]));
      const toSend = prepared.filter((p) => bySubscriber.has(p.sub.id));
      const results = await sendEmailBatch(toSend.map((p) => ({ to: p.sub.email, ...p.message })));
      await Promise.all(
        results.map((result, index) => {
          const id = bySubscriber.get(toSend[index].sub.id)!;
          if (result.status === "SENT") {
            report.sent++;
            return db.emailSend.update({ where: { id }, data: { status: "SENT", providerId: result.providerId } });
          }
          if (result.status === "FAILED") {
            report.failed++;
            return db.emailSend.update({ where: { id }, data: { status: "FAILED", error: result.error.slice(0, 500) } });
          }
          report.notSent++;
          return db.emailSend.update({ where: { id }, data: { status: "NOT_SENT_NO_PROVIDER" } });
        }),
      );
    }
  }
  return reports;
}
