"""Function-calling tools + the generic agent loop.

This is the textbook agentic pattern:

    while not done:
        model responds with tool_calls
        we execute them and append results
        model sees results, decides the next move
        ... until it calls finish(...) with its final answer

Key safety properties (guardrails baked into the loop):
- finish() is a tool with a strict schema → the final answer is validated
- max_iterations hard-stops runaway loops
- unknown tools / bad args return an error TO THE MODEL (it can recover)
- every tool call is logged to the agent trace (observable behaviour)
- each iteration spends from the per-analysis call budget
"""

import json
import logging
import re

import httpx

from ..config import get_settings
from . import stages

log = logging.getLogger("tools")

MAX_ITERATIONS = 8


class ToolLoopError(RuntimeError):
    pass


# Some gateways 400 on strict function schemas; flips to False on first
# rejection and stays there for the process lifetime.
_finish_strict = True


def _build_tools(tool_schemas: list[dict], finish_schema: dict) -> list[dict]:
    finish_fn = {
        "name": "finish",
        "description": "Submit your final answer. Call this exactly once, "
                       "when you have gathered enough information.",
        "parameters": finish_schema,
    }
    if _finish_strict:
        finish_fn["strict"] = True
    return tool_schemas + [{"type": "function", "function": finish_fn}]


def _loose_json(raw: str) -> dict | None:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        try:
            return stages._parse_json_lenient(raw)
        except Exception:
            return None


def _transcript(messages: list) -> str:
    """Flatten the loop conversation (searches + results) for the synth fallback."""
    parts = []
    for m in messages:
        if isinstance(m, dict):
            if m.get("role") == "tool" and m.get("content"):
                parts.append(f"[result] {m['content'][:1500]}")
            elif m.get("role") == "user" and m.get("content"):
                parts.append(f"[task] {m['content'][:400]}")
        else:  # assistant message object carrying tool_calls
            for tc in getattr(m, "tool_calls", None) or []:
                parts.append(f"[called {tc.function.name}] {tc.function.arguments[:200]}")
    return "\n".join(parts)[:8000]


def run_tool_loop(agent_name: str, system: str, user: str,
                  tool_schemas: list[dict], tool_impls: dict,
                  finish_schema: dict, trace) -> dict:
    """Run a tool-calling loop until the model calls finish(...).

    Robust against weak models: nudges toward finishing near the limit, parses
    finish args leniently, and — if the loop still exhausts — SYNTHESISES the
    final answer from the gathered context instead of raising. Callers always
    get a schema-shaped result."""
    global _finish_strict
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    for iteration in range(MAX_ITERATIONS):
        # Firm nudge on the penultimate round so a rambling model converges
        if iteration == MAX_ITERATIONS - 2:
            messages.append({"role": "user", "content":
                             "You now have enough information. Do NOT search "
                             "again — call finish(...) with your final answer now."})
        tools = _build_tools(tool_schemas, finish_schema)
        try:
            resp = stages._chat(f"{agent_name.lower()}_tool_loop",
                                messages=messages, tools=tools,
                                tool_choice="auto")
        except stages.BadRequestError:
            if not _finish_strict:
                raise
            _finish_strict = False
            log.warning("strict finish tool rejected by endpoint — retrying "
                        "without strict")
            resp = stages._chat(f"{agent_name.lower()}_tool_loop",
                                messages=messages,
                                tools=_build_tools(tool_schemas, finish_schema),
                                tool_choice="auto")
        msg = resp.choices[0].message

        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content":
                             "Use your tools, then call finish(...) with your "
                             "final answer. Do not reply in prose."})
            continue

        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            args = _loose_json(tc.function.arguments)

            if name == "finish":
                if args is not None:
                    trace.add(agent_name, "finish", f"after {iteration + 1} round(s)")
                    return args
                result = {"error": "finish arguments were not valid JSON — "
                                   "resend ONLY a valid JSON object"}
            else:
                impl = tool_impls.get(name)
                if impl is None or args is None:
                    result = {"error": f"unknown tool or bad arguments: {name}"}
                else:
                    try:
                        result = impl(**args)
                    except TypeError as exc:
                        result = {"error": f"bad arguments: {exc}"}
                    except Exception as exc:
                        result = {"error": f"tool failed: {exc}"}

            detail = ", ".join(f"{k}={str(v)[:40]}" for k, v in (args or {}).items())
            trace.add(agent_name, f"tool: {name}", detail)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)[:6000]})

    # Loop exhausted — salvage: synthesise the final answer from what was gathered
    trace.add(agent_name, "synthesising",
              "hit loop limit — building answer from gathered context")
    try:
        return stages._structured(
            system + "\n\nResearch is complete. Using ONLY the information "
            "already gathered below, produce the final answer.",
            _transcript(messages),
            f"{agent_name.lower()}_synth", finish_schema)
    except Exception as exc:
        raise ToolLoopError(
            f"{agent_name} hit the {MAX_ITERATIONS}-iteration limit and "
            f"synthesis failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Web search tool (Tavily) — used for employer research when the hosted
# OpenAI web_search tool isn't available (any non-OpenAI gateway).
# ---------------------------------------------------------------------------
def web_search(query: str, max_results: int = 5) -> dict:
    key = get_settings().tavily_api_key
    if not key:
        return {"error": "no search API configured"}
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query,
                  "max_results": max_results, "search_depth": "basic"},
            timeout=20)
        r.raise_for_status()
        return {"results": [
            {"title": x.get("title", ""), "url": x.get("url", ""),
             "content": (x.get("content") or "")[:400]}
            for x in r.json().get("results", [])]}
    except Exception as exc:
        return {"error": f"search failed: {exc}"}


SEARCH_TOOL_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the public web. Returns titles, URLs and "
                       "snippets. Use focused queries; call repeatedly for "
                       "different angles.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False},
    },
}]


# ---------------------------------------------------------------------------
# Deterministic tool: keyword coverage (pure Python — cannot hallucinate)
# ---------------------------------------------------------------------------
def keyword_coverage(cv_text: str, keywords: list[str]) -> dict:
    """Which keywords literally appear in the CV (case-insensitive,
    word-boundary where possible)."""
    lowered = cv_text.lower()
    present, missing = [], []
    for kw in keywords:
        k = kw.strip()
        if not k:
            continue
        pattern = r"\b" + re.escape(k.lower()) + r"\b"
        if re.search(pattern, lowered) or k.lower() in lowered:
            present.append(kw)
        else:
            missing.append(kw)
    return {"present": present, "missing": missing}


# ---------------------------------------------------------------------------
# CV/profile tools for the Match Analyst agent
# ---------------------------------------------------------------------------
def build_cv_toolkit(profile: dict, cv: dict):
    """Returns (schemas, implementations) closing over this user's data."""
    sections = cv.get("sections", [])
    cv_text = json.dumps(sections, ensure_ascii=False)

    def list_sections() -> dict:
        return {"sections": [
            {"id": s["id"], "title": s["title"], "bullets": len(s.get("bullets", []))}
            for s in sections]}

    def get_section_bullets(section_id: str) -> dict:
        for s in sections:
            if s["id"] == section_id:
                return {"title": s["title"],
                        "bullets": [b["text"] for b in s.get("bullets", [])]}
        return {"error": f"no such section: {section_id}"}

    def get_profile() -> dict:
        return {k: profile.get(k) for k in
                ("bio", "skills", "additional_context") if profile.get(k)}

    def check_keywords(keywords: list[str]) -> dict:
        return keyword_coverage(cv_text, keywords)

    schemas = [
        {"type": "function", "function": {
            "name": "list_sections",
            "description": "List the CV's sections with ids and bullet counts.",
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False}}},
        {"type": "function", "function": {
            "name": "get_section_bullets",
            "description": "Read the full bullets of one CV section.",
            "parameters": {"type": "object", "properties": {
                "section_id": {"type": "string"}},
                "required": ["section_id"], "additionalProperties": False}}},
        {"type": "function", "function": {
            "name": "get_profile",
            "description": "Read the candidate's bio, skills and extra context.",
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False}}},
        {"type": "function", "function": {
            "name": "check_keywords",
            "description": "Deterministically check which keywords literally "
                           "appear in the CV. Use for skills the JD demands.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}}},
                "required": ["keywords"], "additionalProperties": False}}},
    ]
    impls = {
        "list_sections": list_sections,
        "get_section_bullets": get_section_bullets,
        "get_profile": get_profile,
        "check_keywords": check_keywords,
    }
    return schemas, impls
