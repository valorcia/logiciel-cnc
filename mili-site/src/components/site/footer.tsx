import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import type { Locale } from "@/lib/i18n/config";
import { getSettings, socialLinks } from "@/lib/settings";

const SOCIAL_LABELS: Record<string, string> = {
  x: "X", youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", reddit: "Reddit", tiktok: "TikTok", discord: "Discord",
};

export async function Footer({ locale }: { locale: Locale }) {
  const [t, settings] = await Promise.all([getTranslations({ locale, namespace: "footer" }), getSettings()]);
  const socials = Object.entries(socialLinks(settings));
  const legal = [settings.legalName, settings.postalAddress].filter(Boolean).join(" · ");

  return (
    <footer className="hairline bg-void">
      <div className="shell py-14">
        <div className="flex flex-col justify-between gap-10 md:flex-row">
          <div>
            <p className="text-2xl font-semibold tracking-[0.32em]">MILLI</p>
            <p className="mt-3 text-sm text-ash">{t("tagline")}</p>
          </div>
          <nav className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-ash" aria-label="Footer">
            <Link href="/journal" className="hover:text-white">{t("journal")}</Link>
            <Link href="/contact" className="hover:text-white">{t("contact")}</Link>
            <Link href="/privacy" className="hover:text-white">{t("privacy")}</Link>
            <Link href="/terms" className="hover:text-white">{t("terms")}</Link>
            <Link href="/cookies" className="hover:text-white">{t("cookies")}</Link>
          </nav>
        </div>

        {socials.length > 0 && (
          <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <span className="eyebrow">{t("follow")}</span>
            {socials.map(([key, url]) => (
              <a key={key} href={url} target="_blank" rel="noopener noreferrer" className="text-ash hover:text-white">
                {SOCIAL_LABELS[key] ?? key}
              </a>
            ))}
          </div>
        )}

        {settings.mode === "MYSTERY" && settings.showPlannedPrice && (
          <p className="mt-10 max-w-3xl text-xs leading-relaxed text-smoke">{t("priceNote")}</p>
        )}
        <p className="mt-6 text-xs text-smoke">
          {t("rights", { year: new Date().getFullYear() })}
          {legal ? ` · ${legal}` : ""}
        </p>
      </div>
    </footer>
  );
}
