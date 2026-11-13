"use server";

import { randomUUID } from "node:crypto";
import { hashPassword } from "better-auth/crypto";
import { db } from "@/lib/db";
import { sendToSubscriber } from "@/lib/email/send";
import { eraseSubscriber } from "@/lib/subscribers";
import type { Role } from "@/generated/prisma/client";
import { adminAction, FormError } from "../_lib/guard";
import { bool, httpsUrl, int, localized, optional, str, utcDate } from "../_lib/form";

/* ───────────── Prospects ───────────── */

export async function deleteSubscriberAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("prospects.delete", "/admin/prospects", async ({ log }) => {
    await eraseSubscriber(id);
    // The audit entry keeps no personal data about the erased person.
    await log("subscriber.erased", "Subscriber", id);
  }, "deleted");
}

export async function clearReferralFlagAction(fd: FormData) {
  const id = str(fd, "id");
  const accept = str(fd, "decision") === "accept";
  await adminAction("prospects.delete", `/admin/prospects?flagged=1`, async ({ log }) => {
    if (accept) await db.subscriber.update({ where: { id }, data: { referralFlagged: false, referralFlagNote: null } });
    else await db.subscriber.update({ where: { id }, data: { referredById: null, referralFlagged: false, referralFlagNote: "Rejected by an administrator" } });
    await log(accept ? "referral.accepted" : "referral.rejected", "Subscriber", id);
  });
}

/* ───────────── Inquiries ───────────── */

export async function updateInquiryAction(fd: FormData) {
  const id = str(fd, "id");
  const status = str(fd, "status");
  await adminAction("inquiries.manage", "/admin/inquiries", async ({ admin, log }) => {
    if (!["OPEN", "IN_PROGRESS", "DONE", "REJECTED"].includes(status)) throw new FormError("Statut inconnu.");
    await db.inquiry.update({ where: { id }, data: { status, note: optional(fd, "note"), handledById: admin.id, handledAt: new Date() } });
    await log("inquiry.updated", "Inquiry", id, { status });
  });
}

/* ───────────── Users ───────────── */

const ROLES: Role[] = ["SUPER_ADMIN", "MARKETING_ADMIN", "CONTENT_EDITOR", "READ_ONLY"];

export async function createUserAction(fd: FormData) {
  await adminAction("users.manage", "/admin/users", async ({ log }) => {
    const email = str(fd, "email").toLowerCase();
    const name = str(fd, "name");
    const password = String(fd.get("password") ?? "");
    const role = str(fd, "role") as Role;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !name) throw new FormError("Nom et adresse e-mail valides requis.");
    if (password.length < 12) throw new FormError("Le mot de passe doit contenir au moins 12 caractères.");
    if (!ROLES.includes(role)) throw new FormError("Rôle inconnu.");
    if (await db.user.findUnique({ where: { email } })) throw new FormError("Un compte existe déjà avec cette adresse.");
    const userId = randomUUID();
    const user = await db.user.create({
      data: {
        id: userId, email, name, role, emailVerified: true,
        accounts: { create: { id: randomUUID(), accountId: userId, providerId: "credential", password: await hashPassword(password) } },
      },
    });
    await log("user.created", "User", user.id, { role });
  }, "created");
}

export async function updateUserAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("users.manage", "/admin/users", async ({ admin, log }) => {
    const role = str(fd, "role") as Role;
    const active = bool(fd, "active");
    if (!ROLES.includes(role)) throw new FormError("Rôle inconnu.");
    const target = await db.user.findUnique({ where: { id } });
    if (!target) throw new FormError("Compte introuvable.");
    const losesSuper = target.role === "SUPER_ADMIN" && target.active && (role !== "SUPER_ADMIN" || !active);
    if (losesSuper) {
      const others = await db.user.count({ where: { role: "SUPER_ADMIN", active: true, id: { not: id } } });
      if (others === 0) throw new FormError("Il doit rester au moins un Super Admin actif.");
    }
    if (id === admin.id && !active) throw new FormError("Vous ne pouvez pas désactiver votre propre compte.");
    await db.user.update({ where: { id }, data: { role, active } });
    // A deactivated or downgraded account loses its open sessions immediately.
    if (!active || role !== target.role) await db.session.deleteMany({ where: { userId: id, ...(id === admin.id ? { id: "none" } : {}) } });
    const password = String(fd.get("password") ?? "");
    if (password) {
      if (password.length < 12) throw new FormError("Le mot de passe doit contenir au moins 12 caractères.");
      await db.account.updateMany({ where: { userId: id, providerId: "credential" }, data: { password: await hashPassword(password) } });
      if (id !== admin.id) await db.session.deleteMany({ where: { userId: id } });
      await log("user.password_reset", "User", id);
    }
    await log("user.updated", "User", id, { role, active });
  });
}

/* ───────────── Settings ───────────── */

export async function saveSettingsAction(fd: FormData) {
  await adminAction("settings.edit", "/admin/settings", async ({ log }) => {
    const kickstarterRaw = optional(fd, "kickstarterUrl");
    const kickstarterUrl = httpsUrl(kickstarterRaw);
    if (kickstarterRaw && (!kickstarterUrl || !/(^|\.)kickstarter\.com$/.test(new URL(kickstarterUrl).hostname))) {
      throw new FormError("Le lien Kickstarter doit être une adresse https://www.kickstarter.com/…");
    }
    const priceDollars = int(fd, "plannedPrice", 1499);
    if (priceDollars < 1 || priceDollars > 100000) throw new FormError("Prix invalide.");
    const contactEmail = optional(fd, "contactEmail");
    if (contactEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contactEmail)) throw new FormError("Adresse de contact invalide.");
    const social: Record<string, string> = {};
    for (const key of ["x", "youtube", "instagram", "facebook", "reddit", "tiktok", "discord"]) {
      const raw = optional(fd, `social.${key}`);
      if (!raw) continue;
      const url = httpsUrl(raw);
      if (!url) throw new FormError(`Lien ${key} invalide : il doit commencer par https://`);
      social[key] = url;
    }
    await db.siteSettings.update({
      where: { id: 1 },
      data: {
        launchAt: utcDate(fd, "launchAt"), countdownEnabled: bool(fd, "countdownEnabled"), kickstarterUrl,
        plannedPriceCents: priceDollars * 100, showPlannedPrice: bool(fd, "showPlannedPrice"), leaderboardEnabled: bool(fd, "leaderboardEnabled"),
        contactEmail, legalName: optional(fd, "legalName"), postalAddress: optional(fd, "postalAddress"), socialLinks: social,
      },
    });
    await log("settings.updated", "SiteSettings", "1", { priceDollars, hasLaunchDate: Boolean(utcDate(fd, "launchAt")) });
  });
}

export async function saveRewardAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("settings.edit", "/admin/settings#rewards", async ({ log }) => {
    const threshold = int(fd, "threshold");
    const name = str(fd, "name");
    if (threshold < 1 || !name) throw new FormError("Seuil et nom requis.");
    const data = { threshold, name, description: localized(fd, "description"), active: bool(fd, "active") };
    try {
      if (id) await db.referralReward.update({ where: { id }, data });
      else await db.referralReward.create({ data });
    } catch {
      throw new FormError("Un rang existe déjà pour ce seuil.");
    }
    await log("reward.saved", "ReferralReward", id || null, { threshold });
  });
}

export async function deleteRewardAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("settings.edit", "/admin/settings#rewards", async ({ log }) => {
    await db.referralReward.delete({ where: { id } });
    await log("reward.deleted", "ReferralReward", id);
  }, "deleted");
}

/** Re-sends the confirmation message to a pending subscriber is intentionally absent:
 *  only the person can ask again from the public form, which rotates the token. */
export async function sendTemplateToSubscriberAction(fd: FormData) {
  const id = str(fd, "id");
  await adminAction("emails.send", "/admin/prospects", async ({ log }) => {
    const sub = await db.subscriber.findUnique({ where: { id } });
    if (!sub) throw new FormError("Prospect introuvable.");
    const outcome = await sendToSubscriber(sub, str(fd, "templateKey"), { kind: "AUTOMATION" });
    if (outcome.status === "SKIPPED") throw new FormError(`Envoi refusé : ${outcome.reason}`);
    if (outcome.status === "FAILED") throw new FormError(`Échec de l'envoi : ${outcome.error}`);
    if (outcome.status === "NOT_SENT_NO_PROVIDER") throw new FormError("Non envoyé : aucun fournisseur d'e-mail configuré.");
    await log("email.sent_manually", "Subscriber", id, { template: str(fd, "templateKey") });
  }, "sent");
}
