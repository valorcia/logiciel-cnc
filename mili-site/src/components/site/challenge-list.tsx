import { getTranslations } from "next-intl/server";
import type { PublicChallenge } from "@/lib/content";
import { VoteButton } from "./vote-button";

export async function ChallengeList({ locale, items }: { locale: string; items: PublicChallenge[] }) {
  const t = await getTranslations({ locale, namespace: "challenge" });
  const e = await getTranslations({ locale, namespace: "errors" });
  if (items.length === 0) return <p className="panel px-6 py-10 text-center text-ash">{t("galleryEmpty")}</p>;

  return (
    <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map((c) => (
        <li key={c.id} className="panel flex flex-col p-6">
          <p className="font-mono text-[0.6875rem] uppercase tracking-[0.2em] text-cyan">{t(`categories.${c.category}` as "categories.OTHER")}</p>
          <h3 className="mt-4 text-xl font-semibold leading-snug tracking-tight">{c.title}</h3>
          {c.description && <p className="mt-2 text-sm leading-relaxed text-ash">{c.description}</p>}
          <div className="mt-auto flex items-end justify-between gap-4 pt-6">
            <p className="text-xs text-smoke">{c.displayName ? t("by", { name: c.displayName }) : ""}</p>
            <VoteButton id={c.id} votes={c.votes} labels={{ vote: t("vote"), voted: t("voted"), errors: { rate: e("rate"), generic: e("generic") } }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
