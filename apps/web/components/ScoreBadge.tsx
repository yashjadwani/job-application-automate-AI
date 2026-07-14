export function ScoreBadge({ score }: { score: number | null }) {
  if (score == null) return <span className="text-subtle">—</span>;
  const color = score >= 70 ? "text-good" : score >= 45 ? "text-warn" : "text-bad";
  return <span className={`font-semibold tabular-nums ${color}`}>{score}</span>;
}
