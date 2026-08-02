"""Planner Agent.

Analyses the request + current context, then returns a STRUCTURED execution
plan (which specialist agents to run, in what order, with reasoning). A weak
gateway model can't be trusted to orchestrate alone, so the LLM plan passes
through a deterministic validator that:
  - drops unknown / already-satisfied agents,
  - completes missing dependencies (topological),
  - forces the HITL ordering (cover_letter always last),
  - falls back to the canonical order if the plan is empty/invalid.

Net effect: the Planner adds intelligence (skipping, reordering, repetition)
while the validator guarantees a runnable, safe plan every time.
"""

import logging

from . import stages
from .context import AnalysisContext
from .registry import AgentRegistry

log = logging.getLogger("planner")

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["plan", "reasoning"],
    "additionalProperties": False,
}

OBJECTIVE = (
    "Produce a job-tailored set of rewritten CV bullets and a cover letter. "
    "Research the employer only if a company is named and not already researched."
)


def _catalog(ctx: AnalysisContext, registry: AgentRegistry) -> list[dict]:
    out = []
    for spec in registry.all():
        done = all(ctx.has(k) for k in spec.produces) and spec.produces != []
        out.append({
            "agent": spec.name,
            "does": spec.description,
            "needs": spec.requires,
            "already_done": done,
        })
    return out


def make_plan(ctx: AnalysisContext, registry: AgentRegistry) -> tuple[list[str], str]:
    """Return (validated_plan, reasoning)."""
    import json
    reasoning = ""
    proposed: list[str] = []
    try:
        out = stages._structured(
            "You are a planning agent for a CV-tailoring system. Given the "
            "available specialist agents and what has already been produced, "
            "output the ordered list of agent names to run to achieve the "
            "objective. Skip agents whose output already exists or that aren't "
            "useful (e.g. research when no company). Keep it minimal.",
            json.dumps({"objective": OBJECTIVE,
                        "company_known": bool(ctx.company),
                        "agents": _catalog(ctx, registry),
                        "already_completed": ctx.completed}, ensure_ascii=False),
            "analysis_plan", PLAN_SCHEMA, role="planner")   # runs on Gemini
        proposed = [a for a in out.get("plan", []) if isinstance(a, str)]
        reasoning = out.get("reasoning", "")
    except Exception as exc:
        log.warning("planner LLM failed (%s) — using canonical plan", exc)
        reasoning = "planner unavailable; canonical order"

    plan = validate_plan(proposed, ctx, registry)
    ctx.note_decision(plan, reasoning)
    return plan, reasoning


def canonical_plan(ctx: AnalysisContext, registry: AgentRegistry) -> list[str]:
    order = []
    if ctx.company and not ctx.has("research"):
        order.append("research")
    order += ["cv_analysis", "ats", "rewrite", "critic", "cover_letter"]
    return [a for a in order if registry.get(a)]


def _complete_dependencies(plan: list[str], ctx: AnalysisContext,
                           registry: AgentRegistry) -> list[str]:
    result: list[str] = []

    def add(name: str, seen: set[str]):
        spec = registry.get(name)
        if not spec or name in result or name in seen:
            return
        for req in spec.requires:
            if not ctx.has(req):
                producer = registry.producer_of(req)
                if producer:
                    add(producer, seen | {name})
        if name not in result:
            result.append(name)

    for a in plan:
        add(a, set())
    return result


def validate_plan(proposed: list[str], ctx: AnalysisContext,
                  registry: AgentRegistry) -> list[str]:
    # 1. keep known agents; drop ones already completed or whose outputs exist.
    #    (The rewrite↔critic revision loop re-runs agents via direct queueing,
    #    not via re-planning, so "repeatable" is irrelevant to planning.)
    plan = []
    for a in proposed:
        spec = registry.get(a)
        if not spec or a in ctx.completed:
            continue
        if spec.produces and all(ctx.has(k) for k in spec.produces):
            continue
        plan.append(a)

    # 2. guarantee the two deliverables get produced
    if not ctx.has("rewritten_bullets") and "rewrite" not in plan:
        plan.append("rewrite")
    if not ctx.has("cover_letter") and "cover_letter" not in plan:
        plan.append("cover_letter")

    # 3. complete dependencies (topological)
    plan = _complete_dependencies(plan, ctx, registry)

    # 4. ensure a critic follows a rewrite (quality gate)
    if "rewrite" in plan and "critic" not in plan:
        plan.insert(plan.index("rewrite") + 1, "critic")

    # 5. HITL safety: cover_letter is always LAST so approval gates it
    if "cover_letter" in plan:
        plan = [a for a in plan if a != "cover_letter"] + ["cover_letter"]

    # 6. de-dup preserving order; fall back if empty
    seen, deduped = set(), []
    for a in plan:
        if a not in seen:
            seen.add(a)
            deduped.append(a)
    return deduped or canonical_plan(ctx, registry)
