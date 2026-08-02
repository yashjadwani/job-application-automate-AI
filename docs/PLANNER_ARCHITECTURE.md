# Planner-Based Agent Architecture

How the fixed pipeline evolved into a dynamic, planner-driven multi-agent
system — **additively**, behind a flag, with the original pipeline preserved.

---

## 1. Philosophy

The system already followed one principle: **the LLM proposes, deterministic
code disposes.** The planner extends exactly that principle to *orchestration*:

- The **Planner Agent** (an LLM call) proposes which specialist agents to run.
- A **deterministic validator** repairs the plan (dependency completion, HITL
  ordering) and falls back to the canonical order if the LLM output is unusable.

Result: the intelligence of dynamic planning (skip, reorder, repeat, stop early)
with a hard guarantee that every plan is runnable and safe — essential on a weak
gateway model that can't be trusted to orchestrate unaided.

## 2. Architecture

```
                         ┌───────────────────────────┐
   POST /analyse ───────►│   worker.run_analysis      │  (unchanged signature)
                         │   PLANNER_ENABLED ?         │
                         └───────┬───────────┬────────┘
                          false  │           │  true
                   ┌─────────────▼──┐   ┌────▼─────────────────────────────┐
                   │ _run_linear     │   │ orchestrator.run                 │
                   │ (original,      │   │  1. sanitise JD (guardrail)      │
                   │  fixed order)   │   │  2. Planner.make_plan ───────────┼──► LLM
                   └─────────────────┘   │  3. validate_plan (deterministic)│
                                         │  4. event loop ▼                 │
                                         └──────────┬───────────────────────┘
                                                    │
   ┌────────────────────────── event loop ─────────▼───────────────────────┐
   │  pop next agent → run (retry/recover) → write shared memory →          │
   │  evaluate: revision loop? HITL pause? done?                            │
   └───────────────────────────────────────────────────────────────────────┘
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼         Agent Registry (planner requests these) ▼
   ┌─────────────┬────────────┬──────┬─────────┬────────┬──────────────┐
   │  research   │ cv_analysis│ ats  │ rewrite │ critic │ cover_letter │  (+ future)
   └──────┬──────┴─────┬──────┴──┬───┴────┬────┴───┬────┴──────────────┘
          │            │         │        │        │
          ▼            ▼         ▼         ▼        ▼   Tool Registry
   ┌───────────────────────────────────────────────────────────────┐
   │ web_search · keyword_coverage · list_sections · get_profile …  │
   └───────────────────────────────────────────────────────────────┘

   Shared Context (working + session memory) threads through everything:
   { profile, cv, jd, research, match, ats, rewritten_bullets, cover_letter,
     completed[], errors{}, retries{}, decisions[], trace }
```

## 3. New modules (all in `apps/api/app/pipeline/`)

| File | Responsibility |
|------|----------------|
| `context.py` | `AnalysisContext` — shared working memory + session memory |
| `registry.py` | `AgentRegistry` + `ToolRegistry` + the specialist `AgentSpec`s |
| `planner.py` | Planner LLM call + deterministic `validate_plan` + canonical fallback |
| `orchestrator.py` | Event loop: run/recover, revision loop, HITL pause, persistence, notify |

Existing modules are reused unchanged — the registry agents are thin adapters
over the *same* `research_agent`, `match_analyst_agent`, `ats_agent`,
`run_bullets`, `critique_bullets`, `cover_letter_agent`.

## 4. Requirement → implementation map

| # | Requirement | Where |
|---|-------------|-------|
| 1 | Planner returns structured plans | `planner.make_plan` → `PLAN_SCHEMA` |
| 2 | Specialists stay independent | `registry.py` adapters; logic untouched |
| 3 | Agent Registry | `AgentRegistry` — planner requests by name |
| 4 | Shared context | `AnalysisContext.data` |
| 5 | Session memory (no duplicate work) | `completed/errors/retries/decisions`; `_derive_completed` on resume |
| 6 | Tool Registry | `ToolRegistry` + `build_tool_registry` |
| 7 | Event-driven execution | `orchestrator._execute` loop |
| 8 | Human approval preserved | HITL gate before `cover_letter` (deterministic) |
| 9 | Observability | Planner/agent/revision events + per-agent timing in `agent_trace`; all LLM calls in `llm_calls` |
| 10 | Error recovery | `_run_agent` retries; optional agents skip; essential fail cleanly; never crashes |
| 11 | Extensibility | add an `AgentSpec`; planner discovers it via catalog |
| 12 | Performance | budget cap, no duplicate work, research cap; concurrency = documented seam (see §7) |
| 13 | Existing features intact | flag-gated; same statuses/columns/API/UI |

## 5. Execution flow (planner mode)

```
plan = [research, cv_analysis, ats, rewrite, critic, cover_letter]

researching → research          (optional; skipped if no company / on failure)
analysing   → cv_analysis, ats
writing     → rewrite → critic
                 └─ not approved & retries left → re-queue rewrite→critic (revision)
awaiting_approval  ← HITL pause (deterministic, before cover_letter)
   … POST /analyses/{id}/approve …
reviewing   → cover_letter
done
```

On resume, the context is rehydrated from the persisted row; `_derive_completed`
marks finished agents, so the planner re-plans to only the remaining work
(`cover_letter`) — no duplication.

## 6. Adding a new agent (extensibility demo)

```python
# 1. write the run function
def _interview_prep(ctx):
    ctx.data["interview_prep"] = generate_questions(
        ctx.data.get("research"), ctx.data["match"], ctx.trace)

# 2. register it — no orchestration changes
reg.register(AgentSpec(
    "interview_prep",
    "Generate likely interview questions from research + gaps.",
    requires=["match"], produces=["interview_prep"], status="reviewing",
    run=_interview_prep, optional=True))
```

The Planner immediately sees it in the catalog and may schedule it. (One DB
column would be needed to persist its output — the only schema touch-point.)

## 7. Known limitations / deferred

- **Concurrency is a documented seam, not enabled.** `research`, `cv_analysis`
  and `ats` are independent and *could* run in parallel, but the call budget and
  telemetry ride on contextvars that don't cross threads automatically, and the
  gateway is a flaky free tier. Forcing concurrency now would *reduce*
  reliability. The orchestrator is structured so a "run this group concurrently"
  helper can be added later with contextvar copying + a lock on `CallBudget`.
- **Planner quality tracks model quality.** On the free model the plan is
  usually the canonical order; the value shows most when a company is
  absent (research skipped) or work is already done (resume). The validator
  guarantees correctness regardless.

---

## 8. Migration notes

**To enable:** set `PLANNER_ENABLED=true` in `apps/api/.env` (or the Modal
secret). Nothing else changes — same routes, same frontend, same DB.

**To roll back:** set it `false` (the default). The original linear pipeline
runs, byte-for-byte as before.

**Recommended sequence:** verify the *linear* pipeline live first (it's the
tested default), then flip the planner on and compare via the eval harness and
the `agent_trace` on real runs. Because the validator falls back to the
canonical order, worst-case planner behaviour equals the linear pipeline.

**No database migration required.** Planner decisions, per-agent timings and
revision rounds are recorded as events inside the existing `agent_trace` jsonb.
(A future dedicated agent that produces new output would add one column.)

---

## 9. Backward-compatibility report

| Area | Status | Notes |
|------|:------:|-------|
| API contracts | ✅ unchanged | `run_analysis`/`resume_analysis` signatures identical; all routes unchanged |
| Status values | ✅ unchanged | `pending…awaiting_approval…done/failed` — frontend polling untouched |
| DB schema | ✅ unchanged | reuses existing columns + `agent_trace` |
| Frontend | ✅ unchanged | no component changes required; planner events render in the existing trace |
| Authentication | ✅ unchanged | untouched |
| Telemetry | ✅ preserved | planner LLM call logged like any other; per-agent timing added |
| Evaluation framework | ✅ preserved | evals call the specialist agents directly, unaffected |
| Prompt versioning | ✅ preserved | `PROMPT_VERSION` unchanged; planner prompt is additive |
| Exports | ✅ preserved | same `rewritten_bullets` / `cover_letter_text` outputs |
| Approval workflow | ✅ preserved | HITL pause enforced deterministically before cover letter |
| Linear pipeline | ✅ preserved | fully intact as `_run_linear`, default path |
| Tests | ✅ green | 26 existing + 4 planner tests = 30 passing |

**Guarantee:** with `PLANNER_ENABLED=false` (default), the system behaves
exactly as before this change. With it `true`, the observable outputs (statuses,
columns, files) are the same shape; only the *route* through the agents becomes
dynamic.
