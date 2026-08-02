# Learn Agentic AI & Tool Configuration — Checklist

A concept-by-concept checklist, each mapped to **where it lives in this
codebase** and **which `debug.ipynb` section** lets you see it run. Tick them off
in order; by the end you'll understand agentic systems from a real one you own.

---

## Part A — Foundations (understand these first)

- [ ] **What "agentic" means.** An agent = an LLM that can *take actions* (call
  tools) in a loop toward a goal, not just answer once. Key shift: the model
  decides *what to do next*, not just *what to say*.
- [ ] **LLM call = one request/response.** Stateless. Everything the model
  "remembers" you must re-send. → `stages._chat` · notebook §3
- [ ] **Structured output.** Force the model to return JSON matching a schema, so
  code can consume it reliably. Two ways: strict `json_schema` mode, or
  prompt-engineered JSON + validation (fallback). → `stages._structured`
- [ ] **Determinism boundary.** Decide what the LLM does vs what code does. Rule
  here: *LLM proposes, Python disposes.* Scores/coverage are computed in code so
  they can't be hallucinated. → `tools.keyword_coverage`, ATS agent · §4c
- [ ] **Telemetry.** Log every call (tokens, latency, cost, label) — you can't
  improve what you can't measure. → `telemetry.py`, `llm_calls` table

## Part B — Tools (the "actions")

- [ ] **A tool = a function + a JSON schema** describing its name, purpose, and
  arguments. You give the model the schemas; it replies with which tool to call
  and with what arguments. → `tools.SEARCH_TOOL_SCHEMA`, `build_cv_toolkit` · §9
- [ ] **Deterministic vs LLM-backed tools.** Some tools are pure code
  (`keyword_coverage`, `list_sections`); some hit external APIs (`web_search`).
  Prefer deterministic tools for anything that must be correct.
- [ ] **Tool schema anatomy** — study one:
  ```json
  {"type":"function","function":{
     "name":"search_web",
     "description":"Search the public web…",   // the model reads THIS to decide
     "parameters":{"type":"object",
        "properties":{"query":{"type":"string"}},
        "required":["query"],"additionalProperties":false}}}
  ```
  Good `description`s are how the model knows *when* to use a tool.
- [ ] **strict mode on tools.** `"strict": true` guarantees the arguments match
  the schema — but not all gateways support it (yours doesn't; the code
  auto-degrades). → `tools._build_tools`, `_finish_strict`
- [ ] **The Tool Registry.** Tools behind one interface so they're discoverable
  and swappable (incl. future MCP tools). → `registry.build_tool_registry` · §9

## Part C — The agent loop (tool calling)

- [ ] **The ReAct loop:** model → returns tool_calls → you execute them → append
  results → model sees results → repeats → until it calls `finish(...)`. This is
  ~80% of agentic AI. Read the ~50 lines. → `tools.run_tool_loop` · §4b
- [ ] **A `finish` / exit tool** ends the loop with a schema-validated answer.
- [ ] **Termination safety** — weak models don't stop. Defences here: iteration
  cap, a nudge near the limit, and a synthesise-from-context fallback so it never
  crashes. → `run_tool_loop` tail
- [ ] **Tool budgets** — cap external calls (e.g. `MAX_SEARCHES=6`) for cost.
  → `agents._research_with_search_tool`

## Part D — Multi-agent patterns

- [ ] **Specialist agents.** One job each, own prompt/schema/tools. Don't build
  one god-agent. → `agents.py` (research, match, ats, rewrite, critic, editor) · §4
- [ ] **Tool-using agent** (decides its own investigation). → match analyst · §4b
- [ ] **Hybrid agent** (LLM extracts, code computes). → ATS · §4c
- [ ] **Adversarial / critic loop** (one agent checks another; feedback → revise).
  → rewrite ⇄ critic · §4d
- [ ] **Draft + editor** (generate, then refine). → cover letter · §4e
- [ ] **Shared context / working memory** — agents read inputs and write outputs
  to ONE object so nothing is recomputed. → `context.AnalysisContext` · §9/§11
- [ ] **Session memory** — track completed/errors/retries/decisions so the system
  never repeats work (esp. on resume). → `AnalysisContext` fields

## Part E — Orchestration (planner)

- [ ] **Fixed pipeline vs planner.** A fixed order is simple and predictable; a
  **planner** decides dynamically which agents to run, skip, repeat, and when to
  stop. → linear `worker._run_linear` vs `orchestrator` · §5 vs §11
- [ ] **Structured plans, not free text.** The planner returns
  `{plan:[...], reasoning}`. → `planner.make_plan`, `PLAN_SCHEMA` · §10a
- [ ] **Validate the plan deterministically.** Never trust an LLM to orchestrate
  unaided: complete dependencies, enforce ordering, fall back to canonical.
  → `planner.validate_plan` · §10b
- [ ] **Event loop.** plan → run agent → update memory → evaluate → continue/stop.
  → `orchestrator._execute` · §11
- [ ] **Agent Registry.** Planner requests agents by name + metadata
  (`requires`/`produces`); add an agent without touching orchestration.
  → `registry.build_agent_registry` · §9

## Part F — Production concerns

- [ ] **Guardrails (4 layers):** input sanitisation, execution budget, output
  validation, semantic (critic). → `guardrails.py`, `agents.critique_bullets`
- [ ] **Human-in-the-loop.** Pause for approval before consequential output;
  enforce it in code, not via the planner's discretion. → HITL gate · §5/§11
- [ ] **Error recovery.** Retry, skip optional agents, fail cleanly, never crash
  the whole run. → `orchestrator._run_agent`
- [ ] **Gateway portability.** Capabilities differ per endpoint; detect and fall
  back (strict JSON, hosted web_search). → `probe_gateway.py`, `_strict_supported`
- [ ] **Evaluation.** Fixed cases + deterministic metrics + an LLM judge, versioned
  by prompt, diffed over time. → `evals/run.py`, `PROMPT_VERSION`
- [ ] **Cost & performance.** Budget caps, no duplicate work, cache expensive
  calls, minimise tokens.

---

## Hands-on path (do these in order)

1. **Run `probe_gateway.py`** — learn what your endpoint supports.
2. **Notebook §3** — make one raw LLM call; inspect `usage`.
3. **Notebook §4b** — watch a tool loop choose tools (the core skill).
4. **Notebook §4c** — see the hybrid pattern (LLM + deterministic code).
5. **Notebook §4d** — watch the critic force a revision.
6. **Notebook §9** — inspect the agent + tool registries.
7. **Notebook §10** — make a plan, then break it and watch the validator repair it.
8. **Notebook §11** — watch the full event loop pause for approval.
9. **Read `tools.run_tool_loop`** end to end (~50 lines).
10. **Add a trivial tool** to `build_tool_registry`, re-run §9 — see it appear.

## The three files to truly understand

1. `pipeline/tools.py :: run_tool_loop` — the agent loop.
2. `pipeline/planner.py` — LLM-proposes / code-disposes orchestration.
3. `pipeline/guardrails.py` — the deterministic safety net.

If you understand those three, you understand this system — and most agentic
systems in production.
