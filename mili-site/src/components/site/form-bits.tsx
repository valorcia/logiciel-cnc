"use client";

import { useEffect, useState } from "react";
import { issueFormToken } from "@/app/actions/public";
import { readAttribution } from "./attribution";

/** Hidden anti-spam fields: a signed display timestamp and a honeypot no human fills in. */
export function SpamGuard() {
  const [token, setToken] = useState("");
  useEffect(() => {
    let live = true;
    issueFormToken().then((t) => live && setToken(t)).catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return (
    <>
      <input type="hidden" name="ft" value={token} />
      <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label>
          Website
          <input type="text" name="website" tabIndex={-1} autoComplete="off" defaultValue="" />
        </label>
      </div>
    </>
  );
}

/** First-touch UTM parameters, referrer and landing page of this session. */
export function AttributionFields() {
  const [attr, setAttr] = useState<Record<string, string | undefined>>({});
  useEffect(() => setAttr(readAttribution()), []);
  return (
    <>
      {Object.entries(attr).map(([key, value]) => (value ? <input key={key} type="hidden" name={key} value={value} /> : null))}
    </>
  );
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="field-error" role="alert">
      {message}
    </p>
  );
}

export function SuccessMark() {
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16" aria-hidden>
      <circle cx="32" cy="32" r="30" fill="none" stroke="#00D9FF" strokeWidth="2" className="ring-draw" transform="rotate(-90 32 32)" />
      <path d="M20 33l8.5 8.5L45 25" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="check-draw" />
    </svg>
  );
}
