/** Environment shared by the test runner and its global setup. Never points at a real database. */
export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? "postgresql://postgres@127.0.0.1:5433/mili_test";

export function applyTestEnv(): void {
  Object.assign(process.env, {
    NODE_ENV: "test",
    DATABASE_URL: TEST_DATABASE_URL,
    NEXT_PUBLIC_SITE_URL: "https://milli.test",
    APP_SECRET: "test-app-secret-0123456789abcdef0123456789",
    BETTER_AUTH_SECRET: "test-auth-secret-0123456789abcdef0123456789",
    CRON_SECRET: "test-cron-secret",
    STORAGE_DRIVER: "local",
    STORAGE_LOCAL_DIR: ".storage-test",
  });
  delete process.env.RESEND_API_KEY;
}
