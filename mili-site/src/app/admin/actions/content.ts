"use server";

import { db } from "@/lib/db";
import { checkUpload, IMAGE_FILE_TYPES } from "@/lib/files";
import { isLocale } from "@/lib/i18n/config";
import { flatMessages } from "@/lib/i18n/messages";
import { createId } from "@/lib/ids";
import { can } from "@/lib/permissions";
import { maxUploadBytes, storage } from "@/lib/storage";
import { parseVideoUrl } from "@/lib/video";
import type { ArticleCategory, ChallengeCategory, ProofCategory, PublishStatus } from "@/generated/prisma/client";
import { adminAction, FormError } from "../_lib/guard";
import { bool, int, localized, optional, optionalInt, str, utcDate } from "../_lib/form";

const STATUSES: PublishStatus[] = ["DRAFT", "SCHEDULED", "PUBLISHED", "ARCHIVED"];
const publishStatus = (fd: FormData, publishAt: Date | null): PublishStatus => {
  const status = str(fd, "status") as PublishStatus;
  if (!STATUSES.includes(status)) throw new FormError("Statut inconnu.");
  if (status === "SCHEDULED" && !publishAt) throw new FormError("Un contenu programmé a besoin d'une date de publication.");
  return status;
};
const videoUrl = (fd: FormData, required: boolean): string | null => {
  const raw = optional(fd, "videoUrl");
  if (!raw) {
    if (required) throw new FormError("Le lien de la vidéo est requis.");
    return null;
  }
  if (!parseVideoUrl(raw)) throw new FormError("Lien vidéo non reconnu. Hébergeurs acceptés : YouTube, Vimeo, Bunny Stream, Cloudflare Stream, Mux, ou un fichier .mp4/.webm en https.");
  return raw;
};

/* ───────────── Site copy overrides ───────────── */

export async function saveOverridesAction(fd: FormData) {
  const locale = str(fd, "locale");
  const namespace = str(fd, "namespace");
  await adminAction("content.edit", `/admin/content?ns=${namespace}&locale=${locale}`, async ({ log }) => {
    if (!isLocale(locale)) throw new FormError("Langue inconnue.");
    const defaults = await flatMessages(locale);
    let changed = 0;
    for (const [key, base] of Object.entries(defaults)) {
      if (!key.startsWith(`${namespace}.`)) continue;
      const field = fd.get(`v:${key}`);
      if (typeof field !== "string") continue;
      const value = field.replace(/\r\n/g, "\n").trim();
      if (!value || value === base) {
        const removed = await db.contentOverride.deleteMany({ where: { key, locale } });
        changed += removed.count;
        continue;
      }
      // ICU placeholders ({price}, {count, plural, …}) must survive the edit, or the page would break.
      const names = (text: string) => [...text.matchAll(/\{\s*(\w+)/g)].map((m) => m[1]).sort().join(",");
      if (names(value) !== names(base)) throw new FormError(`« ${key} » : les variables entre accolades du texte d'origine doivent être conservées telles quelles.`);
      await db.contentOverride.upsert({ where: { key_locale: { key, locale } }, create: { key, locale, value }, update: { value } });
      changed++;
    }
    await log("content.overrides_saved", "ContentOverride", null, { namespace, locale, changed });
  });
}

/* ───────────── Clues ───────────── */

export async function saveClueAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("clues.edit", "/admin/clues", async ({ log }) => {
    const number = int(fd, "number");
    const publishAt = utcDate(fd, "publishAt");
    const title = localized(fd, "title");
    if (number < 1 || !title.en) throw new FormError("Numéro et titre anglais requis.");
    const data = { number, title, content: localized(fd, "content"), imageId: optional(fd, "imageId"), videoUrl: videoUrl(fd, false), publishAt, status: publishStatus(fd, publishAt) };
    try {
      const saved = id ? await db.clue.update({ where: { id }, data }) : await db.clue.create({ data });
      await log("clue.saved", "Clue", saved.id, { number, status: data.status });
    } catch (err) {
      if (err instanceof FormError) throw err;
      throw new FormError("Un indice porte déjà ce numéro.");
    }
  });
}

export async function deleteClueAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("clues.edit", "/admin/clues", async ({ log }) => {
    await db.clue.delete({ where: { id } });
    await log("clue.deleted", "Clue", id);
  }, "deleted");
}

/* ───────────── Proof videos ───────────── */

const PROOF: ProofCategory[] = ["PRECISION", "COMPLEX_GEOMETRY", "FIVE_AXIS", "SURFACE_FINISH", "MATERIALS"];

export async function saveProofAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("proof.edit", "/admin/proof", async ({ admin, log }) => {
    const title = localized(fd, "title");
    const category = str(fd, "category") as ProofCategory;
    if (!title.en || !PROOF.includes(category)) throw new FormError("Titre anglais et catégorie requis.");
    const existing = id ? await db.proofVideo.findUnique({ where: { id } }) : null;
    const url = videoUrl(fd, true)!;
    const status = publishStatus(fd, null);
    // Only a Super Admin can certify that the footage shows the MILLI prototype and that what it claims is true.
    const mayValidate = can(admin.role, "proof.validate");
    const wantsValidated = mayValidate ? bool(fd, "validated") : (existing?.validated ?? false);
    // Changing the footage voids an earlier validation.
    const validated = existing && existing.videoUrl !== url && !mayValidate ? false : wantsValidated;
    if (status === "PUBLISHED" && !validated) throw new FormError("Une vidéo ne peut être publiée qu'après validation technique par un Super Admin.");
    const data = {
      title, description: localized(fd, "description"), category, videoUrl: url, posterId: optional(fd, "posterId"),
      durationSec: optionalInt(fd, "durationSec"), recordedAt: utcDate(fd, "recordedAt"), sortOrder: int(fd, "sortOrder"), status, validated,
      ...(validated && !existing?.validated ? { validatedById: admin.id, validatedAt: new Date() } : {}),
      ...(!validated ? { validatedById: null, validatedAt: null } : {}),
    };
    const saved = id ? await db.proofVideo.update({ where: { id }, data }) : await db.proofVideo.create({ data });
    await log("proof.saved", "ProofVideo", saved.id, { status, validated });
  });
}

export async function deleteProofAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("proof.edit", "/admin/proof", async ({ log }) => {
    await db.proofVideo.delete({ where: { id } });
    await log("proof.deleted", "ProofVideo", id);
  }, "deleted");
}

/* ───────────── Challenges ───────────── */

const CHALLENGE: ChallengeCategory[] = ["ART_DESIGN", "ENGINEERING", "ROBOTICS", "AUTOMOTIVE", "AEROSPACE", "JEWELRY", "EDUCATION", "OTHER"];

export async function moderateChallengeAction(fd: FormData) {
  const id = str(fd, "id");
  const decision = str(fd, "decision");
  await adminAction("challenges.moderate", `/admin/challenges${str(fd, "back")}`, async ({ admin, log }) => {
    if (decision === "delete") {
      const row = await db.challenge.findUnique({ where: { id }, select: { fileKey: true } });
      if (row?.fileKey) await storage().delete(row.fileKey).catch(() => {});
      await db.challenge.delete({ where: { id } });
      await log("challenge.deleted", "Challenge", id);
      return;
    }
    if (decision === "reject") {
      await db.challenge.update({ where: { id }, data: { status: "REJECTED", moderatedById: admin.id, moderatedAt: new Date() } });
      await log("challenge.rejected", "Challenge", id);
      return;
    }
    const publicTitle = str(fd, "publicTitle");
    const category = str(fd, "category") as ChallengeCategory;
    if (!publicTitle) throw new FormError("Un titre public est requis pour publier un défi.");
    if (!CHALLENGE.includes(category)) throw new FormError("Catégorie inconnue.");
    await db.challenge.update({
      where: { id },
      data: {
        status: "APPROVED", publicTitle: publicTitle.slice(0, 120), publicDescription: str(fd, "publicDescription").slice(0, 400),
        displayName: str(fd, "displayName").slice(0, 40), category, moderatedById: admin.id, moderatedAt: new Date(),
      },
    });
    await log("challenge.approved", "Challenge", id);
  });
}

/* ───────────── FAQ ───────────── */

export async function saveFaqAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("content.edit", "/admin/faq", async ({ log }) => {
    const question = localized(fd, "question");
    const answer = localized(fd, "answer");
    const scope = str(fd, "scope");
    if (!question.en || !answer.en) throw new FormError("Question et réponse en anglais requises.");
    if (!["MYSTERY", "REVEAL", "BOTH"].includes(scope)) throw new FormError("Portée inconnue.");
    const data = { question, answer, scope, sortOrder: int(fd, "sortOrder"), published: bool(fd, "published") };
    const saved = id ? await db.faq.update({ where: { id }, data }) : await db.faq.create({ data });
    await log("faq.saved", "Faq", saved.id, { scope });
  });
}

export async function deleteFaqAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("content.edit", "/admin/faq", async ({ log }) => {
    await db.faq.delete({ where: { id } });
    await log("faq.deleted", "Faq", id);
  }, "deleted");
}

/* ───────────── Journal ───────────── */

const ARTICLE: ArticleCategory[] = ["CNC_TECHNOLOGY", "FIVE_AXIS_MACHINING", "MAKER_PROJECTS", "ENGINEERING", "MILLI_NEWS"];
const slugify = (text: string) => text.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);

export async function saveArticleAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("journal.edit", id ? `/admin/journal/${id}` : "/admin/journal/new", async ({ log }) => {
    const title = str(fd, "title");
    const locale = str(fd, "locale");
    const category = str(fd, "category") as ArticleCategory;
    const slug = slugify(str(fd, "slug") || title);
    const publishAt = utcDate(fd, "publishAt");
    if (!title || !slug) throw new FormError("Titre requis.");
    if (!isLocale(locale) || !ARTICLE.includes(category)) throw new FormError("Langue ou catégorie inconnue.");
    const status = publishStatus(fd, publishAt);
    const body = str(fd, "body");
    if (status !== "DRAFT" && (!body || !str(fd, "excerpt"))) throw new FormError("Un article publié ou programmé a besoin d'un résumé et d'un contenu.");
    const data = {
      locale, slug, title, excerpt: str(fd, "excerpt").slice(0, 300), body, category, coverId: optional(fd, "coverId"),
      authorName: str(fd, "authorName") || "MILLI Team", seoTitle: optional(fd, "seoTitle"), seoDescription: optional(fd, "seoDescription"), status, publishAt,
    };
    try {
      const saved = id ? await db.article.update({ where: { id }, data }) : await db.article.create({ data });
      await log("article.saved", "Article", saved.id, { status, locale });
      return `/admin/journal/${saved.id}`;
    } catch {
      throw new FormError("Un article utilise déjà cette adresse (slug) dans cette langue.");
    }
  });
}

export async function deleteArticleAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("journal.edit", "/admin/journal", async ({ log }) => {
    await db.article.delete({ where: { id } });
    await log("article.deleted", "Article", id);
  }, "deleted");
}

/* ───────────── Media library ───────────── */

const PLACEMENTS = ["GALLERY", "HERO_IMAGE", "CLUE", "POSTER", "ARTICLE", "OTHER"];

export async function uploadMediaAction(fd: FormData) {
  await adminAction("media.manage", "/admin/media", async ({ admin, log }) => {
    const file = fd.get("file");
    if (!(file instanceof File) || file.size === 0) throw new FormError("Choisissez un fichier image.");
    if (file.size > maxUploadBytes()) throw new FormError(`Fichier trop lourd (${Math.floor(maxUploadBytes() / 1024 / 1024)} Mo maximum).`);
    const bytes = new Uint8Array(await file.arrayBuffer());
    const check = checkUpload(bytes, file.name, IMAGE_FILE_TYPES, maxUploadBytes());
    if (!check.ok) throw new FormError("Format refusé : seules les images JPG, PNG et WebP sont acceptées, et le contenu doit correspondre à l'extension.");
    const placement = str(fd, "placement");
    if (!PLACEMENTS.includes(placement)) throw new FormError("Emplacement inconnu.");
    // Anything that could show the machine is confidential unless explicitly marked public.
    const visibility = str(fd, "visibility") === "PUBLIC" ? "PUBLIC" : "REVEAL_ONLY";
    const key = `media/${createId()}.${check.file.ext}`;
    await storage().put(key, bytes, check.file.mime);
    const asset = await db.mediaAsset.create({
      data: { storageKey: key, fileName: check.safeName, mime: check.file.mime, size: bytes.length, alt: localized(fd, "alt"), visibility, placement, sortOrder: int(fd, "sortOrder"), uploadedById: admin.id },
    });
    await log("media.uploaded", "MediaAsset", asset.id, { visibility, placement });
  }, "created");
}

export async function updateMediaAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("media.manage", "/admin/media", async ({ log }) => {
    const placement = str(fd, "placement");
    if (!PLACEMENTS.includes(placement)) throw new FormError("Emplacement inconnu.");
    const visibility = str(fd, "visibility") === "PUBLIC" ? "PUBLIC" : "REVEAL_ONLY";
    await db.mediaAsset.update({ where: { id }, data: { alt: localized(fd, "alt"), visibility, placement, sortOrder: int(fd, "sortOrder") } });
    await log("media.updated", "MediaAsset", id, { visibility, placement });
  });
}

export async function deleteMediaAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("media.manage", "/admin/media", async ({ log }) => {
    const asset = await db.mediaAsset.findUnique({ where: { id } });
    if (!asset) return;
    await db.mediaAsset.delete({ where: { id } });
    await storage().delete(asset.storageKey).catch(() => {});
    await log("media.deleted", "MediaAsset", id);
  }, "deleted");
}

