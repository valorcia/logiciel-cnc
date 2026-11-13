import "dotenv/config";
import { randomUUID } from "node:crypto";
import { PrismaPg } from "@prisma/adapter-pg";
import { hashPassword } from "better-auth/crypto";
import { PrismaClient } from "../src/generated/prisma/client";
import { seedDefaults } from "./seed-data";

/**
 * `npm run db:seed` — default content plus the first Super Admin, taken from
 * ADMIN_EMAIL / ADMIN_PASSWORD. Safe to run again: nothing is overwritten.
 */
async function main() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) throw new Error("DATABASE_URL is not set");
  const prisma = new PrismaClient({ adapter: new PrismaPg({ connectionString }) });

  await seedDefaults(prisma);
  console.log("✓ Default content, e-mail templates and sequences are in place.");

  const email = process.env.ADMIN_EMAIL?.trim().toLowerCase();
  const password = process.env.ADMIN_PASSWORD;
  if (!email || !password) {
    console.log("• ADMIN_EMAIL / ADMIN_PASSWORD not set: no administrator created.");
  } else if (password.length < 12) {
    throw new Error("ADMIN_PASSWORD must be at least 12 characters.");
  } else if (await prisma.user.findUnique({ where: { email } })) {
    console.log(`• Administrator ${email} already exists: left untouched.`);
  } else {
    const id = randomUUID();
    await prisma.user.create({
      data: {
        id, email, name: "Super Admin", emailVerified: true, role: "SUPER_ADMIN",
        accounts: { create: { id: randomUUID(), accountId: id, providerId: "credential", password: await hashPassword(password) } },
      },
    });
    console.log(`✓ Super Admin created: ${email}`);
  }
  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
