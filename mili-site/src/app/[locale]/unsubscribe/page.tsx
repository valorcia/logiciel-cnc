import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { StatusPage } from "@/components/site/page-shell";
import { UnsubscribeForm } from "@/components/site/unsubscribe-form";
import { subscriberFromToken } from "@/lib/subscribers";

export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ t?: string }> };

const mask = (email: string) => email.replace(/^(.).*(@.*)$/, "$1•••$2");

export default async function UnsubscribePage({ params, searchParams }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);
  const { t: token } = await searchParams;
  const t = await getTranslations({ locale, namespace: "unsubscribe" });
  const e = await getTranslations({ locale, namespace: "errors" });
  const sub = token ? await subscriberFromToken(token) : null;

  if (!sub || !token) return <StatusPage title={t("title")}><p>{t("invalid")}</p></StatusPage>;
  if (sub.status === "UNSUBSCRIBED") return <StatusPage title={t("doneTitle")}><p>{t("doneText")}</p></StatusPage>;
  return (
    <StatusPage title={t("title")}>
      <UnsubscribeForm
        token={token}
        labels={{ question: t("question", { email: mask(sub.email) }), confirm: t("confirm"), keep: t("keep"), doneTitle: t("doneTitle"), doneText: t("doneText"), error: e("generic") }}
      />
    </StatusPage>
  );
}
