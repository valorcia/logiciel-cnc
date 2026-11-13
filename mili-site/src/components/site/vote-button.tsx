"use client";

import { useState, useTransition } from "react";
import { voteAction } from "@/app/actions/public";

type Props = { id: string; votes: number; labels: { vote: string; voted: string; errors: Record<string, string> } };

export function VoteButton({ id, votes, labels }: Props) {
  const [count, setCount] = useState(votes);
  const [voted, setVoted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const vote = () =>
    start(async () => {
      setError(null);
      const result = await voteAction(id).catch(() => ({ ok: false as const, code: "generic" as const, votes: undefined }));
      if (result.ok) {
        setCount(result.votes ?? count + 1);
        setVoted(true);
      } else if (result.code === "alreadyVoted") {
        setVoted(true);
      } else {
        setError(labels.errors[result.code ?? "generic"] ?? labels.errors.generic);
      }
    });

  return (
    <div>
      <button
        type="button" onClick={vote} disabled={pending || voted} aria-pressed={voted}
        className={`inline-flex min-h-11 items-center gap-2.5 rounded-full border px-4 text-sm font-medium transition ${voted ? "border-cyan text-cyan" : "border-line text-white hover:border-white"} disabled:cursor-default`}
      >
        <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden><path d="M8 3l5 6H3z" fill="currentColor" /></svg>
        <span>{voted ? labels.voted : labels.vote}</span>
        <span className="font-mono tabular-nums text-ash" aria-live="polite">{count}</span>
      </button>
      {error && <p className="field-error" role="alert">{error}</p>}
    </div>
  );
}
