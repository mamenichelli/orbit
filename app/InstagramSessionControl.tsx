"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

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
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/instagram/browser-auth", { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        setState(body as AuthState);
      } else {
        setState(current => ({ ...current, error: body.error ?? "Stato sessione Instagram non disponibile" }));
      }
    } catch {
      setState(current => ({ ...current, error: "Stato sessione Instagram non disponibile" }));
    }
  }, []);

  useEffect(() => {
    const findSettingsModal = () => {
      const dialog = document.querySelector<HTMLElement>('.modal[role="dialog"], section.modal[aria-modal="true"], [role="dialog"]');
      setPortalTarget(dialog);
    };
    findSettingsModal();
    const observer = new MutationObserver(findSettingsModal);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const requestAuth = async () => {
    if (busy || state.requested_at > state.completed_request_at) return;
    setBusy(true);
    setState(current => ({ ...current, error: "" }));
    try {
      const response = await fetch("/api/instagram/browser-auth", {
        method: "POST",
        headers: { "x-orbit-manual": "1" },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error ?? "Rinnovo non richiesto");
      setState(body as AuthState);
    } catch (error) {
      setState(current => ({ ...current, error: error instanceof Error ? error.message : "Rinnovo non richiesto" }));
    } finally {
      setBusy(false);
    }
  };

  if (!portalTarget) return null;

  const pending = state.requested_at > state.completed_request_at;
  const started = pending && state.started_request_at >= state.requested_at;
  const online = state.last_seen > 0 && Date.now() - state.last_seen < 120_000;
  const label = pending ? (started ? "Completa l'accesso in Edge…" : "Richiesta inviata al PC…") : "Rigenera accesso Instagram";
  const status = state.error
    ? state.error
    : pending
      ? "Orbit sta chiedendo al PC dell'agente di aprire Edge e rinnovare la sessione dei Direct → Generali."
      : online
        ? "Collector Direct → Generali collegato e in ascolto."
        : "Usa questo comando quando la sessione browser dei Direct scade. Il collector riprenderà la raccolta dopo il nuovo accesso.";

  return createPortal(
    <div data-orbit-instagram-session-control style={{ marginTop: 18, padding: 16, border: "1px solid #dfe7e1", borderRadius: 14, background: "#f7faf8" }}>
      <strong style={{ display: "block", marginBottom: 4, color: "#123c31" }}>Sessione Direct → Generali</strong>
      <span style={{ display: "block", marginBottom: 12, fontSize: 13, lineHeight: 1.45, color: "#66756e" }}>
        Rinnova la sessione browser usata per leggere tutti i post e reel condivisi nella cartella Generali dei Direct.
      </span>
      <button type="button" className="secondary" onClick={() => void requestAuth()} disabled={busy || pending}
        style={{ width: "100%", minHeight: 44, fontWeight: 800 }}>
        {busy ? "Invio richiesta…" : label}
      </button>
      <span role="status" style={{ display: "block", marginTop: 10, fontSize: 12, lineHeight: 1.4, color: state.error ? "#a33" : "#66756e" }}>
        {status}
      </span>
    </div>,
    portalTarget,
  );
}
