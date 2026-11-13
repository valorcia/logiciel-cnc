import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { StatusPage } from "@/components/site/page-shell";
import { Link } from "@/i18n/navigation";
import { insiderToken } from "@/lib/links";
import { requestMeta } from "@/lib/request";
import { confirmSubscription } from "@/lib/subscribers";

export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ token?: string }> };

export default async function ConfirmPage({ params, searchParams }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const { token } = await searchParams;
  const t = await getTranslations({ locale, namespace: "confirm" });
  const meta = await requestMeta();
  const outcome = await confirmSubscription(token ?? "", { ipHash: meta.ipHash, userAgent: meta.userAgent });

  if (!outcome.ok) {
    const expired = outcome.error === "expired";
    return (
      <StatusPage title={t(expired ? "expiredTitle" : "invalidTitle")}>
        <p>{t(expired ? "expiredText" : "invalidText")}</p>
        <Link href="/#join" className="btn btn-primary mt-9">{t("back")}</Link>
      </StatusPage>
    );
  }
  return (
    <StatusPage eyebrow={outcome.subscriber.publicId} title={t("title")}>
      <p>{t(outcome.alreadyConfirmed ? "already" : "text")}</p>
      <Link href={`/insider/${insiderToken(outcome.subscriber)}`} className="btn btn-primary mt-9">{t("cta")}</Link>
    </StatusPage>
  );
}
