"use client";

import { useCallback, useEffect, useState } from "react";

type AuthState = {
  requested_at: number;
  started_request_at: number;
  completed_request_at: number;
  last_seen: number;
  error: string;
};

const emptyState: AuthState = {
  requested_at: 0,
  started_request_at: 0,
  completed_request_at: 0,
  last_seen: 0,
  error: "",
};

export default function InstagramSessionControl() {
  const [state, setState] = useState<AuthState>(emptyState);
  const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/instagram/browser-auth", { cache: "no-store" });
      if (response.status === 401) { setVisible(false); return; }
      const body = await response.json();
      if (response.ok) setState(body as AuthState);
    } catch {
      // Keep the control visible: a queued request can still be retried later.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const requestAuth = async () => {
    if (busy || state.requested_at > state.completed_request_at) return;
    setBusy(true);
    try {
      const response = await fetch("/api/instagram/browser-auth", {
        method: "POST",
        headers: { "x-orbit-manual": "1" },
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Rinnovo non richiesto");
      setState(body as AuthState);
    } catch (error) {
      setState(current => ({ ...current, error: error instanceof Error ? error.message : "Rinnovo non richiesto" }));
    } finally {
      setBusy(false);
    }
  };

  if (!visible) return null;
  const pending = state.requested_at > state.completed_request_at;
  const started = pending && state.started_request_at >= state.requested_at;
  const online = state.last_seen > 0 && Date.now() - state.last_seen < 120_000;
  const label = pending ? (started ? "Completa l'accesso in Edge…" : "Richiesta inviata al PC…") : "Rigenera accesso Instagram";
  const status = state.error
    ? state.error
    : pending
      ? "Orbit sta aprendo Edge sul PC per rinnovare la sessione dei Direct → Generali."
      : online
        ? "Collector Direct → Generali collegato."
        : "Se la sessione è scaduta, premi il pulsante: il collector riaprirà Edge e riprenderà la raccolta.";

  return (
    <aside data-orbit-instagram-session-control style={{ position: "fixed", right: 20, bottom: 20, zIndex: 1000, width: 330, padding: 14, borderRadius: 16,
      background: "rgba(17,24,39,.96)", color: "white", boxShadow: "0 18px 50px rgba(0,0,0,.28)", fontFamily: "inherit" }}>
      <div style={{ marginBottom: 9, fontSize: 11, fontWeight: 800, letterSpacing: ".08em", color: "#f4c95d" }}>DIRECT → GENERALI</div>
      <button type="button" onClick={() => void requestAuth()} disabled={busy || pending}
        style={{ width: "100%", border: 0, borderRadius: 12, padding: "12px 14px", cursor: busy || pending ? "default" : "pointer",
          fontWeight: 800, background: pending ? "#374151" : "#f4c95d", color: pending ? "#fff" : "#111827" }}>
        {busy ? "Invio richiesta…" : label}
      </button>
      <div style={{ marginTop: 9, fontSize: 12, lineHeight: 1.35, color: state.error ? "#fecaca" : "#d1d5db" }}>{status}</div>
    </aside>
  );
}
