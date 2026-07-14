"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ScoreBadge } from "@/components/ScoreBadge";
import { Monogram, PageHeader } from "@/components/PageHeader";
import { StatusSelect, type AppStatus } from "@/components/AppStatus";

type Row = {
  id: string;
  jd_title: string | null;
  company_name: string | null;
  status: string;
  app_status: AppStatus;
  match_score: number | null;
  created_at: string;
};

export default function HistoryPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Row[]>("/analyses").then(setRows).catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <PageHeader
        title="History"
        subtitle={rows ? `${rows.length} ${rows.length === 1 ? "analysis" : "analyses"} to date.` : undefined}
      />
      {error && <p className="mt-6 text-[14px] text-bad">{error}</p>}
      {rows?.length === 0 && (
        <p className="mt-10 text-[15px] text-subtle">Nothing here yet.</p>
      )}
      <ul className="mt-8">
        {rows?.map((r) => (
          <li key={r.id}>
            <Link href={`/history/${r.id}`}
              className="flex items-center justify-between py-4 -mx-3 px-3 rounded-xl hover:bg-canvas/60 transition-colors">
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
              <div className="flex items-center gap-5">
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
