import { ImageResponse } from "next/og";
import { getTranslations } from "next-intl/server";
import { formatUsd, getSettings } from "@/lib/settings";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "MILLI is coming.";
export const revalidate = 3600;

/** Social preview. Mystery mode: words only — never an image of the machine. */
export default async function OpenGraphImage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "hero" });
  const settings = await getSettings();
  const line = [t("word1"), ...(settings.showPlannedPrice ? [`${formatUsd(settings.plannedPriceCents)}.`] : []), t("word3")].join("  ");

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", background: "#050505", color: "#fff", fontFamily: "sans-serif", backgroundImage: "radial-gradient(circle at 50% 40%, rgba(0,217,255,0.22), transparent 60%)" }}>
        <div style={{ fontSize: 30, letterSpacing: 10, color: "#A1A1AA", display: "flex" }}>{line}</div>
        <div style={{ fontSize: 150, fontWeight: 800, letterSpacing: -6, marginTop: 28, display: "flex", backgroundImage: "linear-gradient(100deg, #fff 20%, #00D9FF 60%, #7856FF)", backgroundClip: "text", color: "transparent" }}>{t("title")}</div>
        <div style={{ fontSize: 34, color: "#A1A1AA", marginTop: 30, display: "flex" }}>{t("subtitle")}</div>
      </div>
    ),
    size,
  );
}
