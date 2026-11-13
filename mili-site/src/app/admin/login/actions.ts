"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { audit } from "@/lib/audit";
import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { rateLimit } from "@/lib/rate-limit";
import { requestMeta } from "@/lib/request";

export type LoginState = { error?: string; email?: string };

export async function loginAction(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const meta = await requestMeta();
  // Ten attempts per network and five per account every fifteen minutes.
  const [byNetwork, byAccount] = await Promise.all([
    rateLimit(`login:${meta.ipHash}`, 10, 900),
    rateLimit(`login-account:${email.slice(0, 120)}`, 5, 900),
  ]);
  if (!byNetwork.allowed || !byAccount.allowed) return { error: "Trop de tentatives. Réessayez dans quinze minutes.", email };

  const generic = { error: "Adresse e-mail ou mot de passe incorrect.", email };
  if (!email || !password) return generic;
  const user = await db.user.findUnique({ where: { email } });
  if (!user || !user.active) {
    await audit(null, "auth.login_failed", "User", user?.id ?? null, {});
    return generic;
  }
  try {
    await auth.api.signInEmail({ body: { email, password }, headers: await headers() });
  } catch {
    await audit(null, "auth.login_failed", "User", user.id, {});
    return generic;
  }
  await audit({ id: user.id, email: user.email }, "auth.login", "User", user.id, {});
  redirect("/admin");
}

export async function logoutAction(): Promise<void> {
  await auth.api.signOut({ headers: await headers() }).catch(() => {});
  redirect("/admin/login");
}
