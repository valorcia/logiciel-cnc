import type { MetadataRoute } from "next";
import { baseUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/admin", "/api/", "/invite/", "/*/insider/", "/insider/", "/*/confirm", "/confirm", "/*/unsubscribe", "/unsubscribe"] }],
    sitemap: `${baseUrl()}/sitemap.xml`,
    host: baseUrl(),
  };
}
