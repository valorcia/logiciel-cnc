import type { ReactNode } from "react";
import { localeNames, locales } from "@/lib/i18n/config";

export function PageTitle({ title, text, actions }: { title: string; text?: string; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1>{title}</h1>
        {text && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ash">{text}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

const MESSAGES: Record<string, string> = {
  saved: "Modifications enregistrées.",
  created: "Élément créé.",
  deleted: "Élément supprimé.",
  sent: "Envoi effectué.",
};

/** Feedback after a redirect: ?ok=saved or ?error=message. */
export function Flash({ params }: { params: { ok?: string; error?: string; denied?: string } }) {
  if (params.error) return <p role="alert" className="mb-6 rounded-lg border border-[#ff5d73]/50 bg-[#ff5d73]/10 px-4 py-3 text-sm text-[#ff8a9a]">{params.error}</p>;
  if (params.denied) return <p role="alert" className="mb-6 rounded-lg border border-[#ffc46b]/40 bg-[#ffc46b]/10 px-4 py-3 text-sm text-[#ffc46b]">Votre rôle ne donne pas accès à cette page.</p>;
  if (params.ok) return <p role="status" className="mb-6 rounded-lg border border-cyan/40 bg-cyan/10 px-4 py-3 text-sm text-cyan">{MESSAGES[params.ok] ?? params.ok}</p>;
  return null;
}

export function Card({ title, children, className = "", aside }: { title?: string; children: ReactNode; className?: string; aside?: ReactNode }) {
  return (
    <section className={`adm-card ${className}`}>
      {(title || aside) && (
        <div className="mb-4 flex items-center justify-between gap-4">
          {title && <h2>{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

type FieldProps = {
  label: string; name: string; defaultValue?: string | number | null; type?: string; required?: boolean; help?: string;
  rows?: number; placeholder?: string; mono?: boolean; maxLength?: number; min?: number; step?: number;
};

export function Field({ label, name, defaultValue, type = "text", required, help, rows, placeholder, mono, maxLength, min, step }: FieldProps) {
  const id = `f-${name.replace(/[^a-z0-9]/gi, "-")}`;
  const cls = `field ${mono ? "font-mono text-sm" : ""}`;
  return (
    <div>
      <label htmlFor={id} className="field-label">{label}{required && <span className="text-cyan"> *</span>}</label>
      {rows ? (
        <textarea id={id} name={name} rows={rows} required={required} defaultValue={defaultValue ?? ""} placeholder={placeholder} maxLength={maxLength} className={cls} />
      ) : (
        <input id={id} name={name} type={type} required={required} defaultValue={defaultValue ?? ""} placeholder={placeholder} maxLength={maxLength} min={min} step={step} className={cls} />
      )}
      {help && <p className="mt-1.5 text-xs leading-relaxed text-smoke">{help}</p>}
    </div>
  );
}

/** One input per language. English is the reference; an empty language falls back to English on the site. */
export function LocalizedField({ label, name, value, rows, required, help }: { label: string; name: string; value?: unknown; rows?: number; required?: boolean; help?: string }) {
  const map = (value && typeof value === "object" ? value : {}) as Record<string, string>;
  return (
    <fieldset>
      <legend className="field-label">{label}{required && <span className="text-cyan"> *</span>}</legend>
      <div className="space-y-2">
        {locales.map((locale, index) => (
          <div key={locale} className="flex items-start gap-2">
            <span className="mt-2.5 w-7 flex-none font-mono text-xs uppercase text-smoke" title={localeNames[locale]}>{locale}</span>
            {rows ? (
              <textarea name={`${name}.${locale}`} rows={rows} required={required && index === 0} defaultValue={map[locale] ?? ""} aria-label={`${label} — ${localeNames[locale]}`} className="field" />
            ) : (
              <input name={`${name}.${locale}`} required={required && index === 0} defaultValue={map[locale] ?? ""} aria-label={`${label} — ${localeNames[locale]}`} className="field" />
            )}
          </div>
        ))}
      </div>
      {help && <p className="mt-1.5 text-xs leading-relaxed text-smoke">{help}</p>}
    </fieldset>
  );
}

export function Select({ label, name, defaultValue, options, help }: { label: string; name: string; defaultValue?: string | null; options: readonly (readonly [string, string])[]; help?: string }) {
  const id = `f-${name}`;
  return (
    <div>
      <label htmlFor={id} className="field-label">{label}</label>
      <select id={id} name={name} defaultValue={defaultValue ?? ""} className="field">
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
      {help && <p className="mt-1.5 text-xs leading-relaxed text-smoke">{help}</p>}
    </div>
  );
}

export function Check({ label, name, defaultChecked, help }: { label: string; name: string; defaultChecked?: boolean; help?: string }) {
  return (
    <div>
      <label className="flex cursor-pointer items-start gap-3 text-sm">
        <input type="checkbox" name={name} defaultChecked={defaultChecked} className="checkbox" />
        <span>{label}</span>
      </label>
      {help && <p className="ml-8 mt-1 text-xs leading-relaxed text-smoke">{help}</p>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "bad"; children: ReactNode }) {
  return <span className={`adm-badge ${tone === "ok" ? "adm-badge-ok" : tone === "warn" ? "adm-badge-warn" : tone === "bad" ? "adm-badge-bad" : ""}`}>{children}</span>;
}

export const STATUS_LABELS: Record<string, [string, "neutral" | "ok" | "warn" | "bad"]> = {
  DRAFT: ["Brouillon", "neutral"], SCHEDULED: ["Programmé", "warn"], PUBLISHED: ["Publié", "ok"], ARCHIVED: ["Archivé", "neutral"],
  PENDING: ["En attente", "warn"], APPROVED: ["Approuvé", "ok"], REJECTED: ["Refusé", "bad"],
  CONFIRMED: ["Confirmé", "ok"], UNSUBSCRIBED: ["Désinscrit", "neutral"], BOUNCED: ["Rejeté (bounce)", "bad"], COMPLAINED: ["Plainte spam", "bad"],
  SENT: ["Envoyé", "ok"], FAILED: ["Échec", "bad"], QUEUED: ["En file", "warn"], NOT_SENT_NO_PROVIDER: ["Non envoyé — pas de fournisseur", "warn"],
  OPEN: ["Ouvert", "warn"], IN_PROGRESS: ["En cours", "warn"], DONE: ["Traité", "ok"],
};

export function StatusBadge({ status }: { status: string }) {
  const [label, tone] = STATUS_LABELS[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-line px-5 py-10 text-center text-sm text-smoke">{children}</p>;
}

const dateFmt = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });
const dayFmt = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeZone: "UTC" });
export const fmtDate = (d: Date | null | undefined) => (d ? `${dateFmt.format(d)} UTC` : "—");
export const fmtDay = (d: Date | null | undefined) => (d ? dayFmt.format(d) : "—");
export const fmtNum = (n: number) => new Intl.NumberFormat("fr-FR").format(n);
export const fmtPct = (num: number, den: number) => (den > 0 ? `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format((num / den) * 100)} %` : "—");
