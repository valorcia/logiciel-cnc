import { getTranslations } from "next-intl/server";
import type { RevealContent } from "@/lib/content";
import { renderSiteMarkdown } from "@/lib/markdown";
import { formatUsd } from "@/lib/settings";
import { VideoPlayer } from "./video-player";

type Props = { locale: string; content: RevealContent; kickstarterUrl: string | null };

/**
 * The product page body. It prints what administrators entered and validated —
 * a section with no text, an unvalidated specification or an inactive reward
 * simply does not exist here.
 */
export async function ProductView({ locale, content, kickstarterUrl }: Props) {
  const t = await getTranslations({ locale, namespace: "reveal" });
  const nav = [
    ...content.sections.map((s) => ({ id: s.key, label: s.title })),
    ...(content.specs.length ? [{ id: "specifications", label: t("specs") }] : []),
    ...(content.kit.length ? [{ id: "kit", label: t("kit") }] : []),
    ...(content.tiers.length ? [{ id: "rewards", label: t("rewards") }] : []),
  ];

  return (
    <>
      <section className="relative overflow-hidden pt-[calc(var(--header-h)+4rem)]">
        <div aria-hidden className="glow-cyan pointer-events-none absolute inset-x-0 top-0 mx-auto h-[36rem] max-w-5xl" />
        <div className="shell relative text-center">
          <p className="eyebrow mb-6">{t("heroSubtitle")}</p>
          <h1 className="display display-xl"><span className="text-gradient">{t("heroTitle")}</span></h1>
          <div className="mt-10 flex justify-center">
            {kickstarterUrl ? (
              <a href={kickstarterUrl} rel="noopener" className="btn btn-primary">{t("cta")}</a>
            ) : (
              <span className="btn btn-ghost" aria-disabled="true">{t("ctaSoon")}</span>
            )}
          </div>
          {content.heroImageId && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`/media/${content.heroImageId}`} alt="MILLI" fetchPriority="high" className="mx-auto mt-16 aspect-[16/9] w-full max-w-6xl rounded-2xl border border-line object-cover" />
          )}
          {content.filmUrl && (
            <div className="mx-auto mt-10 max-w-5xl">
              <VideoPlayer video={content.filmUrl} title={t("watch")} playLabel={t("watch")} />
            </div>
          )}
        </div>
      </section>

      {nav.length > 1 && (
        <nav aria-label={t("discover")} className="sticky top-[var(--header-h)] z-30 mt-16 border-y border-line bg-void/85 backdrop-blur">
          <ul className="shell flex gap-6 overflow-x-auto py-3.5 text-xs uppercase tracking-[0.14em] text-ash">
            {nav.map((item) => (
              <li key={item.id} className="flex-none"><a href={`#${item.id}`} className="hover:text-white">{item.label}</a></li>
            ))}
          </ul>
        </nav>
      )}

      {content.sections.map((section) => (
        <section key={section.key} id={section.key} className="section hairline scroll-mt-28">
          <div className="shell grid gap-10 lg:grid-cols-[0.8fr_1.2fr]">
            <h2 className="display display-lg" data-reveal>{section.title}</h2>
            <div className="prose-milli" data-reveal dangerouslySetInnerHTML={{ __html: renderSiteMarkdown(section.body) }} />
          </div>
        </section>
      ))}

      {content.gallery.length > 0 && (
        <section className="section hairline">
          <div className="shell">
            <h2 className="display display-lg mb-12" data-reveal>{t("gallery")}</h2>
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {content.gallery.map((image) => (
                <li key={image.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`/media/${image.id}`} alt={image.alt} loading="lazy" decoding="async" className="aspect-[4/3] w-full rounded-xl border border-line object-cover" />
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {content.specs.length > 0 && (
        <section id="specifications" className="section hairline scroll-mt-28">
          <div className="shell grid gap-10 lg:grid-cols-[0.8fr_1.2fr]">
            <div data-reveal>
              <h2 className="display display-lg">{t("specs")}</h2>
              <p className="mt-5 max-w-sm text-sm text-smoke">{t("specsNote")}</p>
            </div>
            <div className="space-y-10" data-reveal>
              {content.specs.map((group) => (
                <table key={group.group} className="w-full text-left">
                  {group.group && <caption className="eyebrow pb-3 text-left">{group.group}</caption>}
                  <tbody>
                    {group.rows.map((row) => (
                      <tr key={row.label} className="border-t border-line">
                        <th scope="row" className="w-2/5 py-4 pr-4 align-top text-sm font-normal text-ash">{row.label}</th>
                        <td className="py-4 text-white">{row.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </div>
          </div>
        </section>
      )}

      {content.kit.length > 0 && (
        <section id="kit" className="section hairline scroll-mt-28">
          <div className="shell">
            <h2 className="display display-lg mb-12" data-reveal>{t("kit")}</h2>
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-reveal>
              {content.kit.map((item) => (
                <li key={item.name} className="panel p-6">
                  <div className="flex items-baseline justify-between gap-4">
                    <h3 className="text-lg font-semibold tracking-tight">{item.name}</h3>
                    {item.quantity && <span className="font-mono text-sm text-cyan">{item.quantity}</span>}
                  </div>
                  {item.description && <p className="mt-2 text-sm leading-relaxed text-ash">{item.description}</p>}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {content.tiers.length > 0 && (
        <section id="rewards" className="section hairline scroll-mt-28">
          <div className="shell">
            <h2 className="display display-lg mb-12" data-reveal>{t("rewards")}</h2>
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-reveal>
              {content.tiers.map((tier) => (
                <li key={tier.id} className="panel flex flex-col p-6">
                  <h3 className="eyebrow">{tier.name}</h3>
                  <p className="mt-4 text-5xl font-semibold tracking-tight">{formatUsd(tier.priceCents)}</p>
                  {tier.description && <p className="mt-4 text-sm leading-relaxed text-ash">{tier.description}</p>}
                  {tier.quantityLimit != null && <p className="mt-4 text-xs text-cyan">{t("limited", { count: tier.quantityLimit })}</p>}
                  {tier.conditions && <p className="mt-auto pt-5 text-xs leading-relaxed text-smoke">{tier.conditions}</p>}
                </li>
              ))}
            </ul>
            <p className="mt-8 max-w-2xl text-xs leading-relaxed text-smoke">{t("rewardsNote")}</p>
            {kickstarterUrl && <a href={kickstarterUrl} rel="noopener" className="btn btn-primary mt-8">{t("cta")}</a>}
          </div>
        </section>
      )}
    </>
  );
}
