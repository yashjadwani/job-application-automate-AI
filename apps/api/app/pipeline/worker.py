"""Orchestrator: sequences the agents and advances analyses.status.

With HITL enabled (default):
  phase 1  pending → researching → analysing → writing → awaiting_approval
  (user reviews/edits bullets, then POST /analyses/{id}/approve)
  phase 2  reviewing → done

With HITL disabled, phase 2 runs immediately after phase 1.
The agent trace is persisted on every transition, so a polling client watches
the agents work in real time.
"""

import logging

from supabase import Client

from .. import telegram, telemetry
from ..config import get_settings
from . import guardrails
from .agents import (Trace, ats_agent, cover_letter_agent, match_analyst_agent,
                     research_agent, rewrite_with_critic)

log = logging.getLogger("pipeline")

# Hard cap on LLM calls per analysis (agent loops + critics + retries)
CALL_BUDGET = 25


def _set(client: Client, analysis_id: str, **fields):
    client.table("analyses").update(fields).eq("id", analysis_id).execute()


def _get(client: Client, analysis_id: str) -> dict | None:
    rows = client.table("analyses").select("*").eq("id", analysis_id).execute().data
    return rows[0] if rows else None


def _get_profile(client: Client, user_id: str) -> dict:
    rows = client.table("profiles").select("*").eq("id", user_id).execute().data
    return rows[0] if rows else {}


def _linked_chat(client: Client, user_id: str) -> int | None:
    try:
        rows = (client.table("telegram_links").select("chat_id")
                .eq("user_id", user_id).execute()).data
        return rows[0]["chat_id"] if rows and rows[0]["chat_id"] else None
    except Exception:
        return None


def _notify(client: Client, user_id: str, analysis_id: str,
            notify_chat_id: int | None):
    """Terminal notification (done/failed) + DOCX for bot-initiated runs."""
    chat_id = notify_chat_id or _linked_chat(client, user_id)
    if not (chat_id and telegram.enabled()):
        return
    analysis = _get(client, analysis_id)
    if not analysis:
        return
    telegram.notify_done(chat_id, analysis)
    if analysis["status"] == "done" and notify_chat_id:
        try:
            from ..routers.exports import build_tailored_docx
            docx = build_tailored_docx(client, user_id, analysis)
            company = (analysis.get("company_name") or "tailored").replace(" ", "_")
            telegram.send_document(chat_id, f"CV_{company}.docx", docx,
                                   "Your tailored CV 📄")
        except Exception:
            log.exception("could not send DOCX to telegram")


def run_analysis(client: Client, user_id: str, analysis_id: str, profile: dict,
                 cv: dict, jd_text: str, company: str | None,
                 user_notes: str | None, notify_chat_id: int | None = None):
    """Entry point (unchanged signature). Dispatches to the planner-based
    orchestrator when PLANNER_ENABLED, else runs the original linear pipeline."""
    if get_settings().planner_enabled:
        from .context import AnalysisContext
        from .orchestrator import run as planner_run
        from .registry import build_agent_registry
        ctx = AnalysisContext(user_id=user_id, analysis_id=analysis_id,
                              profile=profile, cv=cv, jd_text=jd_text,
                              company=company, user_notes=user_notes)
        return planner_run(client, ctx, build_agent_registry(), notify_chat_id)
    return _run_linear(client, user_id, analysis_id, profile, cv, jd_text,
                       company, user_notes, notify_chat_id)


def _run_linear(client: Client, user_id: str, analysis_id: str, profile: dict,
                cv: dict, jd_text: str, company: str | None,
                user_notes: str | None, notify_chat_id: int | None = None):
    """Phase 1: research → analyse → rewrite (+guardrails). Pauses for HITL."""
    trace = Trace()

    def step(status: str, **fields):
        _set(client, analysis_id, status=status,
             agent_trace=trace.events, **fields)

    try:
        # Telemetry: every LLM call in this task records to llm_calls
        telemetry.set_context(client, user_id, analysis_id)
        # Guardrails: budget + input sanitisation before any agent runs
        budget = guardrails.set_budget(CALL_BUDGET)
        jd_text, flags = guardrails.sanitize_jd(jd_text)
        trace.add("Guardrail", "input scan",
                  "; ".join(flags) if flags else "clean")
        if user_notes:
            user_notes = user_notes[:guardrails.MAX_NOTES_CHARS]

        # Research agent (skipped when no company given)
        research = None
        if company:
            step("researching")
            try:
                with telemetry.record_stage("research", "researching"):
                    research = research_agent(company, jd_text, trace)
            except guardrails.BudgetExceeded:
                raise
            except Exception:
                log.exception("research agent failed — continuing without it")
                trace.add("Researcher", "failed", "continuing without research")
            step("researching", employer_research=research)

        # Analysis: tool-using analyst + hybrid ATS
        step("analysing")
        with telemetry.record_stage("match", "analysing"):
            match = match_analyst_agent(profile, cv, jd_text, research, trace)
        trace.add("Analyst", "match scored", f"{match['score']}/100")
        with telemetry.record_stage("ats", "analysing"):
            ats = ats_agent(cv, jd_text, trace)
        step("analysing",
             match_score=match["score"],
             match_summary=match["summary"],
             matched_skills=match["matched_skills"],
             gaps=match["gaps"],
             ats_score=ats["ats_score"],
             ats_keywords={"present": ats["present"], "missing": ats["missing"]})

        # Rewrite with critic loop
        step("writing")
        with telemetry.record_stage("rewrite", "writing"):
            bullets = rewrite_with_critic(profile, cv, jd_text, ats["missing"], trace)

        # Output guardrail: deterministic validation, then scrub as last resort
        sections = [s for s in cv.get("sections", []) if s.get("bullets")]
        counts = {s["id"]: len(s["bullets"]) for s in sections}
        violations = guardrails.validate_bullets(bullets, counts)
        if violations:
            trace.add("Guardrail", "output violations",
                      f"{len(violations)}: {violations[0]}")
            bullets = guardrails.scrub_bullets(bullets)
            remaining = guardrails.validate_bullets(bullets, counts)
            if any("expected" in v for v in remaining):
                raise ValueError("Bullet structure invalid after scrub: "
                                 + "; ".join(remaining[:3]))
        else:
            trace.add("Guardrail", "output scan", "clean")
        step("writing", rewritten_bullets=bullets)

        if get_settings().hitl_enabled:
            trace.add("Orchestrator", "paused for approval",
                      f"{budget.used}/{budget.limit} LLM calls so far")
            step("awaiting_approval")
            chat_id = notify_chat_id or _linked_chat(client, user_id)
            if chat_id and telegram.enabled():
                telegram.send_message(
                    chat_id,
                    "✍️ Bullets are ready for review. Approve in the app, or "
                    "reply /approve to continue as-is.")
            return

        _finish(client, user_id, analysis_id, trace, notify_chat_id)
    except Exception as exc:
        log.exception("pipeline failed for analysis %s", analysis_id)
        trace.add("Orchestrator", "failed", str(exc)[:200])
        try:
            step("failed", error=str(exc)[:500])
        except Exception:
            log.exception("could not record failure state")
        _notify(client, user_id, analysis_id, notify_chat_id)


def resume_analysis(client: Client, user_id: str, analysis_id: str,
                    notify_chat_id: int | None = None):
    """Resume after human approval. Dispatches like run_analysis."""
    if get_settings().planner_enabled:
        return _resume_planner(client, user_id, analysis_id, notify_chat_id)
    return _resume_linear(client, user_id, analysis_id, notify_chat_id)


def _resume_planner(client: Client, user_id: str, analysis_id: str,
                    notify_chat_id: int | None = None):
    from .context import AnalysisContext
    from .orchestrator import run as planner_run
    from .registry import build_agent_registry

    row = _get(client, analysis_id)
    if not row or row["status"] != "awaiting_approval":
        log.warning("resume(planner) on %s in state %s", analysis_id,
                    row and row["status"])
        return
    cv = (client.table("cv_structure").select("*")
          .eq("user_id", user_id).execute()).data
    ctx = AnalysisContext(
        user_id=user_id, analysis_id=analysis_id,
        profile=_get_profile(client, user_id), cv=cv[0] if cv else {"sections": []},
        jd_text=row["jd_text"], company=row.get("company_name"),
        user_notes=row.get("user_notes"))
    # Rehydrate shared memory from the persisted row so nothing re-runs
    ctx.trace.events = list(row.get("agent_trace") or [])
    if row.get("employer_research"):
        ctx.data["research"] = row["employer_research"]
    if row.get("match_score") is not None:
        ctx.data["match"] = {"score": row["match_score"],
                             "summary": row.get("match_summary") or "",
                             "matched_skills": row.get("matched_skills") or [],
                             "gaps": row.get("gaps") or []}
    if row.get("ats_score") is not None:
        kw = row.get("ats_keywords") or {}
        ctx.data["ats"] = {"ats_score": row["ats_score"],
                           "present": kw.get("present", []),
                           "missing": kw.get("missing", [])}
    if row.get("rewritten_bullets"):
        ctx.data["rewritten_bullets"] = row["rewritten_bullets"]
    planner_run(client, ctx, build_agent_registry(), notify_chat_id, resume=True)


def _resume_linear(client: Client, user_id: str, analysis_id: str,
                   notify_chat_id: int | None = None):
    """Phase 2 (after approval): cover letter with editor pass → done."""
    telemetry.set_context(client, user_id, analysis_id)
    guardrails.set_budget(10)

    analysis = _get(client, analysis_id)
    if not analysis or analysis["status"] != "awaiting_approval":
        log.warning("resume called on %s in state %s", analysis_id,
                    analysis and analysis["status"])
        return

    trace = Trace()
    trace.events = list(analysis.get("agent_trace") or [])
    trace.add("Orchestrator", "approved", "resuming with cover letter")

    def step(status: str, **fields):
        _set(client, analysis_id, status=status,
             agent_trace=trace.events, **fields)

    try:
        profile = _get_profile(client, user_id)
        research = analysis.get("employer_research") or {}
        step("reviewing")
        with telemetry.record_stage("cover_letter", "reviewing"):
            cover = cover_letter_agent(
                profile, analysis["jd_text"], analysis.get("match_summary") or "",
                research.get("talking_points", []), analysis.get("user_notes"), trace)
        trace.add("Orchestrator", "complete", "all agents finished")
        step("done", cover_letter_text=cover)
    except Exception as exc:
        log.exception("resume failed for analysis %s", analysis_id)
        trace.add("Orchestrator", "failed", str(exc)[:200])
        try:
            step("failed", error=str(exc)[:500])
        except Exception:
            log.exception("could not record failure state")

    _notify(client, user_id, analysis_id, notify_chat_id)


def _finish(client: Client, user_id: str, analysis_id: str, trace: Trace,
            notify_chat_id: int | None):
    """HITL-disabled path: run phase 2 inline on the same trace."""
    analysis = _get(client, analysis_id)
    profile = _get_profile(client, user_id)
    research = (analysis or {}).get("employer_research") or {}

    def step(status: str, **fields):
        _set(client, analysis_id, status=status,
             agent_trace=trace.events, **fields)

    step("reviewing")
    with telemetry.record_stage("cover_letter", "reviewing"):
        cover = cover_letter_agent(
            profile, (analysis or {}).get("jd_text", ""),
            (analysis or {}).get("match_summary") or "",
            research.get("talking_points", []),
            (analysis or {}).get("user_notes"), trace)
    trace.add("Orchestrator", "complete", "all agents finished")
    step("done", cover_letter_text=cover)
    _notify(client, user_id, analysis_id, notify_chat_id)
