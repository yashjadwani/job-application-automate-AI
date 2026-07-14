"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Sections = { id: string; title: string }[];

export function ApprovalPanel({
  analysisId, bullets, onApproved,
}: {
  analysisId: string;
  bullets: Record<string, string[]>;
  onApproved: () => void;
}) {
  const [edited, setEdited] = useState<Record<string, string[]>>(bullets);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Map section ids to real titles from the stored CV (fallback: the id)
    api<{ cv: { sections: Sections } | null }>("/profile")
      .then(({ cv }) => {
        const map: Record<string, string> = {};
        cv?.sections?.forEach((s) => (map[s.id] = s.title));
        setTitles(map);
      })
      .catch(() => {});
  }, []);

  function setBullet(sec: string, i: number, text: string) {
    setEdited((prev) => {
      const next = { ...prev, [sec]: [...prev[sec]] };
      next[sec][i] = text;
      return next;
    });
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await api(`/analyses/${analysisId}/approve`, {
        method: "POST",
        body: JSON.stringify({ rewritten_bullets: edited }),
      });
      onApproved();
    } catch (e: any) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="fade-in">
      <h2 className="section-title">Review your rewritten bullets</h2>
      <p className="mt-2 text-[15px] text-subtle">
        Edit anything that doesn't sound like you, then approve — the cover
        letter is written from what you approve.
      </p>

      <div className="mt-8 space-y-8">
        {Object.entries(edited).map(([sec, items]) => (
          <section key={sec}>
            <h3 className="text-[15px] font-semibold">{titles[sec] ?? sec}</h3>
            <div className="divider mt-2" />
            <ul className="mt-3 space-y-1.5">
              {items.map((b, i) => (
                <li key={i}>
                  <textarea
                    className="w-full resize-none rounded-lg px-2 py-1.5 text-[14px] leading-relaxed
                               hover:bg-canvas focus:bg-canvas outline-none transition-colors"
                    rows={2}
                    value={b}
                    onChange={(e) => setBullet(sec, i, e.target.value)}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="mt-8 flex items-center gap-4">
        <button className="btn-primary" onClick={approve} disabled={busy}>
          {busy ? "Continuing…" : "Approve & write cover letter"}
        </button>
        {error && <span className="text-[14px] text-bad">{error}</span>}
      </div>
    </div>
  );
}
