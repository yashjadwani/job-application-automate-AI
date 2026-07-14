"""The agentic analysis pipeline (PRD §3.1) — OpenAI, 4 stages + ATS scoring.

Stage 0  Employer research   — Responses API + web_search tool, cited findings
Stage 1  Match & gap         — strict Structured Outputs
Stage 1b ATS keyword scoring — strict Structured Outputs (added post-PRD)
Stage 2  Bullet rewriter     — strict Structured Outputs, bullet counts preserved
Stage 3  Cover letter        — plain text

All stages are synchronous functions; the worker in worker.py sequences them
and advances analyses.status so the frontend can poll.
"""

import json
import time

from openai import OpenAI

# Bump when any prompt changes — recorded in eval results so quality shifts
# can be traced to prompt edits (git blame gives the diff).
PROMPT_VERSION = "2026-07-08.1"  # strict formatting rules added to rewriter

from .. import telemetry
from ..config import get_settings
from .guardrails import spend


def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.openai_api_key,
                  base_url=s.openai_base_url or None)


def _model() -> str:
    return get_settings().openai_model


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _chat(label: str, **kwargs):
    """All chat.completions calls go through here: budget + telemetry."""
    spend()
    t0 = time.perf_counter()
    try:
        resp = _client().chat.completions.create(model=_model(), **kwargs)
    except Exception as exc:
        telemetry.record(label, _model(), _ms(t0), kind="chat",
                         status="error", error=str(exc))
        raise
    usage = getattr(resp, "usage", None)
    telemetry.record(
        label, getattr(resp, "model", _model()), _ms(t0),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None))
    return resp


def _respond(label: str, **kwargs):
    """All Responses API calls (hosted tools like web_search) go through here."""
    spend()
    t0 = time.perf_counter()
    try:
        resp = _client().responses.create(model=_model(), **kwargs)
    except Exception as exc:
        telemetry.record(label, _model(), _ms(t0), kind="responses",
                         status="error", error=str(exc))
        raise
    usage = getattr(resp, "usage", None)
    telemetry.record(
        label, getattr(resp, "model", _model()), _ms(t0),
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(usage, "total_tokens", None),
        kind="responses")
    return resp


# ---------------------------------------------------------------------------
# Stage 0 — Employer research (web search, citations required)
# ---------------------------------------------------------------------------
RESEARCH_PROMPT = """You are an employer-research analyst helping a job applicant.
Company: {company}
Role (from the job description): {jd_excerpt}

Research this company on the web and surface NON-OBVIOUS intel the applicant
would not think to look up: culture signals and red flags, recent news, funding
or layoffs, leadership changes, interview process reports, and strategic bets.

Rules:
- Every finding MUST be grounded in a source you actually found. Discard
  anything you cannot cite.
- Prefer the last 12 months.
- Finish with 3-5 talking points the applicant can use in a cover letter or
  interview.

Return ONLY JSON in exactly this shape (no markdown fence):
{{"findings": [{{"category": "...", "insight": "...", "sources": ["url"]}}],
  "talking_points": ["..."]}}"""


def run_research(company: str, jd_text: str) -> dict:
    resp = _respond(
        "research_web_search",
        tools=[{"type": "web_search"}],
        input=RESEARCH_PROMPT.format(company=company, jd_excerpt=jd_text[:1500]),
    )
    text = resp.output_text.strip()
    # Tolerate a stray fence despite instructions.
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    data = json.loads(text)
    # Enforce the citation rule server-side too.
    data["findings"] = [f for f in data.get("findings", []) if f.get("sources")]
    data.setdefault("talking_points", [])
    return data


# ---------------------------------------------------------------------------
# Structured-output helper (strict JSON schema)
# ---------------------------------------------------------------------------
def _structured(system: str, user: str, schema_name: str, schema: dict) -> dict:
    resp = _chat(
        schema_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    )
    return json.loads(resp.choices[0].message.content)


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
