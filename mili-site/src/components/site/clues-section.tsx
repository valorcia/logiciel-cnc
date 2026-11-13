import { getFormatter, getTranslations } from "next-intl/server";
import { publicClues } from "@/lib/content";
import { ClueGrid } from "./clue-grid";

export async function CluesSection({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "clues" });
  const format = await getFormatter({ locale });
  const clues = await publicClues(locale);
  if (clues.length === 0) return null;

  return (
    <section id="clues" className="section hairline">
      <div className="shell">
        <div className="mb-14 max-w-3xl" data-reveal>
          <h2 className="display display-xl">{t("title")}</h2>
          <p className="lede mt-7">{t("subtitle")}</p>
        </div>
        <div data-reveal>
          <ClueGrid
            labels={{ locked: t("locked"), fresh: t("new"), watch: t("watch") }}
            items={clues.map((clue) => ({
              ...clue,
              label: t("label", { number: String(clue.number).padStart(2, "0") }),
              lockLabel: clue.publishAt
                ? t("unlocksOn", { date: format.dateTime(new Date(clue.publishAt), { dateStyle: "long", timeZone: "UTC" }) })
                : t("locked"),
            }))}
          />
        </div>
      </div>
    </section>
  );
}
