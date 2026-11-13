import Link from "next/link";
import { notFound } from "next/navigation";
import { Submit } from "@/components/admin/client";
import { MediaSelect, mediaOptions, STATUS_OPTIONS } from "@/components/admin/pickers";
import { Card, Field, Flash, PageTitle, Select } from "@/components/admin/ui";
import { requireAdmin } from "@/lib/admin-session";
import { db } from "@/lib/db";
import { localeNames, localePath, locales } from "@/lib/i18n/config";
import { toInputDateTime } from "../../../_lib/form";
import { deleteArticleAction, saveArticleAction } from "../../../actions/content";

export const metadata = { title: "Article" };
const CATEGORIES = [["CNC_TECHNOLOGY", "CNC Technology"], ["FIVE_AXIS_MACHINING", "5-Axis Machining"], ["MAKER_PROJECTS", "Maker Projects"], ["ENGINEERING", "Engineering"], ["MILI_NEWS", "MILI News"]] as const;

export default async function ArticleEditPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ok?: string; error?: string }> }) {
  await requireAdmin("journal.edit");
  const { id } = await params;
  const article = id === "new" ? null : await db.article.findUnique({ where: { id } });
  if (id !== "new" && !article) notFound();
  const media = await mediaOptions();
  const live = article && (article.status === "PUBLISHED" || article.status === "SCHEDULED") && (!article.publishAt || article.publishAt <= new Date());

  return (
    <>
      <PageTitle
        title={article ? article.title : "Nouvel article"}
        actions={<>
          <Link href="/admin/journal" className="adm-btn adm-btn-ghost">← Tous les articles</Link>
          {live && article && <a href={localePath(article.locale, `/journal/${article.slug}`)} target="_blank" rel="noopener" className="adm-btn adm-btn-ghost">Voir en ligne ↗</a>}
        </>}
      />
      <Flash params={await searchParams} />
      <form action={saveArticleAction} className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <input type="hidden" name="id" value={article?.id ?? ""} />
        <Card>
          <div className="space-y-4">
            <Field label="Titre" name="title" defaultValue={article?.title} required maxLength={160} />
            <Field label="Résumé" name="excerpt" defaultValue={article?.excerpt} rows={2} maxLength={300} help="Affiché dans la liste des articles et, par défaut, dans Google." />
            <Field label="Contenu (Markdown)" name="body" defaultValue={article?.body} rows={24} mono
              help="## Titre · ### Sous-titre · **gras** · *italique* · - liste · 1. liste numérotée · > citation · [lien](https://…) · image : ![description](/media/IDENTIFIANT) — l'identifiant se copie depuis Médias." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Publication">
            <div className="space-y-4">
              <Select label="Statut" name="status" defaultValue={article?.status ?? "DRAFT"} options={STATUS_OPTIONS} />
              <Field label="Date de publication (UTC)" name="publishAt" type="datetime-local" defaultValue={toInputDateTime(article?.publishAt)} help="Requise pour « Programmé » : l'article apparaît seul à cette date." />
              <Select label="Langue" name="locale" defaultValue={article?.locale ?? "en"} options={locales.map((l) => [l, localeNames[l]] as const)} />
              <Select label="Catégorie" name="category" defaultValue={article?.category ?? "MILI_NEWS"} options={CATEGORIES} />
              <Field label="Auteur affiché" name="authorName" defaultValue={article?.authorName ?? "MILI Team"} />
              <MediaSelect label="Image de couverture" name="coverId" value={article?.coverId} media={media} publicOnly />
            </div>
          </Card>
          <Card title="Référencement">
            <div className="space-y-4">
              <Field label="Adresse (slug)" name="slug" defaultValue={article?.slug} mono help="Laissé vide : calculé depuis le titre." />
              <Field label="Titre SEO" name="seoTitle" defaultValue={article?.seoTitle} maxLength={70} help="Facultatif — 60 caractères environ." />
              <Field label="Description SEO" name="seoDescription" defaultValue={article?.seoDescription} rows={2} maxLength={170} />
            </div>
          </Card>
          <button className="adm-btn w-full">Enregistrer</button>
        </div>
      </form>
      {article && (
        <form action={deleteArticleAction} className="mt-6">
          <input type="hidden" name="id" value={article.id} />
          <Submit className="adm-btn adm-btn-danger adm-btn-sm" confirm="Supprimer définitivement cet article ?">Supprimer l&apos;article</Submit>
        </form>
      )}
    </>
  );
}
