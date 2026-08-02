"""Gateway capability probe — does the configured LLM endpoint support
everything the pipeline needs?

Fires one MINIMAL call per capability (a few hundred tokens total) against
whatever OPENAI_BASE_URL / OPENAI_MODEL is configured, and prints a matrix.

    cd apps/api && py probe_gateway.py

Capabilities probed, mapped to where the codebase needs them:
  1. plain chat            → cover letter draft + editor pass
  2. usage reporting       → telemetry (tokens/cost in llm_calls)
  3. json_schema (strict)  → rewriter, critic, ATS, coverage, judge, match
  4. function calling      → analyst tool loop, Tavily research loop
  5. strict function tool  → the finish(...) exit tool in run_tool_loop
  6. multi-turn tool msgs  → feeding tool results back into the loop
  7. responses+web_search  → hosted research (OpenAI-only; Tavily replaces it)
  8. Tavily search API     → gateway-mode research (if key configured)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings  # noqa: E402
from app.pipeline import providers  # noqa: E402

s = get_settings()
# Probe the agent-role primary endpoint (defaults to OpenCode). Pass a role
# name as argv[1] ('planner') to probe the planner (Gemini) chain instead.
role = sys.argv[1] if len(sys.argv) > 1 else "agent"
_ep = providers.chain_for(role)[0]
client = providers.client_for(_ep)
MODEL = _ep.model

results: list[tuple[str, bool, str]] = []


def probe(name: str):
    def wrap(fn):
        try:
            detail = fn() or "ok"
            results.append((name, True, detail))
        except Exception as exc:
            results.append((name, False, str(exc)[:140]))
    return wrap


# 1 — plain chat
@probe("plain chat completions")
def _():
    r = client.chat.completions.create(model=MODEL, messages=[
        {"role": "user", "content": "Reply with exactly: pong"}])
    return f"reply={r.choices[0].message.content!r:.30}"


# 2 — usage reporting (telemetry depends on it)
@probe("usage / token reporting")
def _():
    r = client.chat.completions.create(model=MODEL, messages=[
        {"role": "user", "content": "hi"}])
    u = r.usage
    assert u and u.total_tokens, "no usage block returned"
    return f"total_tokens={u.total_tokens}"


# 3 — strict structured outputs (the pipeline's backbone)
@probe("json_schema strict mode")
def _():
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Give a score of 7"}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "t", "strict": True, "schema": {
                "type": "object", "properties": {"score": {"type": "integer"}},
                "required": ["score"], "additionalProperties": False}}})
    data = json.loads(r.choices[0].message.content)
    assert isinstance(data.get("score"), int)
    return f"parsed={data}"


TOOLS = [{"type": "function", "function": {
    "name": "get_number", "description": "Returns a number.",
    "parameters": {"type": "object", "properties": {},
                   "additionalProperties": False}}}]

STRICT_FINISH = [{"type": "function", "function": {
    "name": "finish", "description": "Submit the answer.", "strict": True,
    "parameters": {"type": "object", "properties": {"answer": {"type": "integer"}},
                   "required": ["answer"], "additionalProperties": False}}}]


# 4 — function calling
@probe("function calling (tools)")
def _():
    r = client.chat.completions.create(
        model=MODEL, tools=TOOLS, tool_choice="auto",
        messages=[{"role": "user",
                   "content": "Call get_number, then tell me what it returned."}])
    tcs = r.choices[0].message.tool_calls
    assert tcs, "model did not emit a tool call"
    return f"called={tcs[0].function.name}"


# 5 — strict function schema (the finish-tool pattern)
@probe("strict function schema (finish tool)")
def _():
    r = client.chat.completions.create(
        model=MODEL, tools=STRICT_FINISH,
        tool_choice={"type": "function", "function": {"name": "finish"}},
        messages=[{"role": "user", "content": "Finish with answer 42."}])
    tc = r.choices[0].message.tool_calls[0]
    args = json.loads(tc.function.arguments)
    assert args.get("answer") == 42, f"bad args {args}"
    return "finish(42) parsed"


# 6 — multi-turn: tool result fed back (the loop's second iteration)
@probe("multi-turn tool-result round trip")
def _():
    first = client.chat.completions.create(
        model=MODEL, tools=TOOLS, tool_choice="auto",
        messages=[{"role": "user",
                   "content": "Call get_number, then state the number."}])
    msg = first.choices[0].message
    assert msg.tool_calls, "no tool call to answer"
    followup = client.chat.completions.create(
        model=MODEL, tools=TOOLS,
        messages=[
            {"role": "user", "content": "Call get_number, then state the number."},
            msg,
            {"role": "tool", "tool_call_id": msg.tool_calls[0].id,
             "content": json.dumps({"number": 17})},
        ])
    reply = followup.choices[0].message.content or ""
    assert "17" in reply, f"tool result ignored: {reply!r:.60}"
    return "tool result consumed"


# 7 — hosted web_search via Responses API (OpenAI-only; expected FAIL on gateways)
@probe("responses API + hosted web_search")
def _():
    r = client.responses.create(
        model=MODEL, tools=[{"type": "web_search"}],
        input="In one short sentence: what is Tavily?")
    return f"output={r.output_text[:50]!r}"


# 8 — Tavily (the gateway-mode research replacement)
@probe("tavily search API")
def _():
    if not s.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY not set — research will be skipped")
    from app.pipeline.tools import web_search
    out = web_search("Tavily search API", max_results=1)
    if "error" in out:
        raise RuntimeError(out["error"])
    return f"{len(out['results'])} result(s)"


# ---------------------------------------------------------------------------
print(f"\nrole     : {role}")
print(f"provider : {_ep.provider}")
print(f"endpoint : {_ep.base_url}")
print(f"model    : {MODEL}\n")
print(f"{'capability':<38} {'status':<6} detail")
print("-" * 88)
for name, ok, detail in results:
    print(f"{name:<38} {'PASS' if ok else 'FAIL':<6} {detail}")

need = {r[0]: r[1] for r in results}
core = ["plain chat completions", "json_schema strict mode",
        "function calling (tools)", "strict function schema (finish tool)",
        "multi-turn tool-result round trip"]
research_ok = need.get("responses API + hosted web_search") or need.get("tavily search API")

print("\nverdict:")
if all(need.get(c) for c in core):
    print("  CORE PIPELINE: fully supported "
          "(match, ATS, rewrite+critic, cover letter, analyst loop)")
else:
    missing = [c for c in core if not need.get(c)]
    print(f"  CORE PIPELINE: BLOCKED — missing: {', '.join(missing)}")
print(f"  RESEARCH: {'available' if research_ok else 'unavailable — set TAVILY_API_KEY (hosted web_search needs real OpenAI)'}")
if not need.get("usage / token reporting"):
    print("  TELEMETRY: token counts unavailable — llm_calls will log latency only")
