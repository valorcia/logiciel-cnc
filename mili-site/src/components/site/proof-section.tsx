import { getFormatter, getTranslations } from "next-intl/server";
import { publicProofVideos } from "@/lib/content";
import { formatDuration } from "@/lib/video";
import { ProofGallery } from "./proof-gallery";

export async function ProofSection({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "proof" });
  const format = await getFormatter({ locale });
  const videos = await publicProofVideos(locale);

  return (
    <section id="proof" className="section hairline">
      <div className="shell">
        <div className="mx-auto max-w-4xl text-center" data-reveal>
          <h2 className="display display-xl">{t("title")}</h2>
          {videos.length > 0 && <p className="lede mx-auto mt-8 max-w-2xl">{t("subtitle")}</p>}
        </div>

        <div className="mt-16" data-reveal>
          {videos.length === 0 ? (
            /* No validated demonstration yet: a neutral holding state, never borrowed footage. */
            <div className="panel relative mx-auto max-w-3xl overflow-hidden px-6 py-16 text-center sm:px-12">
              <div aria-hidden className="scanline" />
              <p className="eyebrow mb-5">REC — 00:00:00</p>
              <h3 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("emptyTitle")}</h3>
              <p className="mx-auto mt-4 max-w-xl text-ash">{t("emptyText")}</p>
            </div>
          ) : (
            <ProofGallery
              labels={{ all: t("all"), validated: t("validated"), play: t("play") }}
              items={videos.map((v) => ({
                ...v,
                durationLabel: formatDuration(v.duration),
                dateLabel: v.recordedAt ? t("recorded", { date: format.dateTime(new Date(v.recordedAt), { dateStyle: "medium", timeZone: "UTC" }) }) : null,
                categoryLabel: t(`categories.${v.category}` as "categories.PRECISION"),
              }))}
            />
          )}
        </div>
      </div>
    </section>
  );
}
