"""LLM call telemetry — every OpenAI request is recorded to llm_calls.

A contextvar carries (db client, user_id, analysis_id) so the recorder needs
no plumbing through agent signatures. Recording is best-effort: a telemetry
failure must never break the pipeline.
"""

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from .config import get_settings

log = logging.getLogger("telemetry")

_ctx: ContextVar[dict | None] = ContextVar("llm_ctx", default=None)


def set_context(client, user_id: str, analysis_id: str | None = None):
    _ctx.set({"client": client, "user_id": user_id, "analysis_id": analysis_id})


def record(label: str, model: str | None, latency_ms: int,
           prompt_tokens: int | None = None, completion_tokens: int | None = None,
           total_tokens: int | None = None, kind: str = "chat",
           status: str = "ok", error: str | None = None,
           provider: str | None = None, response: str | None = None):
    ctx = _ctx.get()
    if not ctx:
        return
    settings = get_settings()
    cost = None
    if (prompt_tokens is not None
            and settings.openai_input_cost_per_1m
            and settings.openai_output_cost_per_1m):
        cost = round(
            (prompt_tokens * settings.openai_input_cost_per_1m
             + (completion_tokens or 0) * settings.openai_output_cost_per_1m)
            / 1_000_000, 6)
    try:
        ctx["client"].table("llm_calls").insert({
            "user_id": ctx["user_id"],
            "analysis_id": ctx["analysis_id"],
            "label": label,
            "kind": kind,
            "provider": provider,
            "model": model,
            "status": status,
            "error": (error or "")[:300] or None,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost,
            "response": (response or "")[:8000] or None,
        }).execute()
    except Exception:
        log.exception("failed to record llm call %s", label)


# ---------------------------------------------------------------------------
# Per-agent execution trail → analysis_events (wall-clock, includes tool loops)
# ---------------------------------------------------------------------------
def _insert_event(ctx: dict, agent: str, stage: str | None, status: str,
                  detail: str | None, error: str | None,
                  started_at: datetime, duration_ms: int | None):
    try:
        ctx["client"].table("analysis_events").insert({
            "analysis_id": ctx["analysis_id"],
            "user_id": ctx["user_id"],
            "agent": agent,
            "stage": stage,
            "status": status,
            "detail": (detail or "")[:300] or None,
            "error": (error or "")[:300] or None,
            "started_at": started_at.isoformat(),
            "duration_ms": duration_ms,
        }).execute()
    except Exception:
        log.exception("failed to record analysis event %s", agent)


@contextmanager
def record_stage(agent: str, stage: str | None = None, detail: str | None = None):
    """Time an agent stage and append one row to analysis_events. Best-effort:
    an error is recorded and re-raised so the pipeline's own recovery still runs."""
    ctx = _ctx.get()
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        yield
    except BaseException as exc:  # record failure, then let the caller handle it
        status, error = "error", str(exc)[:300]
        raise
    finally:
        if ctx:
            _insert_event(ctx, agent, stage, status, detail, error, started,
                          int((time.perf_counter() - t0) * 1000))


def record_skip(agent: str, stage: str | None = None, detail: str | None = None):
    ctx = _ctx.get()
    if ctx:
        _insert_event(ctx, agent, stage, "skipped", detail, None,
                      datetime.now(timezone.utc), None)
