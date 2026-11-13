import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { ReactNode } from "react";
import "../globals.css";

export const metadata: Metadata = {
  title: { default: "Administration — MILI", template: "%s — Administration MILI" },
  robots: { index: false, follow: false, nocache: true },
  referrer: "same-origin",
};
export const viewport: Viewport = { themeColor: "#050505", colorScheme: "dark" };

/** Root layout of the back office. Separate from the public site: French interface, never indexed. */
export default function AdminRootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="adm">{children}</body>
    </html>
  );
}
