import { getTranslations } from "next-intl/server";
import { formatUsd } from "@/lib/settings";
import type { SiteSettings } from "@/generated/prisma/client";
import { MysteryStage } from "./mystery-stage";
import { Orbits } from "./orbits";

export async function MysterySection({ locale, settings }: { locale: string; settings: SiteSettings }) {
  const t = await getTranslations({ locale, namespace: "mystery" });
  const known = [t("known1"), t("known2"), ...(settings.showPlannedPrice ? [t("known3", { price: formatUsd(settings.plannedPriceCents) })] : [])];

  return (
    <section id="mystery" className="section hairline overflow-hidden">
      <div className="shell">
        <div className="mx-auto max-w-4xl text-center" data-reveal>
          <h2 className="display display-xl">{t("title")}</h2>
          <p className="lede mx-auto mt-8 max-w-2xl">{t("text")}</p>
        </div>

        <div className="mt-16 grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]" data-reveal>
          <div className="relative mx-auto aspect-square w-full max-w-[34rem]">
            <div aria-hidden className="glow-cyan absolute inset-0" />
            <Orbits label={t("title")} />
          </div>

          <MysteryStage
            hint={t("hint")}
            classified={t("classified")}
            known={known}
            axisLabels={[1, 2, 3, 4, 5].map((n) => t("axis", { number: String(n).padStart(2, "0") }))}
          />
        </div>

        <p className="mx-auto mt-20 max-w-3xl text-center text-2xl font-medium tracking-tight text-white sm:text-4xl" data-reveal>
          {t("final")}
        </p>
      </div>
    </section>
  );
}
