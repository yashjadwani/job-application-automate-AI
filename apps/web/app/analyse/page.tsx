"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { AgentTrace, AnalysisResults, type Analysis } from "@/components/AnalysisResults";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { PageHeader } from "@/components/PageHeader";

const STAGE_LABEL: Record<string, string> = {
  pending: "Queued…",
  researching: "Research agent is investigating the company…",
  analysing: "Analyst is scoring your match…",
  writing: "Rewriter and critic are working on your bullets…",
  reviewing: "Editor is polishing your cover letter…",
};

const TERMINAL = ["done", "failed", "awaiting_approval"];

export default function AnalysePage() {
  const [jd, setJd] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  function poll(analysisId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const a = await api<Analysis>(`/analyses/${analysisId}`);
        setAnalysis(a);
        if (TERMINAL.includes(a.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch { /* transient poll error — keep polling */ }
    }, 2500);
  }

  async function start() {
    setError(null);
    setAnalysis(null);
    try {
      const { analysis_id } = await api<{ analysis_id: string }>("/analyse", {
        method: "POST",
        body: JSON.stringify({
          jd_text: jd,
          company_name: company || null,
          jd_title: title || null,
          user_notes: notes || null,
        }),
      });
      poll(analysis_id);
      setAnalysis({ id: analysis_id, status: "pending" } as Analysis);
    } catch (e: any) {
      setError(e.message);
    }
  }

  const running = analysis && !TERMINAL.includes(analysis.status);

  return (
    <div>
      <PageHeader
        title="New analysis"
        subtitle="Paste the job description. We research the employer, score your fit, and rewrite your CV for this exact role."
      />

      <div className="mt-10 space-y-3 max-w-2xl">
        <div className="flex gap-3">
          <input className="field" placeholder="Company" value={company}
            onChange={(e) => setCompany(e.target.value)} />
          <input className="field" placeholder="Role title (optional)" value={title}
            onChange={(e) => setTitle(e.target.value)} />
        </div>
        <textarea className="field min-h-56" placeholder="Paste the job description…"
          value={jd} onChange={(e) => setJd(e.target.value)} />
        <textarea className="field min-h-20"
          placeholder="Notes for this application (optional)"
          value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button className="btn-primary" onClick={start}
          disabled={!!running || jd.trim().length < 100}>
          {running ? "Analysing…" : "Analyse"}
        </button>
      </div>

      {error && <p className="mt-6 text-[14px] text-bad">{error}</p>}

      {running && (
        <div className="mt-14">
          <div className="flex items-center gap-3 text-[15px] text-subtle">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            {STAGE_LABEL[analysis!.status] ?? analysis!.status}
          </div>
          {analysis?.agent_trace?.length ? (
            <div className="mt-6 border-l-2 border-hairline pl-5">
              <AgentTrace events={analysis.agent_trace} live />
            </div>
          ) : null}
        </div>
      )}

      {analysis?.status === "awaiting_approval" && analysis.rewritten_bullets && (
        <div className="mt-14">
          <ApprovalPanel
            analysisId={analysis.id}
            bullets={analysis.rewritten_bullets}
            onApproved={() => {
              setAnalysis({ ...analysis, status: "reviewing" });
              poll(analysis.id);
            }}
          />
        </div>
      )}

      {analysis?.status === "failed" && (
        <p className="mt-10 text-[15px] text-bad">
          Analysis failed{analysis.error ? `: ${analysis.error}` : ""}. Try again.
        </p>
      )}

      {analysis?.status === "done" && (
        <div className="mt-14 fade-in">
          <AnalysisResults a={analysis} />
        </div>
      )}
    </div>
  );
}
