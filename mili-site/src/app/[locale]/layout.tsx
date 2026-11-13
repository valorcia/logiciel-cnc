import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { Attribution } from "@/components/site/attribution";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { RevealObserver } from "@/components/site/reveal-observer";
import { routing } from "@/i18n/routing";
import { baseUrl, pageMetadata } from "@/lib/seo";
import type { Locale } from "@/lib/i18n/config";
import "../globals.css";

type Props = { children: ReactNode; params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export const viewport: Viewport = { themeColor: "#050505", colorScheme: "dark" };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "meta" });
  return {
    metadataBase: new URL(baseUrl()),
    ...pageMetadata({ locale: locale as Locale, path: "/", title: t("title"), description: t("description") }),
    title: { default: t("title"), template: "%s — MILLI" },
    applicationName: "MILLI",
    keywords: [
      "5 axis CNC", "affordable 5 axis CNC", "DIY CNC", "CNC kit", "desktop CNC", "CNC machining",
      "5 axis milling machine", "Kickstarter CNC",
    ],
    formatDetection: { telephone: false },
  };
}

/** Runs before first paint: skips the hero intro for visitors who already saw it this session. */
const introScript = `try{document.documentElement.classList.remove('no-js');if(sessionStorage.getItem('milli_intro')){document.documentElement.dataset.intro='skip'}else{sessionStorage.setItem('milli_intro','1')}}catch(e){}`;

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "nav" });

  return (
    <html lang={locale} className={`no-js ${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: introScript }} />
      </head>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-full focus:bg-white focus:px-5 focus:py-3 focus:text-sm focus:font-semibold focus:text-void">
          {t("skip")}
        </a>
        <NextIntlClientProvider>
          <Header locale={locale as Locale} />
          <main id="main">{children}</main>
          <Footer locale={locale as Locale} />
          <Attribution locale={locale} />
          <RevealObserver />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
