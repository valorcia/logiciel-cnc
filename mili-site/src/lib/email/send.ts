import "server-only";
import { db } from "../db";
import { siteUrl } from "../env";
import { isLocale, localeTags, type Locale } from "../i18n/config";
import { insiderUrl, oneClickUnsubscribeUrl, referralUrl, unsubscribeUrl } from "../links";
import { getSettings } from "../settings";
import { sendEmail, type OutgoingEmail, type SendResult } from "./provider";
import { interpolate, layout, renderMarkdown, renderText, type EmailVars } from "./render";
import { emailStrings } from "./strings";
import type { EmailTemplate, SiteSettings, Subscriber } from "@/generated/prisma/client";

/** Templates of these series are commercial communication and need confirmed consent. */
const MARKETING_SERIES = new Set(["WELCOME", "PRELAUNCH", "LAUNCH"]);

export async function findTemplate(key: string, locale: string): Promise<EmailTemplate | null> {
  const rows = await db.emailTemplate.findMany({ where: { key, locale: { in: [locale, "en"] } } });
  return rows.find((r) => r.locale === locale) ?? rows.find((r) => r.locale === "en") ?? null;
}

export function subscriberVars(sub: Subscriber, settings: SiteSettings, extra: EmailVars = {}): EmailVars {
  const locale: Locale = isLocale(sub.locale) ? sub.locale : "en";
  const strings = emailStrings[locale];
  const launchDate = settings.launchAt
    ? new Intl.DateTimeFormat(localeTags[locale], { dateStyle: "long", timeZone: "UTC" }).format(settings.launchAt)
    : strings.soon;
  return {
    firstName: sub.firstName ?? "",
    greeting: strings.greeting(sub.firstName),
    referralLink: referralUrl(sub.referralCode),
    insiderLink: insiderUrl(sub, locale),
    launchDate,
    // The Kickstarter link only exists for recipients once the reveal has been approved.
    kickstarterUrl: settings.mode === "REVEAL" ? (settings.kickstarterUrl ?? "") : "",
    siteUrl: siteUrl(),
    unsubscribeUrl: unsubscribeUrl(sub, locale),
    ...extra,
  };
}

export type BuiltEmail = { message: Omit<OutgoingEmail, "to">; subject: string; locale: string };

/** Renders a stored template into a ready-to-send message. */
export function buildEmail(
  template: EmailTemplate,
  vars: EmailVars,
  settings: SiteSettings,
  unsubscribe?: { url: string; oneClickUrl: string },
): BuiltEmail {
  const locale: Locale = isLocale(template.locale) ? template.locale : "en";
  const strings = emailStrings[locale];
  const marketing = MARKETING_SERIES.has(template.series);
  const subject = interpolate(template.subject, vars).trim();
  const source = interpolate(template.body, vars, { markdownSafe: true });
  const html = layout({
    locale,
    subject,
    preheader: interpolate(template.preheader, vars),
    bodyHtml: renderMarkdown(source),
    reason: marketing ? strings.reasonMarketing : strings.reasonTransactional,
    unsubscribeLabel: marketing && unsubscribe ? strings.unsubscribe : undefined,
    unsubscribeUrl: marketing && unsubscribe ? unsubscribe.url : undefined,
    legalName: settings.legalName,
    postalAddress: settings.postalAddress,
  });
  const headers: Record<string, string> = {};
  if (marketing && unsubscribe) {
    headers["List-Unsubscribe"] = `<${unsubscribe.oneClickUrl}>`;
    headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click";
  }
  const text = `${renderText(source)}\n\n—\n${marketing ? strings.reasonMarketing : strings.reasonTransactional}${
    marketing && unsubscribe ? `\n${strings.unsubscribe}: ${unsubscribe.url}` : ""
  }`;
  return { message: { subject, html, text, headers }, subject, locale };
}

export function mayReceiveMarketing(sub: Pick<Subscriber, "status" | "marketingConsent">): boolean {
  return sub.status === "CONFIRMED" && sub.marketingConsent;
}

export type DeliveryOutcome = SendResult | { status: "SKIPPED"; reason: string };

/**
 * Sends one template to one subscriber and records the attempt.
 * Marketing templates are refused unless the address is confirmed and consent is current.
 */
export async function sendToSubscriber(
  sub: Subscriber,
  templateKey: string,
  opts: { stepId?: string; kind?: "AUTOMATION" | "TRANSACTIONAL"; extraVars?: EmailVars } = {},
): Promise<DeliveryOutcome> {
  const template = await findTemplate(templateKey, sub.locale);
  if (!template) return { status: "SKIPPED", reason: `Unknown template "${templateKey}"` };
  if (MARKETING_SERIES.has(template.series) && !mayReceiveMarketing(sub)) {
    return { status: "SKIPPED", reason: "No confirmed marketing consent" };
  }
  const settings = await getSettings();
  const built = buildEmail(template, subscriberVars(sub, settings, opts.extraVars), settings, {
    url: unsubscribeUrl(sub, sub.locale),
    oneClickUrl: oneClickUnsubscribeUrl(sub),
  });

  let sendId: string;
  try {
    const row = await db.emailSend.create({
      data: {
        subscriberId: sub.id,
        stepId: opts.stepId,
        templateKey,
        locale: built.locale,
        subject: built.subject,
        kind: opts.kind ?? (opts.stepId ? "AUTOMATION" : "TRANSACTIONAL"),
        status: "QUEUED",
      },
    });
    sendId = row.id;
  } catch {
    // Unique (subscriberId, stepId): another worker already took this delivery.
    return { status: "SKIPPED", reason: "Already sent" };
  }

  const result = await sendEmail({ to: sub.email, ...built.message });
  await db.emailSend.update({
    where: { id: sendId },
    data:
      result.status === "SENT"
        ? { status: "SENT", providerId: result.providerId }
        : result.status === "FAILED"
          ? { status: "FAILED", error: result.error.slice(0, 500) }
          : { status: "NOT_SENT_NO_PROVIDER" },
  });
  return result;
}

/** Admin test send: rendered with sample data, delivered to the administrator only. */
export async function sendTestEmail(template: EmailTemplate, to: string): Promise<SendResult> {
  const settings = await getSettings();
  const locale: Locale = isLocale(template.locale) ? template.locale : "en";
  const built = buildEmail(template, sampleVars(locale, settings), settings, {
    url: `${siteUrl()}/unsubscribe?t=TEST`,
    oneClickUrl: `${siteUrl()}/api/unsubscribe?t=TEST`,
  });
  const result = await sendEmail({ to, ...built.message, subject: `[TEST] ${built.subject}` });
  await db.emailSend.create({
    data: {
      templateKey: template.key,
      locale: built.locale,
      subject: built.subject,
      kind: "TEST",
      status: result.status,
      providerId: result.status === "SENT" ? result.providerId : null,
      error: result.status === "FAILED" ? result.error.slice(0, 500) : null,
    },
  });
  return result;
}

export function sampleVars(locale: Locale, settings: SiteSettings): EmailVars {
  const strings = emailStrings[locale];
  return {
    firstName: "Alex",
    greeting: strings.greeting("Alex"),
    referralLink: `${siteUrl()}/invite/SAMPLE7`,
    insiderLink: `${siteUrl()}/insider/SAMPLE`,
    confirmUrl: `${siteUrl()}/confirm?token=SAMPLE`,
    launchDate: settings.launchAt
      ? new Intl.DateTimeFormat(localeTags[locale], { dateStyle: "long", timeZone: "UTC" }).format(settings.launchAt)
      : strings.soon,
    kickstarterUrl: settings.kickstarterUrl ?? "https://www.kickstarter.com/",
    siteUrl: siteUrl(),
    unsubscribeUrl: `${siteUrl()}/unsubscribe?t=SAMPLE`,
  };
}
