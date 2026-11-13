import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { approvedChallenges } from "@/lib/content";
import { maxUploadBytes } from "@/lib/storage";
import { ChallengeForm } from "./challenge-form";
import { ChallengeList } from "./challenge-list";

export async function ChallengeSection({ locale, full = false }: { locale: string; full?: boolean }) {
  const t = await getTranslations({ locale, namespace: "challenge" });
  const items = await approvedChallenges(full ? 60 : 3);
  const Heading = full ? "h1" : "h2";

  return (
    <section id="challenge" className={`section ${full ? "" : "hairline"}`}>
      <div className="shell">
        <div className="grid items-start gap-12 lg:grid-cols-2 lg:gap-20">
          <div data-reveal className="lg:sticky lg:top-28">
            <p className="eyebrow mb-5">{t("subtitle")}</p>
            <Heading className="display display-xl">{t("title")}</Heading>
            <p className="lede mt-7 max-w-md">{t("intro")}</p>
          </div>
          <div data-reveal style={{ "--reveal-delay": "120ms" } as React.CSSProperties}>
            <ChallengeForm maxMb={Math.floor(maxUploadBytes() / 1024 / 1024)} />
          </div>
        </div>

        {(full || items.length > 0) && (
          <div className="mt-24" data-reveal>
            <div className="mb-8 flex items-end justify-between gap-6">
              <h3 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("galleryTitle")}</h3>
              {!full && <Link href="/challenge" className="text-sm text-ash underline underline-offset-4 hover:text-white">{t("seeAll")}</Link>}
            </div>
            <ChallengeList locale={locale} items={items} />
          </div>
        )}
      </div>
    </section>
  );
}
