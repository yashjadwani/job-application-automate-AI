"""The agentic analysis pipeline (PRD §3.1) — OpenAI, 4 stages + ATS scoring.

Stage 1  Match & gap         — strict Structured Outputs
Stage 1b ATS keyword scoring — strict Structured Outputs (added post-PRD)
Stage 2  Bullet rewriter     — strict Structured Outputs, bullet counts preserved
Stage 3  Cover letter        — plain text

All stages are synchronous functions; the worker in worker.py sequences them
and advances analyses.status so the frontend can poll. Employer research is a
tool-loop agent (see agents.py), not a stage here.
"""

import json
import logging
import time

from openai import BadRequestError

log = logging.getLogger("stages")

# Bump when any prompt changes — recorded in eval results so quality shifts
# can be traced to prompt edits (git blame gives the diff).
PROMPT_VERSION = "2026-07-08.1"  # strict formatting rules added to rewriter

from .. import telemetry
from ..config import get_settings
from . import providers
from .guardrails import spend


def _model() -> str:
    """The agent-role primary model (for eval labelling / probes)."""
    chain = providers.agent_chain()
    return chain[0].model if chain else get_settings().opencode_model


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _response_text(msg) -> str:
    """Serialise a chat message for the telemetry `response` column."""
    if getattr(msg, "content", None):
        return msg.content[:8000]
    tcs = getattr(msg, "tool_calls", None)
    if tcs:
        return "; ".join(f"{tc.function.name}({(tc.function.arguments or '')[:200]})"
                         for tc in tcs)[:8000]
    return ""


def _chat(label: str, role: str = "agent", **kwargs):
    """All chat.completions calls go through here: provider fallback, budget,
    telemetry. Walks the role's provider chain; on a transient failure it moves
    to the next provider. Each attempt is logged (provider, model, latency,
    tokens, response). BadRequestError is NOT retried across providers — it means
    the request shape is unsupported, which the caller degrades (strict → plain).
    """
    last_exc = None
    for ep in providers.chain_for(role):
        spend()
        t0 = time.perf_counter()
        try:
            resp = providers.client_for(ep).chat.completions.create(
                model=ep.model, **kwargs)
        except BadRequestError as exc:
            telemetry.record(label, ep.model, _ms(t0), kind="chat",
                             status="error", error=str(exc), provider=ep.provider)
            raise
        except Exception as exc:  # transient — fall back to the next provider
            telemetry.record(label, ep.model, _ms(t0), kind="chat",
                             status="error", error=str(exc), provider=ep.provider)
            last_exc = exc
            log.warning("provider %s (%s) failed for %s — falling back: %s",
                        ep.provider, ep.model, label, str(exc)[:100])
            continue
        usage = getattr(resp, "usage", None)
        telemetry.record(
            label, getattr(resp, "model", ep.model), _ms(t0),
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(usage, "total_tokens", None),
            provider=ep.provider,
            response=_response_text(resp.choices[0].message))
        return resp
    raise last_exc or RuntimeError(f"no LLM provider configured for role '{role}'")


# ---------------------------------------------------------------------------
# Structured-output helper (strict JSON schema)
# ---------------------------------------------------------------------------
# Some gateways reject strict json_schema mode with a 400. Detected once per
# ROLE at runtime, then cached (planner=gemini may support it, agent=opencode
# may not). Missing/True = try strict; False = use the prompt-engineered fallback.
_strict_supported: dict[str, bool] = {}


def _parse_json_lenient(text: str) -> dict:
    """Parse JSON from a model reply that may include fences or prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _structured(system: str, user: str, schema_name: str, schema: dict,
                role: str = "agent") -> dict:
    if _strict_supported.get(role) is not False:
        try:
            resp = _chat(
                schema_name, role=role,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True,
                                    "schema": schema},
                },
            )
            _strict_supported[role] = True
            return json.loads(resp.choices[0].message.content)
        except BadRequestError:
            _strict_supported[role] = False
            log.warning("strict json_schema rejected for role '%s' — "
                        "falling back to prompt-engineered JSON", role)

    # Fallback: works on any chat-completions endpoint. Downstream validators
    # (counts, section ids, guardrails) still enforce semantics.
    sys_msg = (system + "\n\nReturn ONLY a valid JSON object matching this "
               "JSON Schema — no prose, no markdown fences:\n"
               + json.dumps(schema))
    resp = _chat(f"{schema_name}_fb", role=role,
                 messages=[{"role": "system", "content": sys_msg},
                           {"role": "user", "content": user}])
    text = resp.choices[0].message.content or ""
    try:
        data = _parse_json_lenient(text)
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise ValueError(f"missing keys: {missing}")
        return data
    except (ValueError, json.JSONDecodeError) as exc:
        resp = _chat(f"{schema_name}_fb_retry", role=role,
                     messages=[{"role": "system", "content": sys_msg},
                               {"role": "user", "content": user},
                               {"role": "assistant", "content": text[:4000]},
                               {"role": "user", "content":
                                f"That output was invalid ({exc}). Return ONLY "
                                "the corrected JSON object."}])
        data = _parse_json_lenient(resp.choices[0].message.content or "")
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise ValueError(f"{schema_name}: still missing keys {missing} "
                             "after retry")
        return data


# ---------------------------------------------------------------------------
# Stage 1 — Match & gap
# ---------------------------------------------------------------------------
MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "matched_skills": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["score", "matched_skills", "gaps", "summary"],
    "additionalProperties": False,
}


def run_match(profile: dict, cv: dict, jd_text: str, research: dict | None) -> dict:
    context = json.dumps({"profile": profile, "cv_sections": cv.get("sections", []),
                          "employer_research": research}, ensure_ascii=False)
    return _structured(
        "You assess how well a candidate matches a job description. Score 0-100. "
        "Be honest: list genuine gaps, not flattery.",
        f"CANDIDATE CONTEXT:\n{context}\n\nJOB DESCRIPTION:\n{jd_text}",
        "match_result",
        MATCH_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Stage 2 — Bullet rewriter (counts preserved, ATS keywords woven in truthfully)
# ---------------------------------------------------------------------------
def _bullets_schema(sections: list[dict]) -> dict:
    props = {
        s["id"]: {"type": "array", "items": {"type": "string"}}
        for s in sections if s.get("bullets")
    }
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def run_bullets(profile: dict, cv: dict, jd_text: str, ats_missing: list[str],
                feedback: list[str] | None = None,
                previous: dict | None = None) -> dict:
    sections = [s for s in cv.get("sections", []) if s.get("bullets")]
    counts = {s["id"]: len(s["bullets"]) for s in sections}
    context = json.dumps({"profile": profile, "sections": sections}, ensure_ascii=False)

    user_msg = (f"CANDIDATE:\n{context}\n\nJOB DESCRIPTION:\n{jd_text}\n\n"
                f"ATS KEYWORDS MISSING FROM CV: {json.dumps(ats_missing)}")
    if feedback and previous:
        user_msg += (
            f"\n\nYOUR PREVIOUS DRAFT:\n{json.dumps(previous, ensure_ascii=False)}"
            f"\n\nA REVIEWER FOUND THESE ISSUES — fix every one:\n"
            + "\n".join(f"- {f}" for f in feedback)
        )

    result = _structured(
        "You rewrite CV bullet points to maximise relevance to a job description. "
        "HARD RULES — violating any of these makes the output unusable:\n"
        f"(1) EXACT same number of bullets per section — counts: {json.dumps(counts)}. "
        "Never merge, split, add or drop a bullet.\n"
        "(2) Never invent facts, employers, tools, metrics or outcomes not present "
        "in the original bullets.\n"
        "(3) FORMATTING MUST REMAIN IDENTICAL: plain text only — no markdown, no "
        "bold/italic markers (**, _, `), no bullet glyphs (•, -, *) at the start, "
        "no numbering, no trailing punctuation changes (if the original bullet has "
        "no full stop, yours has none), no line breaks inside a bullet.\n"
        "(4) Keep each rewritten bullet within ±20% of the original bullet's "
        "length so the document layout does not reflow.\n"
        "(5) Where a missing ATS keyword genuinely applies to real experience, "
        "incorporate it naturally — never fabricate to include a keyword.",
        user_msg,
        "rewritten_bullets",
        _bullets_schema(sections),
    )

    # Validate the semantic constraint the schema can't express; retry once.
    if not _counts_ok(result, counts):
        result = _structured(
            "Return the SAME sections with EXACT bullet counts per section: "
            + json.dumps(counts),
            f"Fix this output to match the required counts exactly, preserving "
            f"content quality:\n{json.dumps(result, ensure_ascii=False)}",
            "rewritten_bullets",
            _bullets_schema(sections),
        )
        if not _counts_ok(result, counts):
            raise ValueError(f"Bullet counts mismatch after retry: "
                             f"wanted {counts}, got { {k: len(v) for k, v in result.items()} }")
    return result


def _counts_ok(result: dict, counts: dict[str, int]) -> bool:
    return all(len(result.get(sec, [])) == n for sec, n in counts.items())


# ---------------------------------------------------------------------------
# Stage 3 — Cover letter
# ---------------------------------------------------------------------------
def run_cover_letter(profile: dict, jd_text: str, match_summary: str,
                     talking_points: list[str], user_notes: str | None) -> str:
    resp = _chat(
        "cover_letter_draft",
        messages=[
            {"role": "system", "content":
                "Write a compelling, specific cover letter body (salutation to "
                "sign-off). Plain text only. Use the talking points where they fit "
                "naturally; never invent experience. Keep it under 350 words."},
            {"role": "user", "content": json.dumps({
                "profile": profile,
                "job_description": jd_text,
                "match_summary": match_summary,
                "employer_talking_points": talking_points,
                "applicant_notes": user_notes,
            }, ensure_ascii=False)},
        ],
    )
    return resp.choices[0].message.content.strip()
