"use client";

import { useFormStatus } from "react-dom";
import type { ReactNode } from "react";

/** Submit button that disables itself while its form is being sent. */
export function Submit({ children, className = "adm-btn", confirm }: { children: ReactNode; className?: string; confirm?: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit" className={className} disabled={pending}
      onClick={confirm ? (e) => { if (!window.confirm(confirm)) e.preventDefault(); } : undefined}
    >
      {pending ? "…" : children}
    </button>
  );
}
