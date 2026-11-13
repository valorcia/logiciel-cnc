import { getTranslations } from "next-intl/server";
import { countryOptions } from "@/lib/countries";
import { JoinForm } from "./join-form";

export async function JoinSection({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "join" });
  return (
    <section id="join" className="section hairline overflow-hidden">
      <div aria-hidden className="glow-violet pointer-events-none absolute inset-x-0 top-0 mx-auto h-[36rem] max-w-4xl" />
      <div className="shell relative grid items-center gap-12 lg:grid-cols-2 lg:gap-20">
        <div data-reveal>
          <p className="eyebrow mb-5">{t("text")}</p>
          <h2 className="display display-xl">{t("title")}</h2>
          <p className="lede mt-7 max-w-md">{t("points")}</p>
        </div>
        <div data-reveal style={{ "--reveal-delay": "120ms" } as React.CSSProperties}>
          <JoinForm countries={countryOptions(locale)} />
        </div>
      </div>
    </section>
  );
}
