import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

/** Locale detection and localised URLs for the public site. */
export default createMiddleware(routing);

export const config = {
  // Everything except the back office, API routes, invitation and media handlers, and static files.
  matcher: ["/((?!admin|api|invite|media|_next|_vercel|.*\\..*).*)"],
};
