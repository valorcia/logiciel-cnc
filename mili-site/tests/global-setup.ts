import { execSync } from "node:child_process";
import { TEST_DATABASE_URL } from "./env";

/** Brings the test database up to the current migrations before any test runs. */
export default function setup(): void {
  execSync("npx prisma migrate deploy", {
    env: { ...process.env, DATABASE_URL: TEST_DATABASE_URL },
    stdio: "pipe",
  });
}
