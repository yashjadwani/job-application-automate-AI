from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..auth import AuthedUser, CurrentUser
from ..config import get_settings
from ..db import user_client
from ..pipeline.guardrails import validate_bullets
from ..pipeline.worker import resume_analysis, run_analysis

router = APIRouter(tags=["analyse"])


class AnalyseIn(BaseModel):
    jd_text: str
    company_name: str | None = None
    jd_title: str | None = None
    user_notes: str | None = None


@router.post("/analyse")
def start_analysis(body: AnalyseIn, tasks: BackgroundTasks,
                   user: AuthedUser = CurrentUser):
    if len(body.jd_text.strip()) < 100:
        raise HTTPException(400, "Job description looks too short to analyse")

    client = user_client(user.token)

    # Quota: count this calendar month's analyses (PRD §5.5)
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    used = (client.table("analyses").select("id", count="exact")
            .eq("user_id", user.user_id).gte("created_at", month_start)
            .execute()).count or 0
    quota = get_settings().monthly_analysis_quota
    if used >= quota:
        raise HTTPException(429, f"Monthly quota reached ({quota} analyses). "
                                 "Resets on the 1st.")

    # Need profile + CV before analysing
    prof = client.table("profiles").select("*").eq("id", user.user_id).execute()
    cv = client.table("cv_structure").select("*").eq("user_id", user.user_id).execute()
    if not cv.data:
        raise HTTPException(409, "Upload a CV before running an analysis")
    profile = prof.data[0] if prof.data else {}

    row = (client.table("analyses").insert({
        "user_id": user.user_id,
        "jd_text": body.jd_text,
        "jd_title": body.jd_title,
        "company_name": body.company_name,
        "user_notes": body.user_notes,
        "status": "pending",
    }).execute()).data[0]

    tasks.add_task(run_analysis, client, user.user_id, row["id"], profile,
                   cv.data[0], body.jd_text, body.company_name, body.user_notes)
    return {"analysis_id": row["id"], "status": "pending"}


@router.get("/quota")
def get_quota(user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    used = (client.table("analyses").select("id", count="exact")
            .eq("user_id", user.user_id).gte("created_at", month_start)
            .execute()).count or 0
    return {"used": used, "limit": get_settings().monthly_analysis_quota}


@router.get("/usage")
def get_usage(user: AuthedUser = CurrentUser):
    """This month's LLM telemetry, aggregated."""
    client = user_client(user.token)
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = (client.table("llm_calls")
            .select("label, status, latency_ms, total_tokens, cost_usd")
            .eq("user_id", user.user_id).gte("created_at", month_start)
            .execute()).data

    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
    by_label: dict[str, dict] = {}
    for r in rows:
        agg = by_label.setdefault(r["label"], {"calls": 0, "tokens": 0})
        agg["calls"] += 1
        agg["tokens"] += r["total_tokens"] or 0

    return {
        "calls": len(rows),
        "errors": sum(1 for r in rows if r["status"] == "error"),
        "total_tokens": sum(r["total_tokens"] or 0 for r in rows),
        "cost_usd": round(sum(float(r["cost_usd"] or 0) for r in rows), 4) or None,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "by_label": by_label,
    }


@router.get("/analyses/{analysis_id}/calls")
def get_analysis_calls(analysis_id: str, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    return (client.table("llm_calls")
            .select("label, kind, model, status, latency_ms, "
                    "prompt_tokens, completion_tokens, total_tokens, cost_usd")
            .eq("analysis_id", analysis_id).eq("user_id", user.user_id)
            .order("created_at").execute()).data


@router.get("/analyses")
def list_analyses(user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    return (client.table("analyses")
            .select("id, jd_title, company_name, status, app_status, "
                    "match_score, ats_score, created_at")
            .eq("user_id", user.user_id)
            .order("created_at", desc=True).execute()).data


class ApproveIn(BaseModel):
    # Optional user edits made during review: { section_id: [bullet, ...] }
    rewritten_bullets: dict[str, list[str]] | None = None


@router.post("/analyses/{analysis_id}/approve")
def approve_analysis(analysis_id: str, body: ApproveIn, tasks: BackgroundTasks,
                     user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    rows = (client.table("analyses").select("id, status")
            .eq("id", analysis_id).eq("user_id", user.user_id).execute()).data
    if not rows:
        raise HTTPException(404, "Analysis not found")
    if rows[0]["status"] != "awaiting_approval":
        raise HTTPException(409, f"Analysis is not awaiting approval "
                                 f"(status: {rows[0]['status']})")

    if body.rewritten_bullets is not None:
        cv = (client.table("cv_structure").select("sections")
              .eq("user_id", user.user_id).execute()).data
        if not cv:
            raise HTTPException(409, "No CV on file")
        counts = {s["id"]: len(s["bullets"])
                  for s in cv[0]["sections"] if s.get("bullets")}
        issues = validate_bullets(body.rewritten_bullets, counts)
        if issues:
            raise HTTPException(422, "Edited bullets invalid: "
                                     + "; ".join(issues[:3]))
        (client.table("analyses")
         .update({"rewritten_bullets": body.rewritten_bullets})
         .eq("id", analysis_id).execute())

    tasks.add_task(resume_analysis, client, user.user_id, analysis_id)
    return {"id": analysis_id, "status": "resuming"}


class AppStatusIn(BaseModel):
    app_status: Literal["not_applied", "applied", "interviewing", "offer", "rejected"]


@router.patch("/analyses/{analysis_id}/status")
def set_app_status(analysis_id: str, body: AppStatusIn,
                   user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    result = (client.table("analyses").update({"app_status": body.app_status})
              .eq("id", analysis_id).eq("user_id", user.user_id).execute())
    if not result.data:
        raise HTTPException(404, "Analysis not found")
    return {"id": analysis_id, "app_status": body.app_status}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    result = (client.table("analyses").select("*")
              .eq("id", analysis_id).eq("user_id", user.user_id).execute())
    if not result.data:
        raise HTTPException(404, "Analysis not found")
    return result.data[0]
