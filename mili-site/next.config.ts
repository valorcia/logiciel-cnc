import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** Video providers whose players may be embedded (adaptive streaming, loaded on demand). */
const FRAME_SOURCES = [
  "https://www.youtube-nocookie.com",
  "https://player.vimeo.com",
  "https://iframe.mediadelivery.net",
  "https://iframe.videodelivery.net",
  "https://*.cloudflarestream.com",
  "https://player.mux.com",
].join(" ");

const csp = [
  "default-src 'self'",
  // Next.js injects inline bootstrap scripts; a nonce-based policy would force every page to render dynamically.
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://i.ytimg.com https://i.vimeocdn.com https://image.mux.com",
  "media-src 'self' https:",
  "font-src 'self' data:",
  `frame-src ${FRAME_SOURCES}`,
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), browsing-topics=()" },
];

const nextConfig: NextConfig = {
  // The site uses the classic caching model (ISR + on-demand revalidation):
  // next-intl's static rendering is documented for it, not yet for Cache Components.
  cacheComponents: false,
  poweredByHeader: false,
  experimental: {
    // Vercel caps a function's request body at 4.5 MB; uploads are validated below that.
    serverActions: { bodySizeLimit: "5mb" },
  },
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      { source: "/admin/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
    ];
  },
};

export default withNextIntl(nextConfig);
