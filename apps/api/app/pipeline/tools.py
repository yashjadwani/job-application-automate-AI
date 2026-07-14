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

from . import stages

log = logging.getLogger("tools")

MAX_ITERATIONS = 8


class ToolLoopError(RuntimeError):
    pass


def run_tool_loop(agent_name: str, system: str, user: str,
                  tool_schemas: list[dict], tool_impls: dict,
                  finish_schema: dict, trace) -> dict:
    """Run a tool-calling loop until the model calls finish(...)."""
    tools = tool_schemas + [{
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Submit your final answer. Call this exactly once, "
                           "when you have gathered enough information.",
            "parameters": finish_schema,
            "strict": True,
        },
    }]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    for iteration in range(MAX_ITERATIONS):
        resp = stages._chat(f"{agent_name.lower()}_tool_loop",
                            messages=messages, tools=tools, tool_choice="auto")
        msg = resp.choices[0].message

        if not msg.tool_calls:
            # Model chatted instead of acting — nudge it back on task
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content":
                             "Use your tools, then call finish(...) with your "
                             "final answer. Do not reply in prose."})
            continue

        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None

            if name == "finish" and args is not None:
                trace.add(agent_name, "finish", f"after {iteration + 1} round(s)")
                return args

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

    raise ToolLoopError(f"{agent_name} hit the {MAX_ITERATIONS}-iteration limit")


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
