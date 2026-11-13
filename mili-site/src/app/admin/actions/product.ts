"use server";

import { revalidatePath } from "next/cache";
import { db } from "@/lib/db";
import { can } from "@/lib/permissions";
import { parseVideoUrl } from "@/lib/video";
import { adminAction, FormError } from "../_lib/guard";
import { bool, int, localized, optional, optionalInt, str } from "../_lib/form";

const BACK = "/admin/product";

export async function saveSectionAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("product.edit", `${BACK}#sections`, async ({ log }) => {
    const title = localized(fd, "title");
    if (!title.en) throw new FormError("Titre anglais requis.");
    const body = localized(fd, "body");
    const published = bool(fd, "published");
    if (published && !body.en) throw new FormError("Une section publiée a besoin d'un texte en anglais.");
    await db.productSection.update({ where: { id }, data: { title, body, published, sortOrder: int(fd, "sortOrder") } });
    await log("product.section_saved", "ProductSection", id, { published });
  });
}

export async function saveSpecAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("product.edit", `${BACK}#specs`, async ({ admin, log }) => {
    const label = localized(fd, "label");
    const value = localized(fd, "value");
    if (!label.en || !value.en) throw new FormError("Intitulé et valeur en anglais requis.");
    const existing = id ? await db.productSpec.findUnique({ where: { id } }) : null;
    const mayValidate = can(admin.role, "product.validate");
    // A figure edited by someone who cannot validate goes back to "unvalidated": it leaves the public table.
    const changed = existing && JSON.stringify(existing.value) !== JSON.stringify(value);
    const validated = mayValidate ? bool(fd, "validated") : changed ? false : (existing?.validated ?? false);
    const data = {
      groupName: localized(fd, "groupName"), label, value, sortOrder: int(fd, "sortOrder"), validated,
      ...(validated && !existing?.validated ? { validatedById: admin.id, validatedAt: new Date() } : {}),
      ...(!validated ? { validatedById: null, validatedAt: null } : {}),
    };
    const saved = id ? await db.productSpec.update({ where: { id }, data }) : await db.productSpec.create({ data });
    await log("product.spec_saved", "ProductSpec", saved.id, { validated });
  });
}

export async function saveKitItemAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("product.edit", `${BACK}#kit`, async ({ log }) => {
    const name = localized(fd, "name");
    if (!name.en) throw new FormError("Nom anglais requis.");
    const data = { name, description: localized(fd, "description"), quantity: optional(fd, "quantity"), sortOrder: int(fd, "sortOrder") };
    const saved = id ? await db.kitItem.update({ where: { id }, data }) : await db.kitItem.create({ data });
    await log("product.kit_saved", "KitItem", saved.id);
  });
}

export async function saveTierAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("product.edit", `${BACK}#tiers`, async ({ admin, log }) => {
    const name = str(fd, "name");
    const price = int(fd, "price");
    if (!name || price < 1) throw new FormError("Nom et prix requis.");
    const existing = id ? await db.pledgeTier.findUnique({ where: { id } }) : null;
    // Prices are a commercial commitment: only a Super Admin can make a reward visible.
    const mayActivate = can(admin.role, "product.validate");
    const active = mayActivate ? bool(fd, "active") : existing && existing.priceCents === price * 100 ? existing.active : false;
    const data = { name, priceCents: price * 100, description: localized(fd, "description"), conditions: localized(fd, "conditions"), quantityLimit: optionalInt(fd, "quantityLimit"), active, sortOrder: int(fd, "sortOrder") };
    const saved = id ? await db.pledgeTier.update({ where: { id }, data }) : await db.pledgeTier.create({ data });
    await log("product.tier_saved", "PledgeTier", saved.id, { price, active });
  });
}

export async function deleteProductRowAction(fd: FormData) {
  const id = str(fd, "id");
  const kind = str(fd, "kind");
  await adminAction("product.edit", `${BACK}#${kind}`, async ({ log }) => {
    if (kind === "specs") await db.productSpec.delete({ where: { id } });
    else if (kind === "kit") await db.kitItem.delete({ where: { id } });
    else if (kind === "tiers") await db.pledgeTier.delete({ where: { id } });
    else throw new FormError("Type inconnu.");
    await log("product.row_deleted", kind, id);
  }, "deleted");
}

export async function saveFilmAction(fd: FormData) {
  await adminAction("product.edit", `${BACK}#film`, async ({ log }) => {
    const url = optional(fd, "filmUrl");
    if (url && !parseVideoUrl(url)) throw new FormError("Lien vidéo non reconnu (YouTube, Vimeo, Bunny Stream, Cloudflare Stream, Mux ou fichier .mp4/.webm en https).");
    await db.siteSettings.update({ where: { id: 1 }, data: { filmUrl: url } });
    await log("product.film_saved", "SiteSettings", "1", { hasFilm: Boolean(url) });
  });
}

/* ───────────── Mystery → Reveal ───────────── */

/**
 * The reveal is one atomic change: a single row flips, inside a transaction
 * that also writes the audit entry. Every confidential loader reads that row,
 * so nothing is half-published. The public cache is purged right after.
 */
export async function switchModeAction(fd: FormData) {
  const target = str(fd, "target") === "REVEAL" ? "REVEAL" : "MYSTERY";
  await adminAction("reveal.switch", "/admin/reveal", async ({ admin }) => {
    if (str(fd, "confirmation") !== target) throw new FormError(`Pour confirmer, saisissez exactement ${target}.`);
    if (!bool(fd, "understood")) throw new FormError("Cochez la case de confirmation.");
    const current = await db.siteSettings.findUniqueOrThrow({ where: { id: 1 } });
    if (current.mode === target) throw new FormError(`Le site est déjà en mode ${target}.`);
    if (target === "REVEAL") {
      const sections = await db.productSection.count({ where: { published: true } });
      if (sections === 0) throw new FormError("Aucune section de la fiche produit n'est publiée : la page serait vide. Publiez au moins une section.");
    }
    await db.$transaction([
      db.siteSettings.update({
        where: { id: 1 },
        data: target === "REVEAL" ? { mode: "REVEAL", revealedAt: new Date(), revealedById: admin.id } : { mode: "MYSTERY", revealedAt: null, revealedById: null },
      }),
      db.auditLog.create({
        data: { actorId: admin.id, actorEmail: admin.email, action: target === "REVEAL" ? "site.revealed" : "site.back_to_mystery", entity: "SiteSettings", entityId: "1", meta: {} },
      }),
    ]);
    revalidatePath("/", "layout");
    revalidatePath("/sitemap.xml");
  });
}
