import { getTranslations } from "next-intl/server";
import { publicFaqs } from "@/lib/content";
import { jsonLd } from "@/lib/seo";

export async function FaqSection({ locale, mode }: { locale: string; mode: "MYSTERY" | "REVEAL" }) {
  const t = await getTranslations({ locale, namespace: "faq" });
  const faqs = await publicFaqs(locale, mode);
  if (faqs.length === 0) return null;

  const schema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({ "@type": "Question", name: f.question, acceptedAnswer: { "@type": "Answer", text: f.answer } })),
  };

  return (
    <section id="faq" className="section hairline">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(schema) }} />
      <div className="shell grid gap-12 lg:grid-cols-[0.8fr_1.2fr]">
        <h2 className="display display-lg" data-reveal>{t("title")}</h2>
        <div className="border-t border-line" data-reveal>
          {faqs.map((faq) => (
            <details key={faq.id} className="group border-b border-line">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-6 text-lg font-medium tracking-tight transition hover:text-cyan [&::-webkit-details-marker]:hidden">
                {faq.question}
                <span aria-hidden className="relative h-4 w-4 flex-none">
                  <span className="absolute left-0 top-1/2 h-px w-4 bg-current" />
                  <span className="absolute left-0 top-1/2 h-px w-4 rotate-90 bg-current transition-transform duration-300 group-open:rotate-0" />
                </span>
              </summary>
              <p className="max-w-2xl whitespace-pre-line pb-7 leading-relaxed text-ash">{faq.answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
