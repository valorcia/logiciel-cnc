import "server-only";
import { db } from "./db";
import { pickText } from "./i18n/config";
import { getSettings } from "./settings";
import { parseVideoUrl, type VideoSource } from "./video";

/* ───────────── Clues ───────────── */

export type PublicClue = {
  number: number;
  unlocked: boolean;
  publishAt: string | null;
  /** Present only when unlocked: locked clues never leave the server. */
  title?: string;
  content?: string;
  imageId?: string | null;
  video?: VideoSource | null;
};

export async function publicClues(locale: string, now = new Date()): Promise<PublicClue[]> {
  const clues = await db.clue.findMany({
    where: { status: { in: ["PUBLISHED", "SCHEDULED"] } },
    orderBy: { number: "asc" },
    include: { image: { select: { id: true, visibility: true } } },
  });
  return clues.map((clue) => {
    const due = !clue.publishAt || clue.publishAt.getTime() <= now.getTime();
    const unlocked = due && (clue.status === "PUBLISHED" || Boolean(clue.publishAt));
    if (!unlocked) return { number: clue.number, unlocked: false, publishAt: clue.publishAt?.toISOString() ?? null };
    return {
      number: clue.number,
      unlocked: true,
      publishAt: clue.publishAt?.toISOString() ?? null,
      title: pickText(clue.title, locale),
      content: pickText(clue.content, locale),
      imageId: clue.image?.visibility === "PUBLIC" ? clue.image.id : null,
      video: clue.videoUrl ? parseVideoUrl(clue.videoUrl) : null,
    };
  });
}

/* ───────────── Proof ───────────── */

export type PublicProof = {
  id: string;
  title: string;
  description: string;
  category: string;
  video: VideoSource;
  posterId: string | null;
  duration: number | null;
  recordedAt: string | null;
};

/** Only demonstrations that are both published and technically validated. */
export async function publicProofVideos(locale: string): Promise<PublicProof[]> {
  const rows = await db.proofVideo.findMany({
    where: { status: "PUBLISHED", validated: true },
    orderBy: [{ sortOrder: "asc" }, { recordedAt: "desc" }],
    include: { poster: { select: { id: true, visibility: true } } },
  });
  const out: PublicProof[] = [];
  for (const row of rows) {
    const video = parseVideoUrl(row.videoUrl);
    if (!video) continue;
    out.push({
      id: row.id,
      title: pickText(row.title, locale),
      description: pickText(row.description, locale),
      category: row.category,
      video,
      posterId: row.poster?.visibility === "PUBLIC" ? row.poster.id : null,
      duration: row.durationSec,
      recordedAt: row.recordedAt?.toISOString() ?? null,
    });
  }
  return out;
}

/* ───────────── Challenges ───────────── */

export type PublicChallenge = { id: string; title: string; description: string; displayName: string; category: string; votes: number };

/** Moderated fields only — never the raw submission, the e-mail or the file. */
export async function approvedChallenges(limit?: number): Promise<PublicChallenge[]> {
  const rows = await db.challenge.findMany({
    where: { status: "APPROVED", publicTitle: { not: null } },
    orderBy: [{ voteCount: "desc" }, { moderatedAt: "desc" }],
    take: limit,
    select: { id: true, publicTitle: true, publicDescription: true, displayName: true, category: true, voteCount: true },
  });
  return rows.map((r) => ({
    id: r.id,
    title: r.publicTitle ?? "",
    description: r.publicDescription ?? "",
    displayName: r.displayName ?? "",
    category: r.category,
    votes: r.voteCount,
  }));
}

/* ───────────── FAQ ───────────── */

export type PublicFaq = { id: string; question: string; answer: string };

export async function publicFaqs(locale: string, mode: "MYSTERY" | "REVEAL"): Promise<PublicFaq[]> {
  const rows = await db.faq.findMany({
    where: { published: true, scope: { in: [mode, "BOTH"] } },
    orderBy: { sortOrder: "asc" },
  });
  return rows
    .map((r) => ({ id: r.id, question: pickText(r.question, locale), answer: pickText(r.answer, locale) }))
    .filter((f) => f.question && f.answer);
}

/* ───────────── Journal ───────────── */

const livePredicate = (now: Date) => ({
  OR: [
    { status: "PUBLISHED" as const, OR: [{ publishAt: null }, { publishAt: { lte: now } }] },
    { status: "SCHEDULED" as const, publishAt: { lte: now } },
  ],
});

export async function publishedArticles(locale: string, category?: string, now = new Date()) {
  return db.article.findMany({
    where: { locale, ...(category ? { category: category as never } : {}), ...livePredicate(now) },
    orderBy: [{ publishAt: "desc" }, { createdAt: "desc" }],
    select: { id: true, slug: true, title: true, excerpt: true, category: true, publishAt: true, createdAt: true, authorName: true, coverId: true },
  });
}

export async function publishedArticle(locale: string, slug: string, now = new Date()) {
  return db.article.findFirst({ where: { locale, slug, ...livePredicate(now) } });
}

/* ───────────── Reveal-only product content ───────────── */

export type RevealContent = {
  sections: { key: string; title: string; body: string }[];
  specs: { group: string; rows: { label: string; value: string }[] }[];
  kit: { name: string; description: string; quantity: string | null }[];
  tiers: { id: string; name: string; priceCents: number; description: string; conditions: string; quantityLimit: number | null }[];
  gallery: { id: string; alt: string }[];
  heroImageId: string | null;
  filmUrl: VideoSource | null;
};

/**
 * Everything the product page needs. Returns null while the site is in
 * Mystery mode — unless `preview` is set by a caller that has already
 * authenticated an administrator.
 */
export async function revealContent(locale: string, opts: { preview?: boolean } = {}): Promise<RevealContent | null> {
  const settings = await getSettings();
  if (!opts.preview && settings.mode !== "REVEAL") return null;

  const [sections, specs, kit, tiers, media] = await Promise.all([
    db.productSection.findMany({ where: opts.preview ? {} : { published: true }, orderBy: { sortOrder: "asc" } }),
    db.productSpec.findMany({ where: { validated: true }, orderBy: { sortOrder: "asc" } }),
    db.kitItem.findMany({ orderBy: { sortOrder: "asc" } }),
    db.pledgeTier.findMany({ where: { active: true }, orderBy: { sortOrder: "asc" } }),
    db.mediaAsset.findMany({ where: { placement: { in: ["GALLERY", "HERO_IMAGE"] } }, orderBy: { sortOrder: "asc" } }),
  ]);

  const groups = new Map<string, { label: string; value: string }[]>();
  for (const spec of specs) {
    const group = pickText(spec.groupName, locale);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push({ label: pickText(spec.label, locale), value: pickText(spec.value, locale) });
  }

  return {
    sections: sections
      .map((s) => ({ key: s.key, title: pickText(s.title, locale), body: pickText(s.body, locale) }))
      .filter((s) => s.body.trim()),
    specs: [...groups.entries()].map(([group, rows]) => ({ group, rows })),
    kit: kit.map((k) => ({ name: pickText(k.name, locale), description: pickText(k.description, locale), quantity: k.quantity })),
    tiers: tiers.map((t) => ({
      id: t.id, name: t.name, priceCents: t.priceCents, description: pickText(t.description, locale),
      conditions: pickText(t.conditions, locale), quantityLimit: t.quantityLimit,
    })),
    gallery: media.filter((m) => m.placement === "GALLERY").map((m) => ({ id: m.id, alt: pickText(m.alt, locale) })),
    heroImageId: media.find((m) => m.placement === "HERO_IMAGE")?.id ?? null,
    filmUrl: settings.filmUrl ? parseVideoUrl(settings.filmUrl) : null,
  };
}
