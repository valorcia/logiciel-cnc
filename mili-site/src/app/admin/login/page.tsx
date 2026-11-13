import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { currentAdmin } from "@/lib/admin-session";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Connexion" };
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  if (await currentAdmin()) redirect("/admin");
  return (
    <main className="grid min-h-svh place-items-center px-4">
      <div className="w-full max-w-sm">
        <p className="mb-8 text-center text-lg font-semibold tracking-[0.3em]">MILLI</p>
        <LoginForm />
        <p className="mt-6 text-center text-xs text-smoke">Accès réservé à l&apos;équipe MILLI. Les connexions sont journalisées.</p>
      </div>
    </main>
  );
}
