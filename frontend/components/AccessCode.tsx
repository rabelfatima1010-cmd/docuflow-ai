"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getAccessCode, setAccessCode, type Health } from "@/lib/api";

/** Server health + whether this browser holds a working access code. */
export function useAccess() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unlocked, setUnlocked] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth(h);
      if (!h.access_code_required) return setUnlocked(true);
      const saved = getAccessCode();
      setUnlocked(saved ? await api.checkAccessCode(saved) : false);
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { health, unlocked, refresh, needsCode: !!health?.access_code_required && !unlocked };
}

export function AccessCodeForm({ onUnlocked, compact = false }: { onUnlocked: () => void; compact?: boolean }) {
  const [code, setCode] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = code.trim();
    if (!value) return;
    setChecking(true);
    setError(null);
    try {
      if (await api.checkAccessCode(value)) {
        setAccessCode(value);
        onUnlocked();
      } else {
        setError("That code isn't right. Check it and try again.");
      }
    } catch {
      setError("Couldn't check the code. Try again in a moment.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <form onSubmit={submit} className={compact ? "space-y-2" : "card space-y-3 p-6 text-center"}>
      {!compact && (
        <>
          <div className="text-2xl" aria-hidden>
            🔒
          </div>
          <div className="font-semibold">Enter the access code to try it with your own invoices</div>
          <div className="text-sm muted">
            Anyone can browse the sample invoices below. Uploading uses real AI, so it needs the code the owner shared
            with you.
          </div>
        </>
      )}
      {compact && <div className="text-sm muted">Enter the access code to approve, reject or re-run documents.</div>}
      <div className={`flex gap-2 ${compact ? "" : "mx-auto max-w-sm"}`}>
        <input
          className="input"
          placeholder="Access code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          aria-label="Access code"
          autoComplete="off"
        />
        <button className="btn btn-primary" disabled={checking || !code.trim()}>
          {checking ? "Checking…" : "Unlock"}
        </button>
      </div>
      {error && (
        <div className="text-sm" style={{ color: "var(--bad)" }}>
          {error}
        </div>
      )}
    </form>
  );
}
