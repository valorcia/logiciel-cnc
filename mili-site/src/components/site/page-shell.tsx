import type { ReactNode } from "react";

/** Centered, narrow layout for utility pages (confirmation, unsubscribe, errors). */
export function StatusPage({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <section className="relative flex min-h-[80svh] items-center overflow-hidden pt-[var(--header-h)]">
      <div aria-hidden className="glow-cyan pointer-events-none absolute inset-x-0 top-0 mx-auto h-[32rem] max-w-4xl" />
      <div className="shell relative py-20 text-center">
        {eyebrow && <p className="eyebrow mb-6">{eyebrow}</p>}
        <h1 className="display display-lg mx-auto max-w-3xl">{title}</h1>
        <div className="mx-auto mt-7 max-w-xl text-ash">{children}</div>
      </div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, text }: { eyebrow?: string; title: string; text?: string }) {
  return (
    <header className="shell pb-12 pt-[calc(var(--header-h)+5rem)]">
      {eyebrow && <p className="eyebrow mb-5">{eyebrow}</p>}
      <h1 className="display display-xl">{title}</h1>
      {text && <p className="lede mt-7 max-w-2xl">{text}</p>}
    </header>
  );
}
