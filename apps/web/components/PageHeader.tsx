import type { ReactNode } from "react";

/** One consistent opening block for every screen: title, quiet subtitle,
 *  optional primary action pinned right. */
export function PageHeader({
  title, subtitle, action,
}: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="mt-2 max-w-xl text-[15px] text-subtle">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

/** Monogram initial for list rows (company / role). */
export function Monogram({ label }: { label: string | null | undefined }) {
  const ch = (label ?? "•").trim().charAt(0).toUpperCase() || "•";
  return <span className="monogram">{ch}</span>;
}
