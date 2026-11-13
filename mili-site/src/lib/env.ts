import "server-only";
import { z } from "zod";

/**
 * Server-side environment, validated once on first access.
 * Secrets never leave this module through anything prefixed NEXT_PUBLIC_.
 */
const schema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  DATABASE_URL: z.string().min(1),
  NEXT_PUBLIC_SITE_URL: z.string().url().default("http://localhost:3000"),
  APP_SECRET: z.string().min(32, "APP_SECRET must be at least 32 characters"),
  BETTER_AUTH_SECRET: z.string().min(32, "BETTER_AUTH_SECRET must be at least 32 characters"),
  CRON_SECRET: z.string().min(12).optional(),
  RESEND_API_KEY: z.string().optional(),
  RESEND_WEBHOOK_SECRET: z.string().optional(),
  EMAIL_FROM: z.string().default("MILI <hello@mili.example>"),
  EMAIL_REPLY_TO: z.string().optional(),
  STORAGE_DRIVER: z.enum(["local", "s3"]).default("local"),
  STORAGE_LOCAL_DIR: z.string().default(".storage"),
  S3_ENDPOINT: z.string().optional(),
  S3_REGION: z.string().default("auto"),
  S3_BUCKET: z.string().optional(),
  S3_ACCESS_KEY_ID: z.string().optional(),
  S3_SECRET_ACCESS_KEY: z.string().optional(),
  UPLOAD_MAX_MB: z.coerce.number().positive().default(25),
});

export type Env = z.infer<typeof schema>;

let cached: Env | undefined;

export function env(): Env {
  if (cached) return cached;
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new Error(`Invalid environment configuration — ${issues}`);
  }
  if (parsed.data.NODE_ENV === "production") {
    for (const key of ["APP_SECRET", "BETTER_AUTH_SECRET"] as const) {
      if (parsed.data[key].startsWith("dev-only")) {
        throw new Error(`${key} still has its development value. Generate a real secret before deploying.`);
      }
    }
  }
  cached = parsed.data;
  return cached;
}

export function siteUrl(): string {
  return env().NEXT_PUBLIC_SITE_URL.replace(/\/+$/, "");
}
