import { getTranslations } from "next-intl/server";
import { StatusPage } from "@/components/site/page-shell";
import { Link } from "@/i18n/navigation";

export default async function NotFound() {
  const t = await getTranslations("notFound");
  return (
    <StatusPage title={t("title")}>
      <p>{t("text")}</p>
      <Link href="/" className="btn btn-primary mt-9">{t("back")}</Link>
    </StatusPage>
  );
}
