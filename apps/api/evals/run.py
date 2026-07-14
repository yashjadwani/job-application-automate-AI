"""Eval harness — runs the real pipeline stages against fixed cases and scores
the output. Costs real OpenAI money; run manually, not in CI/pytest.

Usage (from apps/api, with OPENAI_API_KEY in .env or the environment):
    py -m evals.run                # match + ATS + bullets + letter per case
    py -m evals.run --research     # also run the web-search research agent
    py -m evals.run --case ml_engineer_stretch

Scores per case:
  deterministic: bullet-count fidelity, ATS-keyword incorporation, guardrail
                 violations, latency, tokens (via captured usage)
  LLM judge:     truthfulness (no fabricated facts), JD relevance,
                 cover-letter quality — each 1–5 with a one-line reason

Results land in evals/results/<timestamp>.json tagged with PROMPT_VERSION and
model; the previous run is diffed automatically so prompt regressions surface.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import guardrails, stages, tools  # noqa: E402
from app.pipeline.agents import (Trace, ats_agent, match_analyst_agent,  # noqa: E402
                                  research_agent, rewrite_with_critic)
from evals.cases import CASES, CV, PROFILE  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "truthfulness": {"type": "integer"},
        "truthfulness_reason": {"type": "string"},
        "jd_relevance": {"type": "integer"},
        "jd_relevance_reason": {"type": "string"},
        "cover_letter_quality": {"type": "integer"},
        "cover_letter_reason": {"type": "string"},
    },
    "required": ["truthfulness", "truthfulness_reason", "jd_relevance",
                 "jd_relevance_reason", "cover_letter_quality",
                 "cover_letter_reason"],
    "additionalProperties": False,
}


def judge(case, bullets, cover_letter):
    return stages._structured(
        "You are a strict evaluator of AI-tailored job applications. Score 1-5 "
        "(5 best) with one-line reasons:\n"
        "- truthfulness: rewritten bullets contain ONLY facts supported by the "
        "original bullets (5 = nothing invented; 1 = fabricated experience)\n"
        "- jd_relevance: rewritten bullets emphasise what this JD actually asks "
        "for (5 = clearly targeted; 1 = generic)\n"
        "- cover_letter_quality: specific, natural, cliché-free, factual "
        "(5 = would impress; 1 = template slop)",
        json.dumps({
            "original_sections": CV["sections"],
            "rewritten_bullets": bullets,
            "job_description": case["jd"],
            "cover_letter": cover_letter,
        }, ensure_ascii=False),
        "eval_judgement", JUDGE_SCHEMA)


def run_case(case, with_research: bool) -> dict:
    trace = Trace()
    guardrails.set_budget(40)
    jd, _ = guardrails.sanitize_jd(case["jd"])
    t0 = time.perf_counter()

    research = None
    if with_research:
        research = research_agent(case["company"], jd, trace)

    match = match_analyst_agent(PROFILE, CV, jd, research, trace)
    ats = ats_agent(CV, jd, trace)
    bullets = rewrite_with_critic(PROFILE, CV, jd, ats["missing"], trace)
    cover = stages.run_cover_letter(
        PROFILE, jd, match["summary"],
        (research or {}).get("talking_points", []), None)

    elapsed = round(time.perf_counter() - t0, 1)

    # Deterministic metrics
    counts = {s["id"]: len(s["bullets"]) for s in CV["sections"]}
    violations = guardrails.validate_bullets(bullets, counts)
    all_text = " ".join(b for bs in bullets.values() for b in bs)
    incorporated = tools.keyword_coverage(all_text, ats["missing"])["present"]

    verdict = judge(case, bullets, cover)
    revisions = sum(1 for e in trace.events if e["action"] == "requested revision")

    return {
        "case": case["id"],
        "latency_s": elapsed,
        "match_score": match["score"],
        "ats_score": ats["ats_score"],
        "counts_ok": not any("expected" in v for v in violations),
        "guardrail_violations": len(violations),
        "missing_keywords_incorporated":
            f"{len(incorporated)}/{len(ats['missing'])}",
        "critic_revisions": revisions,
        "judge": {k: verdict[k] for k in
                  ("truthfulness", "jd_relevance", "cover_letter_quality")},
        "judge_reasons": {k: verdict[k] for k in verdict if k.endswith("_reason")},
    }


def previous_result() -> dict | None:
    files = sorted(RESULTS_DIR.glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research", action="store_true",
                        help="include the web-search research agent (slower, costlier)")
    parser.add_argument("--case", help="run a single case id")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.case or c["id"] == args.case]
    if not cases:
        sys.exit(f"no case named {args.case!r}")

    prev = previous_result()
    results = []
    for case in cases:
        print(f"— running {case['id']} …", flush=True)
        try:
            results.append(run_case(case, args.research))
        except Exception as exc:
            results.append({"case": case["id"], "error": str(exc)[:300]})

    run_record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_version": stages.PROMPT_VERSION,
        "model": stages._model(),
        "with_research": args.research,
        "results": results,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{run_record['at'].replace(':', '-')}.json"
    out.write_text(json.dumps(run_record, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    # Report
    print(f"\n{'case':<26}{'lat':>6}{'match':>7}{'ats':>5}"
          f"{'truth':>7}{'relev':>7}{'letter':>8}{'rev':>5}")
    for r in results:
        if "error" in r:
            print(f"{r['case']:<26}  ERROR: {r['error'][:60]}")
            continue
        j = r["judge"]
        print(f"{r['case']:<26}{r['latency_s']:>5}s{r['match_score']:>7}"
              f"{r['ats_score']:>5}{j['truthfulness']:>7}{j['jd_relevance']:>7}"
              f"{j['cover_letter_quality']:>8}{r['critic_revisions']:>5}")
        if not r["counts_ok"]:
            print(f"{'':<26}!! bullet counts broken")

    if prev:
        print(f"\nvs previous run ({prev['at']}, prompts {prev['prompt_version']}):")
        prev_by_case = {r["case"]: r for r in prev["results"] if "judge" in r}
        for r in results:
            p = prev_by_case.get(r.get("case"))
            if not p or "judge" not in r:
                continue
            deltas = []
            for k in ("truthfulness", "jd_relevance", "cover_letter_quality"):
                d = r["judge"][k] - p["judge"][k]
                if d:
                    deltas.append(f"{k} {'+' if d > 0 else ''}{d}")
            print(f"  {r['case']:<24} {'; '.join(deltas) if deltas else 'no change'}")

    print(f"\nsaved → {out}")


if __name__ == "__main__":
    main()
