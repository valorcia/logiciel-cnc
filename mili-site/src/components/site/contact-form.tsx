"use client";

import { useLocale, useTranslations } from "next-intl";
import { useActionState } from "react";
import { inquiryAction, type FormState } from "@/app/actions/public";
import { FieldError, SpamGuard, SuccessMark } from "./form-bits";

const initial: FormState = { status: "idle" };
const KINDS = ["GENERAL", "PRESS", "PARTNERSHIP", "GDPR_ACCESS", "GDPR_DELETION", "GDPR_RECTIFICATION", "GDPR_OBJECTION"] as const;

export function ContactForm() {
  const t = useTranslations("contact");
  const e = useTranslations("errors");
  const locale = useLocale();
  const [state, action, pending] = useActionState(inquiryAction, initial);

  if (state.status === "success") {
    return (
      <div className="panel flex flex-col items-center px-6 py-12 text-center" role="status" aria-live="polite">
        <SuccessMark />
        <h2 className="mt-6 text-3xl font-semibold tracking-tight">{t("successTitle")}</h2>
        <p className="mt-3 text-ash">{t("successText")}</p>
      </div>
    );
  }
  const fields = state.status === "error" ? (state.fields ?? {}) : {};
  const formError = state.status === "error" && !state.fields ? (e.has(state.code) ? e(state.code) : e("generic")) : null;
  const msg = (name: string) => (fields[name] ? (e.has(fields[name]) ? e(fields[name]) : e("invalid")) : undefined);

  return (
    <form action={action} className="panel relative space-y-5 p-6 sm:p-8" noValidate>
      <SpamGuard />
      <input type="hidden" name="locale" value={locale} />
      <div>
        <label htmlFor="ct-kind" className="field-label">{t("kind")}</label>
        <select id="ct-kind" name="kind" className="field" defaultValue="GENERAL">
          {KINDS.map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}
        </select>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor="ct-name" className="field-label">{t("name")}</label>
          <input id="ct-name" name="name" type="text" autoComplete="name" maxLength={80} className="field" />
        </div>
        <div>
          <label htmlFor="ct-email" className="field-label">{t("email")}</label>
          <input id="ct-email" name="email" type="email" required autoComplete="email" className="field" aria-invalid={fields.email ? true : undefined} aria-describedby={fields.email ? "ct-email-error" : undefined} />
          <FieldError id="ct-email-error" message={msg("email")} />
        </div>
      </div>
      <div>
        <label htmlFor="ct-message" className="field-label">{t("message")}</label>
        <textarea id="ct-message" name="message" required rows={6} minLength={10} maxLength={4000} className="field" aria-invalid={fields.message ? true : undefined} aria-describedby={fields.message ? "ct-message-error" : undefined} />
        <FieldError id="ct-message-error" message={msg("message")} />
      </div>
      <p className="text-xs text-smoke">{t("gdprNote")}</p>
      {formError && <p className="field-error" role="alert">{formError}</p>}
      <button type="submit" className="btn btn-primary w-full" disabled={pending}>{pending ? t("sending") : t("submit")}</button>
    </form>
  );
}
