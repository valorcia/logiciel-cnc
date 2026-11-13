"use client";

import { useLocale, useTranslations } from "next-intl";
import { useActionState } from "react";
import { subscribeAction, type FormState } from "@/app/actions/public";
import { Link } from "@/i18n/navigation";
import { AttributionFields, FieldError, SpamGuard, SuccessMark } from "./form-bits";

const initial: FormState = { status: "idle" };

export function JoinForm({ countries }: { countries: { code: string; label: string }[] }) {
  const t = useTranslations("join");
  const e = useTranslations("errors");
  const locale = useLocale();
  const [state, action, pending] = useActionState(subscribeAction, initial);

  if (state.status === "success") {
    return (
      <div className="panel flex flex-col items-center px-6 py-12 text-center" role="status" aria-live="polite">
        <SuccessMark />
        <h3 className="mt-6 text-3xl font-semibold tracking-tight">{t("successTitle")}</h3>
        <p className="mt-3 max-w-md text-ash">{t("successText", { email: state.email ?? "" })}</p>
        <p className="mt-4 max-w-md text-sm text-smoke">{t("successNote")}</p>
      </div>
    );
  }

  const fields = state.status === "error" ? (state.fields ?? {}) : {};
  const formError = state.status === "error" && !state.fields ? e.has(state.code) ? e(state.code) : e("generic") : null;
  const fieldMessage = (name: string) => (fields[name] ? (e.has(fields[name]) ? e(fields[name]) : e("invalid")) : undefined);

  return (
    <form action={action} className="panel relative space-y-5 p-6 sm:p-8" noValidate>
      <SpamGuard />
      <AttributionFields />
      <input type="hidden" name="locale" value={locale} />

      <div>
        <label htmlFor="join-email" className="field-label">{t("email")}</label>
        <input
          id="join-email" name="email" type="email" required autoComplete="email" inputMode="email"
          className="field" placeholder="you@example.com"
          aria-invalid={fields.email ? true : undefined} aria-describedby={fields.email ? "join-email-error" : undefined}
        />
        <FieldError id="join-email-error" message={fieldMessage("email")} />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor="join-first-name" className="field-label">{t("firstName")}</label>
          <input id="join-first-name" name="firstName" type="text" autoComplete="given-name" maxLength={60} className="field" />
        </div>
        <div>
          <label htmlFor="join-country" className="field-label">{t("country")}</label>
          <select id="join-country" name="country" autoComplete="country" className="field" defaultValue="">
            <option value="">{t("countryPlaceholder")}</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>{c.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="flex cursor-pointer items-start gap-3 text-sm leading-relaxed text-ash">
          <input type="checkbox" name="consent" required className="checkbox" aria-describedby={fields.consent ? "join-consent-error" : undefined} />
          <span>
            {t("consent")}{" "}
            <Link href="/privacy" className="text-white underline underline-offset-4 hover:text-cyan">{t("privacy")}</Link>
          </span>
        </label>
        <FieldError id="join-consent-error" message={fieldMessage("consent")} />
      </div>

      {formError && <p className="field-error" role="alert">{formError}</p>}

      <button type="submit" className="btn btn-primary w-full" disabled={pending}>
        {pending ? t("sending") : t("submit")}
      </button>
    </form>
  );
}
