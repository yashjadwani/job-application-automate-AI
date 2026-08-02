"""Event-driven orchestrator for the planner-based agent system.

Loop:  plan → pop next agent → run (with recovery) → update shared memory →
       evaluate (revision loop / HITL pause / done).

Guarantees preserved from the linear pipeline:
  - identical analyses.status values → the frontend polling UI is unchanged,
  - HITL pause before the cover letter (deterministic, not left to the planner),
  - the same DB columns are written,
  - Telegram notifications,
  - deterministic output validation on the bullets,
  - the per-analysis LLM call budget + telemetry.

Never crashes the whole run: optional agents that fail are skipped; essential
failures fail the analysis cleanly (status=failed) with the error recorded.
"""

import logging
import time
from collections import deque

from supabase import Client

from .. import telegram, telemetry
from ..config import get_settings
from . import guardrails, planner
from .context import AnalysisContext
from .registry import AgentRegistry, AgentSpec

log = logging.getLogger("orchestrator")

CALL_BUDGET = 25


# ---------------------------------------------------------------------------
# Persistence — map shared memory → analyses columns (same schema as linear)
# ---------------------------------------------------------------------------
def _persist(client: Client, ctx: AnalysisContext, status: str,
             error: str | None = None):
    d = ctx.data
    fields: dict = {"status": status, "agent_trace": ctx.trace.events}
    if error:
        fields["error"] = error
    if "research" in d and d["research"] is not None:
        fields["employer_research"] = d["research"]
    if "match" in d:
        m = d["match"]
        fields["match_score"] = max(0, min(100, int(m["score"])))
        fields["match_summary"] = m.get("summary")
        fields["matched_skills"] = m["matched_skills"]
        fields["gaps"] = m["gaps"]
    if "ats" in d:
        a = d["ats"]
        fields["ats_score"] = max(0, min(100, int(a["ats_score"])))
        fields["ats_keywords"] = {"present": a["present"], "missing": a["missing"]}
    if "rewritten_bullets" in d:
        fields["rewritten_bullets"] = d["rewritten_bullets"]
    if "cover_letter" in d:
        fields["cover_letter_text"] = d["cover_letter"]
    client.table("analyses").update(fields).eq("id", ctx.analysis_id).execute()


def _get(client: Client, analysis_id: str) -> dict | None:
    rows = client.table("analyses").select("*").eq("id", analysis_id).execute().data
    return rows[0] if rows else None


def _linked_chat(client: Client, user_id: str) -> int | None:
    try:
        rows = (client.table("telegram_links").select("chat_id")
                .eq("user_id", user_id).execute()).data
        return rows[0]["chat_id"] if rows and rows[0]["chat_id"] else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Agent execution with recovery
# ---------------------------------------------------------------------------
def _run_agent(ctx: AnalysisContext, spec: AgentSpec) -> bool:
    attempts = get_settings().planner_max_retries + 1
    for i in range(attempts):
        t0 = time.perf_counter()
        try:
            with telemetry.record_stage(spec.name, spec.status):
                spec.run(ctx)
            ctx.trace.add(spec.name, "done", f"{int((time.perf_counter() - t0) * 1000)}ms")
            return True
        except guardrails.BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — recovery is the point
            ctx.errors[spec.name] = str(exc)[:200]
            ctx.retries[spec.name] = ctx.retries.get(spec.name, 0) + 1
            ctx.trace.add(spec.name, f"error (try {i + 1}/{attempts})", str(exc)[:80])
    if spec.optional:
        telemetry.record_skip(spec.name, spec.status, "optional agent failed — continuing")
        ctx.trace.add(spec.name, "skipped", "optional agent failed — continuing")
    return False


def _finalize_bullets(ctx: AnalysisContext):
    """Deterministic output validation before bullets are exposed/exported."""
    if not ctx.has("rewritten_bullets") or not ctx.has("ats"):
        return
    counts = {s["id"]: len(s["bullets"]) for s in ctx.sections()}
    violations = guardrails.validate_bullets(ctx.data["rewritten_bullets"], counts)
    if violations:
        ctx.trace.add("Guardrail", "output violations", f"{len(violations)}: {violations[0]}")
        ctx.data["rewritten_bullets"] = guardrails.scrub_bullets(ctx.data["rewritten_bullets"])
    else:
        ctx.trace.add("Guardrail", "output scan", "clean")


def _derive_completed(ctx: AnalysisContext, registry: AgentRegistry):
    """On resume, mark agents whose outputs already exist so nothing re-runs."""
    for spec in registry.all():
        if spec.produces and all(ctx.has(k) for k in spec.produces):
            if spec.name not in ctx.completed:
                ctx.completed.append(spec.name)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def run(client: Client, ctx: AnalysisContext, registry: AgentRegistry,
        notify_chat_id: int | None = None, resume: bool = False):
    from .. import telemetry
    telemetry.set_context(client, ctx.user_id, ctx.analysis_id)
    guardrails.set_budget(CALL_BUDGET)
    ctx.approved = resume

    if "jd_safe" not in ctx.data:
        safe, flags = guardrails.sanitize_jd(ctx.jd_text)
        ctx.data["jd_safe"] = safe
        ctx.trace.add("Guardrail", "input scan", "; ".join(flags) if flags else "clean")

    _derive_completed(ctx, registry)

    try:
        plan, reasoning = planner.make_plan(ctx, registry)
        ctx.trace.add("Planner", "plan",
                      f"{' → '.join(plan)}  |  {reasoning[:100]}")
        _execute(client, ctx, registry, deque(plan), notify_chat_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("orchestrator failed for %s", ctx.analysis_id)
        ctx.trace.add("Orchestrator", "failed", str(exc)[:200])
        try:
            _persist(client, ctx, status="failed", error=str(exc)[:500])
        except Exception:
            log.exception("could not record failure state")
        _notify(client, ctx, notify_chat_id)


def _execute(client, ctx, registry, queue, notify_chat_id):
    settings = get_settings()
    while queue:
        name = queue.popleft()
        spec = registry.get(name)
        if not spec:
            continue
        if name in ctx.completed and not spec.repeatable:
            continue

        # HITL gate — approval is mandatory before the cover letter
        if (name == "cover_letter" and settings.hitl_enabled and not ctx.approved
                and ctx.has("rewritten_bullets")):
            _finalize_bullets(ctx)
            ctx.trace.add("Planner", "paused for approval",
                          "awaiting human review of rewritten bullets")
            _persist(client, ctx, status="awaiting_approval")
            _pause_notify(client, ctx, notify_chat_id)
            return

        _persist(client, ctx, status=spec.status)
        ok = _run_agent(ctx, spec)
        if name not in ctx.completed:
            ctx.completed.append(name)
        _persist(client, ctx, status=spec.status)

        if not ok and not spec.optional:
            raise RuntimeError(f"essential agent '{name}' failed: "
                               f"{ctx.errors.get(name)}")

        # rewrite ↔ critic revision loop (the planner-driven "run agent again")
        if name == "critic" and ok:
            crit = ctx.data.get("critique") or {}
            if (not crit.get("approved") and crit.get("issues")
                    and ctx.retries.get("_rev", 0) < settings.planner_max_revisions):
                ctx.retries["_rev"] = ctx.retries.get("_rev", 0) + 1
                for a in ("rewrite", "critic"):
                    if a in ctx.completed:
                        ctx.completed.remove(a)
                ctx.trace.add("Planner", "revision",
                              f"round {ctx.retries['_rev']}: {crit['issues'][0][:60]}")
                queue.appendleft("critic")
                queue.appendleft("rewrite")

    _finalize_bullets(ctx)
    ctx.trace.add("Orchestrator", "complete",
                  f"{len(ctx.completed)} agents run")
    _persist(client, ctx, status="done")
    _notify(client, ctx, notify_chat_id)


# ---------------------------------------------------------------------------
# Notifications (mirror the linear worker's behaviour)
# ---------------------------------------------------------------------------
def _pause_notify(client, ctx, notify_chat_id):
    chat_id = notify_chat_id or _linked_chat(client, ctx.user_id)
    if chat_id and telegram.enabled():
        telegram.send_message(chat_id, "✍️ Bullets are ready for review. Approve "
                                       "in the app, or reply /approve to continue.")


def _notify(client, ctx, notify_chat_id):
    chat_id = notify_chat_id or _linked_chat(client, ctx.user_id)
    if not (chat_id and telegram.enabled()):
        return
    analysis = _get(client, ctx.analysis_id)
    if not analysis:
        return
    telegram.notify_done(chat_id, analysis)
    if analysis["status"] == "done" and notify_chat_id:
        try:
            from ..routers.exports import build_tailored_docx
            docx = build_tailored_docx(client, ctx.user_id, analysis)
            company = (analysis.get("company_name") or "tailored").replace(" ", "_")
            telegram.send_document(chat_id, f"CV_{company}.docx", docx,
                                   "Your tailored CV 📄")
        except Exception:
            log.exception("could not send DOCX to telegram")
