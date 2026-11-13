import { getTranslations } from "next-intl/server";
import type { Locale } from "@/lib/i18n/config";
import { getSettings } from "@/lib/settings";
import { HeaderClient } from "./header-client";

export async function Header({ locale }: { locale: Locale }) {
  const [t, settings] = await Promise.all([getTranslations({ locale, namespace: "nav" }), getSettings()]);
  const revealed = settings.mode === "REVEAL";
  const links = [
    ...(revealed ? [{ href: "/mili", label: t("product") }] : [{ href: "/#mystery", label: t("mystery") }]),
    { href: "/#proof", label: t("proof") },
    ...(revealed ? [] : [{ href: "/#clues", label: t("clues") }]),
    { href: "/#challenge", label: t("challenge") },
    { href: "/journal", label: t("journal") },
  ];
  const cta =
    revealed && settings.kickstarterUrl
      ? { href: settings.kickstarterUrl, label: t("back"), external: true }
      : { href: "/#join", label: t("cta"), external: false };

  return (
    <HeaderClient
      links={links}
      cta={cta}
      labels={{ menu: t("menu"), close: t("close"), language: t("language") }}
    />
  );
}
