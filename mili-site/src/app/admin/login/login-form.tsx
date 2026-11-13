"use client";

import { useActionState } from "react";
import { loginAction, type LoginState } from "./actions";

const initial: LoginState = {};

export function LoginForm() {
  const [state, action, pending] = useActionState(loginAction, initial);
  return (
    <form action={action} className="adm-card space-y-5">
      <div>
        <label htmlFor="email" className="field-label">Adresse e-mail</label>
        <input id="email" name="email" type="email" required autoComplete="username" className="field" />
      </div>
      <div>
        <label htmlFor="password" className="field-label">Mot de passe</label>
        <input id="password" name="password" type="password" required autoComplete="current-password" className="field" />
      </div>
      {state.error && <p role="alert" className="field-error">{state.error}</p>}
      <button type="submit" className="adm-btn w-full" disabled={pending}>{pending ? "Connexion…" : "Se connecter"}</button>
    </form>
  );
}
