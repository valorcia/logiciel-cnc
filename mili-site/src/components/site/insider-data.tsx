"use client";

import { useState, useTransition } from "react";
import { deleteMyDataAction, unsubscribeAction } from "@/app/actions/public";

type Props = {
  token: string;
  subscribed: boolean;
  labels: Record<"export" | "unsubscribe" | "unsubscribed" | "delete" | "deleteConfirm" | "deleteYes" | "deleteNo" | "deletedTitle" | "deletedText" | "error", string>;
};

export function InsiderData({ token, subscribed, labels }: Props) {
  const [state, setState] = useState<"idle" | "confirm" | "deleted">("idle");
  const [unsub, setUnsub] = useState(!subscribed);
  const [error, setError] = useState(false);
  const [pending, start] = useTransition();

  if (state === "deleted") {
    return (
      <div role="status">
        <p className="text-xl font-medium text-white">{labels.deletedTitle}</p>
        <p className="mt-2 text-ash">{labels.deletedText}</p>
      </div>
    );
  }
  const run = (fn: () => Promise<{ ok: boolean }>, done: () => void) =>
    start(async () => {
      setError(false);
      const result = await fn().catch(() => ({ ok: false }));
      if (result.ok) done(); else setError(true);
    });

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <a href={`/api/insider/export?t=${encodeURIComponent(token)}`} className="btn btn-ghost btn-sm">{labels.export}</a>
        {unsub ? (
          <span className="inline-flex min-h-10 items-center text-sm text-ash" role="status">{labels.unsubscribed}</span>
        ) : (
          <button type="button" className="btn btn-ghost btn-sm" disabled={pending} onClick={() => run(() => unsubscribeAction(token), () => setUnsub(true))}>{labels.unsubscribe}</button>
        )}
        {state === "idle" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setState("confirm")}>{labels.delete}</button>}
      </div>
      {state === "confirm" && (
        <div className="mt-5 rounded-xl border border-[#ff5d73]/40 p-5" role="alertdialog" aria-label={labels.delete}>
          <p className="text-sm text-white">{labels.deleteConfirm}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" className="btn btn-sm bg-[#ff5d73] text-void" disabled={pending} onClick={() => run(() => deleteMyDataAction(token), () => setState("deleted"))}>{labels.deleteYes}</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setState("idle")}>{labels.deleteNo}</button>
          </div>
        </div>
      )}
      {error && <p className="field-error" role="alert">{labels.error}</p>}
    </div>
  );
}
