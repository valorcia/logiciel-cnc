"use server";

import { db } from "@/lib/db";
import { processDueEmails } from "@/lib/email/sequences";
import { sendTestEmail } from "@/lib/email/send";
import { isLocale } from "@/lib/i18n/config";
import { adminAction, FormError } from "../_lib/guard";
import { bool, int, str } from "../_lib/form";

/** Variables a template may use. Anything else would be printed as-is in the e-mail. */
const VARIABLES = ["firstName", "greeting", "referralLink", "insiderLink", "launchDate", "kickstarterUrl", "siteUrl", "unsubscribeUrl", "confirmUrl"];

export async function saveTemplateAction(fd: FormData) {
  const key = str(fd, "key");
  const locale = str(fd, "locale");
  await adminAction("emails.edit", `/admin/emails/${key}?locale=${locale}`, async ({ log }) => {
    if (!isLocale(locale)) throw new FormError("Langue inconnue.");
    const subject = str(fd, "subject");
    const body = str(fd, "body");
    if (!subject || !body) throw new FormError("Objet et contenu requis.");
    const unknown = [...`${subject} ${body}`.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).filter((name) => !VARIABLES.includes(name));
    if (unknown.length) throw new FormError(`Variable inconnue : {{${unknown[0]}}}. Variables disponibles : ${VARIABLES.map((v) => `{{${v}}}`).join(", ")}.`);
    const reference = await db.emailTemplate.findFirst({ where: { key }, orderBy: { locale: "asc" } });
    if (!reference) throw new FormError("Modèle inconnu.");
    if (key === "confirm" && !body.includes("{{confirmUrl}}")) throw new FormError("L'e-mail de confirmation doit contenir {{confirmUrl}}, sinon personne ne peut confirmer son inscription.");
    await db.emailTemplate.upsert({
      where: { key_locale: { key, locale } },
      create: { key, locale, series: reference.series, name: reference.name, subject, preheader: str(fd, "preheader"), body },
      update: { subject, preheader: str(fd, "preheader"), body },
    });
    await log("email.template_saved", "EmailTemplate", key, { locale });
  });
}

export async function deleteTemplateTranslationAction(fd: FormData) {
  const key = str(fd, "key");
  const locale = str(fd, "locale");
  await adminAction("emails.edit", `/admin/emails/${key}`, async ({ log }) => {
    if (locale === "en") throw new FormError("La version anglaise sert de référence et ne peut pas être supprimée.");
    await db.emailTemplate.deleteMany({ where: { key, locale } });
    await log("email.template_translation_deleted", "EmailTemplate", key, { locale });
  }, "deleted");
}

export async function sendTestAction(fd: FormData) {
  const key = str(fd, "key");
  const locale = str(fd, "locale");
  await adminAction("emails.send", `/admin/emails/${key}?locale=${locale}`, async ({ admin, log }) => {
    const to = str(fd, "to") || admin.email;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)) throw new FormError("Adresse de test invalide.");
    const template = await db.emailTemplate.findUnique({ where: { key_locale: { key, locale } } });
    if (!template) throw new FormError("Enregistrez d'abord ce modèle dans cette langue.");
    const result = await sendTestEmail(template, to);
    if (result.status === "NOT_SENT_NO_PROVIDER") throw new FormError("Non envoyé : aucun fournisseur d'e-mail n'est configuré (RESEND_API_KEY).");
    if (result.status === "FAILED") throw new FormError(`Le fournisseur a refusé l'envoi : ${result.error}`);
    await log("email.test_sent", "EmailTemplate", key, { locale });
  }, "sent");
}

export async function saveStepAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("emails.edit", "/admin/emails", async ({ log }) => {
    const unit = str(fd, "unit") === "hours" ? 60 : 1440;
    const sign = str(fd, "direction") === "before" ? -1 : 1;
    const amount = Math.abs(int(fd, "amount"));
    const offsetMinutes = sign * amount * unit;
    await db.emailStep.update({ where: { id }, data: { offsetMinutes, active: bool(fd, "active") } });
    await log("email.step_saved", "EmailStep", id, { offsetMinutes, active: bool(fd, "active") });
  });
}

export async function runAutomationAction() {
  await adminAction("emails.send", "/admin/emails", async ({ log }) => {
    const reports = await processDueEmails();
    const sent = reports.reduce((n, r) => n + r.sent, 0);
    const failed = reports.reduce((n, r) => n + r.failed, 0);
    await log("email.automation_run", "EmailStep", null, { sent, failed });
    const blocked = reports.find((r) => r.skippedReason === "No e-mail provider configured");
    if (blocked) throw new FormError("Rien n'a été envoyé : aucun fournisseur d'e-mail n'est configuré.");
    return `/admin/emails?ran=${sent}&failed=${failed}`;
  });
}
