"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export type AppStatus = "not_applied" | "applied" | "interviewing" | "offer" | "rejected";

export const APP_STATUS_META: Record<AppStatus, { label: string; cls: string }> = {
  not_applied: { label: "Not applied", cls: "text-subtle" },
  applied: { label: "Applied", cls: "text-accent" },
  interviewing: { label: "Interviewing", cls: "text-warn" },
  offer: { label: "Offer 🎉", cls: "text-good" },
  rejected: { label: "Rejected", cls: "text-subtle line-through" },
};

const ORDER: AppStatus[] = ["not_applied", "applied", "interviewing", "offer", "rejected"];

/** Quiet inline dropdown — looks like a status label until you interact. */
export function StatusSelect({
  id, value, onChange,
}: { id: string; value: AppStatus; onChange?: (s: AppStatus) => void }) {
  const [current, setCurrent] = useState<AppStatus>(value ?? "not_applied");
  const [busy, setBusy] = useState(false);

  async function update(next: AppStatus) {
    const prev = current;
    setCurrent(next);
    setBusy(true);
    try {
      await api(`/analyses/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ app_status: next }),
      });
      onChange?.(next);
    } catch {
      setCurrent(prev); // revert on failure
    } finally {
      setBusy(false);
    }
  }

  return (
    <select
      value={current}
      disabled={busy}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => update(e.target.value as AppStatus)}
      className={`cursor-pointer appearance-none bg-transparent text-[13px] font-medium
                  outline-none disabled:opacity-50 ${APP_STATUS_META[current].cls}`}
    >
      {ORDER.map((s) => (
        <option key={s} value={s}>{APP_STATUS_META[s].label}</option>
      ))}
    </select>
  );
}
