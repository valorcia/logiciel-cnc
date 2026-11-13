"use client";

import { useState, useTransition } from "react";
import { unsubscribeAction } from "@/app/actions/public";
import { Link } from "@/i18n/navigation";

type Props = { token: string; labels: { question: string; confirm: string; keep: string; doneTitle: string; doneText: string; error: string } };

export function UnsubscribeForm({ token, labels }: Props) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState(false);
  const [pending, start] = useTransition();

  if (done) {
    return (
      <div role="status">
        <p className="text-xl font-medium text-white">{labels.doneTitle}</p>
        <p className="mt-3">{labels.doneText}</p>
      </div>
    );
  }
  return (
    <div>
      <p>{labels.question}</p>
      <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <button
          type="button" className="btn btn-primary" disabled={pending}
          onClick={() => start(async () => {
            const result = await unsubscribeAction(token).catch(() => ({ ok: false }));
            if (result.ok) setDone(true); else setError(true);
          })}
        >
          {labels.confirm}
        </button>
        <Link href="/" className="btn btn-ghost">{labels.keep}</Link>
      </div>
      {error && <p className="field-error" role="alert">{labels.error}</p>}
    </div>
  );
}
