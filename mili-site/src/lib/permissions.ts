import type { Role } from "@/generated/prisma/client";

/** Every protected capability of the back office. */
export const permissions = [
  "dashboard.view",
  "prospects.view",
  "prospects.export",
  "prospects.delete",
  "content.edit",
  "clues.edit",
  "proof.edit",
  "proof.validate",
  "challenges.moderate",
  "journal.edit",
  "emails.edit",
  "emails.send",
  "product.edit",
  "product.validate",
  "media.manage",
  "inquiries.manage",
  "settings.edit",
  "reveal.switch",
  "users.manage",
  "audit.view",
] as const;

export type Permission = (typeof permissions)[number];

const marketing: Permission[] = [
  "dashboard.view", "prospects.view", "prospects.export", "prospects.delete", "content.edit", "clues.edit",
  "proof.edit", "challenges.moderate", "journal.edit", "emails.edit", "emails.send", "product.edit",
  "media.manage", "inquiries.manage", "settings.edit", "audit.view",
];

const editor: Permission[] = [
  "dashboard.view", "content.edit", "clues.edit", "proof.edit", "journal.edit", "product.edit", "media.manage",
];

const matrix: Record<Role, ReadonlySet<Permission>> = {
  SUPER_ADMIN: new Set(permissions),
  MARKETING_ADMIN: new Set(marketing),
  CONTENT_EDITOR: new Set(editor),
  READ_ONLY: new Set<Permission>(["dashboard.view"]),
};

export function can(role: Role, permission: Permission): boolean {
  return matrix[role].has(permission);
}

export const roleLabels: Record<Role, string> = {
  SUPER_ADMIN: "Super Admin",
  MARKETING_ADMIN: "Marketing Admin",
  CONTENT_EDITOR: "Content Editor",
  READ_ONLY: "Read Only",
};
