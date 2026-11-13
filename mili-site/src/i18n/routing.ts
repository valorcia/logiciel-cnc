import { defineRouting } from "next-intl/routing";
import { defaultLocale, locales } from "@/lib/i18n/config";

/** English (US) lives at the root; other languages get a prefix: /fr, /de, /es, /ja. */
export const routing = defineRouting({
  locales,
  defaultLocale,
  localePrefix: "as-needed",
});
