import "server-only";
import { betterAuth } from "better-auth";
import { prismaAdapter } from "better-auth/adapters/prisma";
import { nextCookies } from "better-auth/next-js";
import { db } from "./db";
import { env, siteUrl } from "./env";

/**
 * Back-office authentication (better-auth, sessions stored in PostgreSQL).
 * Public sign-up is disabled: administrators are created by the seed script
 * or by a Super Admin from /admin/users.
 */
export const auth = betterAuth({
  baseURL: siteUrl(),
  secret: env().BETTER_AUTH_SECRET,
  database: prismaAdapter(db, { provider: "postgresql" }),
  emailAndPassword: {
    enabled: true,
    disableSignUp: true,
    minPasswordLength: 12,
    maxPasswordLength: 128,
  },
  user: {
    additionalFields: {
      role: { type: "string", required: false, defaultValue: "READ_ONLY", input: false },
      active: { type: "boolean", required: false, defaultValue: true, input: false },
    },
  },
  session: {
    expiresIn: 60 * 60 * 12, // 12 hours
    updateAge: 60 * 60,
  },
  rateLimit: { enabled: true, window: 60, max: 20, storage: "memory" },
  advanced: { cookiePrefix: "milli_admin", useSecureCookies: env().NODE_ENV === "production" },
  plugins: [nextCookies()],
});
