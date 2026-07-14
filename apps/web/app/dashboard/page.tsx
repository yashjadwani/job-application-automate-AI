"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ScoreBadge } from "@/components/ScoreBadge";
import { Monogram, PageHeader } from "@/components/PageHeader";
import { APP_STATUS_META, StatusSelect, type AppStatus } from "@/components/AppStatus";

type Row = {
  id: string;
  jd_title: string | null;
  company_name: string | null;
  status: string;
  app_status: AppStatus;
  match_score: number | null;
  ats_score: number | null;
  created_at: string;
};

export default function Dashboard() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);
  const [usage, setUsage] = useState<{
    calls: number; total_tokens: number; cost_usd: number | null;
    avg_latency_ms: number | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Row[]>("/analyses").then(setRows).catch((e) => setError(e.message));
    api<{ used: number; limit: number }>("/quota").then(setQuota).catch(() => {});
    api<typeof usage>("/usage").then(setUsage).catch(() => {});
  }, []);

  const avg =
    rows && rows.length
      ? Math.round(
          rows.filter((r) => r.match_score != null)
              .reduce((a, r) => a + (r.match_score ?? 0), 0) /
            Math.max(1, rows.filter((r) => r.match_score != null).length)
        )
      : null;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Your job hunt at a glance."
        action={<Link href="/analyse" className="btn-primary">New Analysis</Link>}
      />

      {/* Summary — plain figures split by hairlines, no cards */}
      <div className="mt-10 flex flex-wrap divide-x divide-hairline fade-in">
        <div className="pr-8 sm:pr-10">
          <div className="text-[28px] font-semibold tabular-nums">{rows?.length ?? "—"}</div>
          <div className="text-[13px] text-subtle">Analyses</div>
        </div>
        <div className="px-8 sm:px-10">
          <div className="text-[28px] font-semibold tabular-nums">{avg ?? "—"}</div>
          <div className="text-[13px] text-subtle">Avg match</div>
        </div>
        {quota && (
          <div className="px-8 sm:px-10">
            <div className="text-[28px] font-semibold tabular-nums">
              {quota.used}<span className="text-subtle text-[18px]"> / {quota.limit}</span>
            </div>
            <div className="text-[13px] text-subtle">This month</div>
          </div>
        )}
        {usage && usage.calls > 0 && (
          <>
            <div className="px-8 sm:px-10">
              <div className="text-[28px] font-semibold tabular-nums">
                {usage.total_tokens >= 1000
                  ? `${(usage.total_tokens / 1000).toFixed(0)}k`
                  : usage.total_tokens}
              </div>
              <div className="text-[13px] text-subtle">
                Tokens · {usage.calls} calls
                {usage.cost_usd ? ` · $${usage.cost_usd.toFixed(2)}` : ""}
              </div>
            </div>
            {usage.avg_latency_ms != null && (
              <div className="px-8 sm:px-10">
                <div className="text-[28px] font-semibold tabular-nums">
                  {(usage.avg_latency_ms / 1000).toFixed(1)}s
                </div>
                <div className="text-[13px] text-subtle">Avg call latency</div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Application pipeline — where every application stands */}
      {rows && rows.length > 0 && (
        <div className="mt-8 flex flex-wrap gap-2">
          {(Object.keys(APP_STATUS_META) as AppStatus[]).map((s) => {
            const n = rows.filter((r) => (r.app_status ?? "not_applied") === s).length;
            if (!n) return null;
            return (
              <span key={s}
                className={`rounded-full bg-canvas px-3.5 py-1.5 text-[13px] font-medium ${APP_STATUS_META[s].cls}`}>
                {APP_STATUS_META[s].label} · {n}
              </span>
            );
          })}
        </div>
      )}

      <div className="mt-12 flex items-baseline justify-between">
        <h2 className="section-title">Recent</h2>
        <Link href="/history" className="text-[14px] text-accent hover:underline">
          View all
        </Link>
      </div>
      <div className="divider mt-3" />

      {error && <p className="mt-6 text-bad text-[14px]">{error}</p>}
      {rows === null && !error && (
        <p className="mt-10 text-subtle text-[15px] animate-pulse">Loading…</p>
      )}
      {rows && rows.length === 0 && (
        <p className="mt-10 text-subtle text-[15px]">
          No analyses yet. Paste your first job description to get started.
        </p>
      )}

      <ul>
        {rows?.slice(0, 8).map((r) => (
          <li key={r.id}>
            <Link
              href={`/history/${r.id}`}
              className="flex items-center justify-between py-4 hover:bg-canvas/60 -mx-3 px-3 rounded-xl transition-colors"
            >
              <div className="flex items-center gap-3.5">
                <Monogram label={r.company_name || r.jd_title} />
                <div>
                  <div className="text-[15px] font-medium">
                    {r.jd_title || r.company_name || "Untitled role"}
                  </div>
                  <div className="text-[13px] text-subtle">
                    {r.company_name} · {new Date(r.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-5 text-[15px]">
                {r.status !== "done" && (
                  <span className={`text-[13px] ${r.status === "awaiting_approval" ? "text-warn" : "text-subtle"}`}>
                    {r.status === "awaiting_approval" ? "needs review" : r.status}
                  </span>
                )}
                {r.status === "done" && (
                  <StatusSelect id={r.id} value={r.app_status ?? "not_applied"} />
                )}
                <ScoreBadge score={r.match_score} />
              </div>
            </Link>
            <div className="divider" />
          </li>
        ))}
      </ul>
    </div>
  );
}
