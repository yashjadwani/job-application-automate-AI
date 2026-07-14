"use client";

import { useState } from "react";
import { api, apiDownload } from "@/lib/api";
import { ScoreBadge } from "./ScoreBadge";

type LlmCall = {
  label: string;
  kind: string;
  model: string | null;
  status: string;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
};

function ApiCallsDetails({ id }: { id: string }) {
  const [calls, setCalls] = useState<LlmCall[] | null>(null);

  async function load() {
    if (calls) return;
    try {
      setCalls(await api<LlmCall[]>(`/analyses/${id}/calls`));
    } catch {
      setCalls([]);
    }
  }

  const totalTokens = calls?.reduce((a, c) => a + (c.total_tokens ?? 0), 0) ?? 0;
  const totalCost = calls?.reduce((a, c) => a + Number(c.cost_usd ?? 0), 0) ?? 0;

  return (
    <details onToggle={(e) => (e.target as HTMLDetailsElement).open && load()}>
      <summary className="cursor-pointer text-[14px] text-subtle hover:text-ink transition-colors list-none">
        API calls ›
      </summary>
      <div className="mt-4">
        {!calls && <p className="text-[13px] text-subtle animate-pulse">Loading…</p>}
        {calls?.length === 0 && (
          <p className="text-[13px] text-subtle">No telemetry recorded for this analysis.</p>
        )}
        {calls && calls.length > 0 && (
          <>
            <p className="mb-3 text-[13px] text-subtle">
              {calls.length} calls · {totalTokens.toLocaleString()} tokens
              {totalCost > 0 && <> · ${totalCost.toFixed(4)}</>}
            </p>
            <div className="space-y-1.5">
              {calls.map((c, i) => (
                <div key={i} className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
                  <span className="w-44 shrink-0 font-mono">{c.label}</span>
                  <span className={c.status === "error" ? "text-bad" : "text-subtle"}>
                    {c.status === "error" ? "error" :
                      `${c.total_tokens?.toLocaleString() ?? "—"} tok · ${
                        c.latency_ms != null ? `${(c.latency_ms / 1000).toFixed(1)}s` : "—"}`}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </details>
  );
}

export type Analysis = {
  id: string;
  status: string;
  app_status?: string;
  jd_title: string | null;
  company_name: string | null;
  match_score: number | null;
  ats_score: number | null;
  gaps: string[] | null;
  matched_skills: string[] | null;
  ats_keywords: { present: string[]; missing: string[] } | null;
  employer_research: {
    findings: { category: string; insight: string; sources: string[] }[];
    talking_points: string[];
  } | null;
  rewritten_bullets: Record<string, string[]> | null;
  cover_letter_text: string | null;
  agent_trace?: { agent: string; action: string; detail?: string }[] | null;
  error?: string | null;
};

export function AgentTrace({
  events, live = false,
}: { events: { agent: string; action: string; detail?: string }[]; live?: boolean }) {
  if (!events?.length) return null;
  const shown = live ? events.slice(-5) : events;
  return (
    <ol className={live ? "space-y-1.5" : "space-y-2"}>
      {shown.map((e, i) => (
        <li key={i} className="flex gap-3 text-[13px] leading-relaxed fade-in">
          <span className="w-20 shrink-0 font-medium text-subtle">{e.agent}</span>
          <span>
            {e.action}
            {e.detail && <span className="text-subtle"> — {e.detail}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

function DownloadRow({ id, hasCover }: { id: string; hasCover: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function grab(path: string, filename: string, label: string) {
    setBusy(label);
    setError(null);
    try {
      await apiDownload(path, filename);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <button className="btn-primary" disabled={!!busy}
          onClick={() => grab(`/export/docx/${id}`, "CV_tailored.docx", "docx")}>
          {busy === "docx" ? "Preparing…" : "CV · DOCX"}
        </button>
        <button className="btn-secondary" disabled={!!busy}
          onClick={() => grab(`/export/pdf/${id}`, "CV_tailored.pdf", "pdf")}>
          {busy === "pdf" ? "Preparing…" : "CV · PDF"}
        </button>
        {hasCover && (
          <button className="btn-secondary" disabled={!!busy}
            onClick={() => grab(`/export/cover-pdf/${id}`, "Cover_Letter.pdf", "cover")}>
            {busy === "cover" ? "Preparing…" : "Cover letter · PDF"}
          </button>
        )}
      </div>
      {error && <p className="mt-3 text-[13px] text-bad">{error}</p>}
    </div>
  );
}

export function AnalysisResults({ a }: { a: Analysis }) {
  return (
    <div className="space-y-12">
      {/* Scores — big numbers, no boxes */}
      <div className="flex gap-14">
        <div>
          <div className="text-[44px] font-semibold leading-none">
            <ScoreBadge score={a.match_score} />
          </div>
          <div className="mt-1 text-[13px] text-subtle">Match score</div>
        </div>
        <div>
          <div className="text-[44px] font-semibold leading-none">
            <ScoreBadge score={a.ats_score} />
          </div>
          <div className="mt-1 text-[13px] text-subtle">ATS keywords</div>
        </div>
      </div>

      {/* Matched skills */}
      {a.matched_skills?.length ? (
        <section>
          <h2 className="section-title">Where you're strong</h2>
          <div className="divider mt-3" />
          <div className="mt-4 flex flex-wrap gap-2">
            {a.matched_skills.map((s) => (
              <span key={s} className="rounded-full bg-canvas px-3.5 py-1.5 text-[13px] text-good">
                {s}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {/* Gaps + keywords as quiet chips */}
      {(a.gaps?.length || a.ats_keywords?.missing?.length) && (
        <section>
          <h2 className="section-title">Gaps to be aware of</h2>
          <div className="divider mt-3" />
          <div className="mt-4 flex flex-wrap gap-2">
            {a.gaps?.map((g) => (
              <span key={g} className="rounded-full bg-canvas px-3.5 py-1.5 text-[13px]">{g}</span>
            ))}
            {a.ats_keywords?.missing?.map((k) => (
              <span key={k} className="rounded-full bg-canvas px-3.5 py-1.5 text-[13px] text-warn">
                missing: {k}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Employer insights */}
      {a.employer_research?.findings?.length ? (
        <section>
          <h2 className="section-title">Employer insights</h2>
          <div className="divider mt-3" />
          <ul className="mt-4 space-y-5">
            {a.employer_research.findings.map((f, i) => (
              <li key={i}>
                <div className="text-[12px] uppercase tracking-wide text-subtle">{f.category}</div>
                <p className="mt-1 text-[15px] leading-relaxed">{f.insight}</p>
                <div className="mt-1 flex gap-3">
                  {f.sources.map((s, j) => (
                    <a key={j} href={s} target="_blank" rel="noreferrer"
                       className="text-[13px] text-accent hover:underline truncate max-w-64">
                      {new URL(s).hostname}
                    </a>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {a.employer_research.talking_points?.length > 0 && (
            <>
              <h3 className="mt-8 text-[15px] font-semibold">Talking points</h3>
              <ul className="mt-2 list-disc pl-5 text-[15px] leading-relaxed space-y-1">
                {a.employer_research.talking_points.map((t, i) => <li key={i}>{t}</li>)}
              </ul>
            </>
          )}
        </section>
      ) : null}

      {/* Rewritten bullets */}
      {a.rewritten_bullets && (
        <section>
          <h2 className="section-title">Rewritten bullets</h2>
          <div className="divider mt-3" />
          <div className="mt-4 space-y-6">
            {Object.entries(a.rewritten_bullets).map(([sec, bullets]) => (
              <div key={sec}>
                <ul className="list-disc pl-5 text-[15px] leading-relaxed space-y-1.5">
                  {bullets.map((b, i) => <li key={i}>{b}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Cover letter */}
      {a.cover_letter_text && (
        <section>
          <h2 className="section-title">Cover letter</h2>
          <div className="divider mt-3" />
          <p className="mt-4 whitespace-pre-wrap text-[15px] leading-relaxed">
            {a.cover_letter_text}
          </p>
        </section>
      )}

      {/* Downloads */}
      {a.status === "done" && <DownloadRow id={a.id} hasCover={!!a.cover_letter_text} />}

      {/* What the agents did + what it cost */}
      <div className="space-y-4">
        {a.agent_trace?.length ? (
          <details className="group">
            <summary className="cursor-pointer text-[14px] text-subtle hover:text-ink transition-colors list-none">
              Agent activity ({a.agent_trace.length} steps) ›
            </summary>
            <div className="mt-4">
              <AgentTrace events={a.agent_trace} />
            </div>
          </details>
        ) : null}
        {a.status === "done" && <ApiCallsDetails id={a.id} />}
      </div>
    </div>
  );
}
