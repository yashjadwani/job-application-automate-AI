"""LLM call telemetry — every OpenAI request is recorded to llm_calls.

A contextvar carries (db client, user_id, analysis_id) so the recorder needs
no plumbing through agent signatures. Recording is best-effort: a telemetry
failure must never break the pipeline.
"""

import logging
from contextvars import ContextVar

from .config import get_settings

log = logging.getLogger("telemetry")

_ctx: ContextVar[dict | None] = ContextVar("llm_ctx", default=None)


def set_context(client, user_id: str, analysis_id: str | None = None):
    _ctx.set({"client": client, "user_id": user_id, "analysis_id": analysis_id})


def record(label: str, model: str | None, latency_ms: int,
           prompt_tokens: int | None = None, completion_tokens: int | None = None,
           total_tokens: int | None = None, kind: str = "chat",
           status: str = "ok", error: str | None = None):
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
            "model": model,
            "status": status,
            "error": (error or "")[:300] or None,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost,
        }).execute()
    except Exception:
        log.exception("failed to record llm call %s", label)
