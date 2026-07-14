"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { AnalysisResults, type Analysis } from "@/components/AnalysisResults";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { StatusSelect, type AppStatus } from "@/components/AppStatus";

export default function AnalysisDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [a, setA] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Analysis>(`/analyses/${id}`).then(setA).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="text-[14px] text-bad">{error}</p>;
  if (!a) return <p className="text-[15px] text-subtle animate-pulse">Loading…</p>;

  return (
    <div className="fade-in">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="page-title">{a.jd_title || a.company_name || "Analysis"}</h1>
        {a.status === "done" && (
          <StatusSelect id={a.id} value={(a.app_status ?? "not_applied") as AppStatus} />
        )}
      </div>
      {a.company_name && <p className="mt-1 text-[15px] text-subtle">{a.company_name}</p>}
      {a.status === "awaiting_approval" && a.rewritten_bullets && (
        <div className="mt-10">
          <ApprovalPanel
            analysisId={a.id}
            bullets={a.rewritten_bullets}
            onApproved={() => setA({ ...a, status: "reviewing" })}
          />
        </div>
      )}
      {!["done", "failed", "awaiting_approval"].includes(a.status) && (
        <p className="mt-6 text-[15px] text-subtle">
          Still running ({a.status}) — refresh to check progress.
        </p>
      )}
      {a.status === "failed" && (
        <p className="mt-6 text-[15px] text-bad">This analysis failed. Run it again from Analyse.</p>
      )}
      <div className="mt-12">
        <AnalysisResults a={a} />
      </div>
    </div>
  );
}
