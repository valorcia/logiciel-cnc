"use client";

import { useLocale } from "next-intl";
import { useEffect, useState } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { localeNames, locales } from "@/lib/i18n/config";

type Props = {
  links: { href: string; label: string }[];
  cta: { href: string; label: string; external: boolean };
  labels: { menu: string; close: string; language: string };
};

export function HeaderClient({ links, cta, labels }: Props) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();
  const locale = useLocale();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const Cta = ({ className }: { className: string }) =>
    cta.external ? (
      <a href={cta.href} target="_blank" rel="noopener noreferrer" className={className} onClick={() => setOpen(false)}>
        {cta.label}
      </a>
    ) : (
      <Link href={cta.href} className={className} onClick={() => setOpen(false)}>
        {cta.label}
      </Link>
    );

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
        scrolled || open ? "border-b border-line bg-void/85 backdrop-blur-md" : "border-b border-transparent"
      }`}
    >
      <div className="shell flex h-16 items-center justify-between gap-6">
        <Link href="/" className="text-lg font-semibold tracking-[0.32em]" aria-label="MILI">
          MILI
        </Link>

        <nav className="hidden items-center gap-8 lg:flex" aria-label="Primary">
          {links.map((link) => (
            <Link key={link.href} href={link.href} className="text-sm text-ash transition-colors hover:text-white">
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <label className="relative hidden sm:block">
            <span className="sr-only">{labels.language}</span>
            <LanguageSelect pathname={pathname} locale={locale} />
          </label>
          <Cta className="btn btn-primary btn-sm hidden sm:inline-flex" />
          <button
            type="button"
            className="grid h-10 w-10 place-items-center rounded-full border border-line lg:hidden"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? labels.close : labels.menu}
            onClick={() => setOpen((v) => !v)}
          >
            <span className="relative block h-3 w-4" aria-hidden>
              <span className={`absolute inset-x-0 top-0 h-px bg-white transition-transform ${open ? "translate-y-[6px] rotate-45" : ""}`} />
              <span className={`absolute inset-x-0 bottom-0 h-px bg-white transition-transform ${open ? "-translate-y-[5px] -rotate-45" : ""}`} />
            </span>
          </button>
        </div>
      </div>

      {open && (
        <div id="mobile-menu" className="border-t border-line bg-void lg:hidden">
          <nav className="shell flex flex-col py-6" aria-label="Mobile">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="border-b border-line py-4 text-2xl font-medium tracking-tight"
              >
                {link.label}
              </Link>
            ))}
            <div className="mt-6 flex flex-wrap gap-2" aria-label={labels.language}>
              {locales.map((l) => (
                <Link
                  key={l}
                  href={pathname}
                  locale={l}
                  onClick={() => setOpen(false)}
                  aria-current={l === locale ? "true" : undefined}
                  className={`rounded-full border px-4 py-2 text-sm ${l === locale ? "border-white text-white" : "border-line text-ash"}`}
                >
                  {localeNames[l]}
                </Link>
              ))}
            </div>
            <Cta className="btn btn-primary mt-6 w-full" />
          </nav>
        </div>
      )}
    </header>
  );
}

function LanguageSelect({ pathname, locale }: { pathname: string; locale: string }) {
  // Real links (crawlable, work without JS) laid out as a compact disclosure.
  return (
    <details className="group relative">
      <summary className="flex h-10 cursor-pointer list-none items-center gap-2 rounded-full border border-line px-4 text-xs uppercase tracking-widest text-ash transition-colors hover:text-white [&::-webkit-details-marker]:hidden">
        {locale}
        <span aria-hidden className="text-[0.6rem] transition-transform group-open:rotate-180">▾</span>
      </summary>
      <ul className="absolute right-0 top-12 min-w-40 rounded-xl border border-line bg-carbon p-1.5 shadow-2xl">
        {locales.map((l) => (
          <li key={l}>
            <Link
              href={pathname}
              locale={l}
              hrefLang={l}
              aria-current={l === locale ? "true" : undefined}
              className={`block rounded-lg px-3 py-2 text-sm hover:bg-white/5 ${l === locale ? "text-white" : "text-ash"}`}
            >
              {localeNames[l]}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}
