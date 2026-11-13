"use client";

import { useLocale, useTranslations } from "next-intl";
import { useActionState, useState } from "react";
import { submitChallengeAction, type FormState } from "@/app/actions/public";
import { FieldError, SpamGuard, SuccessMark } from "./form-bits";

const initial: FormState = { status: "idle" };
const CATEGORIES = ["ART_DESIGN", "ENGINEERING", "ROBOTICS", "AUTOMOTIVE", "AEROSPACE", "JEWELRY", "EDUCATION", "OTHER"] as const;
const ACCEPT = ".step,.stp,.stl,.obj,.pdf,.jpg,.jpeg,.png";

export function ChallengeForm({ maxMb }: { maxMb: number }) {
  const t = useTranslations("challenge");
  const e = useTranslations("errors");
  const locale = useLocale();
  const [state, action, pending] = useActionState(submitChallengeAction, initial);
  const [tooLarge, setTooLarge] = useState(false);

  if (state.status === "success") {
    return (
      <div className="panel flex flex-col items-center px-6 py-12 text-center" role="status" aria-live="polite">
        <SuccessMark />
        <h3 className="mt-6 text-3xl font-semibold tracking-tight">{t("successTitle")}</h3>
        <p className="mt-3 max-w-md text-ash">{t("successText")}</p>
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

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor="ch-name" className="field-label">{t("name")}</label>
          <input id="ch-name" name="name" type="text" required autoComplete="name" maxLength={80} className="field" aria-invalid={fields.name ? true : undefined} aria-describedby={fields.name ? "ch-name-error" : undefined} />
          <FieldError id="ch-name-error" message={msg("name")} />
        </div>
        <div>
          <label htmlFor="ch-email" className="field-label">{t("email")}</label>
          <input id="ch-email" name="email" type="email" required autoComplete="email" inputMode="email" className="field" aria-invalid={fields.email ? true : undefined} aria-describedby={fields.email ? "ch-email-error" : undefined} />
          <FieldError id="ch-email-error" message={msg("email")} />
        </div>
      </div>

      <div>
        <label htmlFor="ch-category" className="field-label">{t("category")}</label>
        <select id="ch-category" name="category" className="field" defaultValue="ENGINEERING">
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{t(`categories.${c}`)}</option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="ch-description" className="field-label">{t("description")}</label>
        <textarea id="ch-description" name="description" required rows={5} minLength={20} maxLength={2000} className="field" aria-invalid={fields.description ? true : undefined} aria-describedby="ch-description-help" />
        <p id="ch-description-help" className="mt-1.5 text-xs text-smoke">{t("descriptionHelp")}</p>
        <FieldError id="ch-description-error" message={msg("description")} />
      </div>

      <div>
        <label htmlFor="ch-file" className="field-label">{t("file")}</label>
        <input
          id="ch-file" name="file" type="file" accept={ACCEPT} aria-describedby="ch-file-help"
          onChange={(ev) => setTooLarge((ev.target.files?.[0]?.size ?? 0) > maxMb * 1024 * 1024)}
          className="block w-full text-sm text-ash file:mr-4 file:rounded-full file:border file:border-solid file:border-line file:bg-transparent file:px-4 file:py-2 file:text-xs file:font-medium file:uppercase file:tracking-[0.12em] file:text-white hover:file:border-white"
        />
        <p id="ch-file-help" className="mt-1.5 text-xs text-smoke">{t("fileHelp", { max: maxMb })}</p>
        <FieldError id="ch-file-error" message={tooLarge ? e("fileTooLarge") : msg("file")} />
      </div>

      <div>
        <label className="flex cursor-pointer items-start gap-3 text-sm leading-relaxed text-ash">
          <input type="checkbox" name="consent" required className="checkbox" />
          <span>{t("consent")}</span>
        </label>
        <FieldError id="ch-consent-error" message={msg("consent")} />
      </div>

      {formError && <p className="field-error" role="alert">{formError}</p>}

      <button type="submit" className="btn btn-primary w-full" disabled={pending || tooLarge}>
        {pending ? t("sending") : t("submit")}
      </button>
    </form>
  );
}
