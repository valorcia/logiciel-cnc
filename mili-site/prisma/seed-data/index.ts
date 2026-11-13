import type { PrismaClient } from "../../src/generated/prisma/client";
import { clueSeeds, faqSeeds, pledgeSeeds, rewardSeeds, sectionSeeds } from "./content";
import { emailSteps, emailTemplates } from "./emails";

/**
 * Idempotent defaults: creates what is missing, never overwrites what an
 * administrator has edited.
 */
export async function seedDefaults(prisma: PrismaClient, now = new Date()): Promise<void> {
  await prisma.siteSettings.upsert({ where: { id: 1 }, update: {}, create: { id: 1 } });

  for (const t of emailTemplates) {
    await prisma.emailTemplate.upsert({
      where: { key_locale: { key: t.key, locale: t.locale } },
      update: {},
      create: t,
    });
  }
  for (const s of emailSteps) {
    await prisma.emailStep.upsert({
      where: { series_templateKey: { series: s.series, templateKey: s.templateKey } },
      update: {},
      create: s,
    });
  }
  for (const c of clueSeeds(now)) {
    await prisma.clue.upsert({ where: { number: c.number }, update: {}, create: c });
  }
  if ((await prisma.faq.count()) === 0) await prisma.faq.createMany({ data: faqSeeds });
  for (const r of rewardSeeds) {
    await prisma.referralReward.upsert({ where: { threshold: r.threshold }, update: {}, create: r });
  }
  if ((await prisma.pledgeTier.count()) === 0) await prisma.pledgeTier.createMany({ data: pledgeSeeds });
  for (const s of sectionSeeds) {
    await prisma.productSection.upsert({ where: { key: s.key }, update: {}, create: { ...s, body: {} } });
  }
}
