"""Agent Registry + Tool Registry.

The Planner and orchestrator never call run_research()/run_ats() directly; they
request agents and tools from these registries. Adding a new specialist agent
(Interview Prep, Salary Insights, …) is: write its run function, register an
AgentSpec, done — no orchestration code changes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from . import agents, stages, tools
from .context import AnalysisContext

# ===========================================================================
# Tool Registry — planner-discoverable capabilities behind a common interface
# ===========================================================================
@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict                 # OpenAI function-tool schema
    impl: Callable               # the callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def catalog(self) -> list[dict]:
        return [{"name": t.name, "description": t.description}
                for t in self._tools.values()]


def build_tool_registry() -> ToolRegistry:
    """Global, stateless tools. Per-user CV tools are bound per request (they
    close over the user's data) via tools.build_cv_toolkit()."""
    reg = ToolRegistry()
    reg.register(ToolSpec(
        "web_search", "Search the public web (Tavily). Returns titles/URLs/snippets.",
        tools.SEARCH_TOOL_SCHEMA[0], tools.web_search))
    reg.register(ToolSpec(
        "keyword_coverage",
        "Deterministically check which keywords literally appear in a text.",
        {"type": "function", "function": {
            "name": "keyword_coverage",
            "description": "Which keywords appear in the CV text.",
            "parameters": {"type": "object", "properties": {
                "cv_text": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}}},
                "required": ["cv_text", "keywords"],
                "additionalProperties": False}}},
        tools.keyword_coverage))
    # Extension point: register salary_lookup, interview_questions,
    # company_lookup, MCP tools here — the Planner discovers them via catalog().
    return reg


# ===========================================================================
# Agent Registry
# ===========================================================================
@dataclass
class AgentSpec:
    name: str
    description: str            # shown to the Planner
    requires: list[str]         # context keys needed before running
    produces: list[str]         # context keys written
    status: str                 # analyses.status while this agent runs
    run: Callable[[AnalysisContext], None]
    optional: bool = False      # failure → skip instead of fail the run
    repeatable: bool = False     # may be scheduled more than once
    metadata: dict = field(default_factory=dict)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec):
        self._agents[spec.name] = spec

    def get(self, name: str) -> AgentSpec | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents)

    def all(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def producer_of(self, key: str) -> str | None:
        for spec in self._agents.values():
            if key in spec.produces:
                return spec.name
        return None


# --- Agent adapters: wrap the existing (tested) agent functions to read/write
#     the shared context. The specialist logic itself is unchanged. ----------
def _research(ctx: AnalysisContext):
    ctx.data["research"] = agents.research_agent(ctx.company, ctx.data["jd_safe"], ctx.trace)


def _cv_analysis(ctx: AnalysisContext):
    ctx.data["match"] = agents.match_analyst_agent(
        ctx.profile, ctx.cv, ctx.data["jd_safe"], ctx.data.get("research"), ctx.trace)


def _ats(ctx: AnalysisContext):
    ctx.data["ats"] = agents.ats_agent(ctx.cv, ctx.data["jd_safe"], ctx.trace)


def _rewrite(ctx: AnalysisContext):
    ats = ctx.data["ats"]
    critique = ctx.data.get("critique") or {}
    ctx.data["rewritten_bullets"] = stages.run_bullets(
        ctx.profile, ctx.cv, ctx.data["jd_safe"], ats["missing"],
        feedback=critique.get("issues"),
        previous=ctx.data.get("rewritten_bullets"))


def _critic(ctx: AnalysisContext):
    ctx.data["critique"] = agents.critique_bullets(
        ctx.sections(), ctx.data["rewritten_bullets"],
        ctx.data["jd_safe"], ctx.data["ats"]["missing"])


def _cover_letter(ctx: AnalysisContext):
    m = ctx.data["match"]
    tps = (ctx.data.get("research") or {}).get("talking_points", [])
    ctx.data["cover_letter"] = agents.cover_letter_agent(
        ctx.profile, ctx.data["jd_safe"], m["summary"], tps, ctx.user_notes, ctx.trace)


def build_agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(AgentSpec(
        "research", "Research the employer on the web; returns cited findings "
        "and talking points. Only useful when a company name is known.",
        requires=["company"], produces=["research"], status="researching",
        run=_research, optional=True))
    reg.register(AgentSpec(
        "cv_analysis", "Score how well the CV/profile match the job (0-100) and "
        "list gaps. Reads the CV via tools.",
        requires=["cv", "profile"], produces=["match"], status="analysing",
        run=_cv_analysis))
    reg.register(AgentSpec(
        "ats", "Extract ATS keywords from the JD and compute deterministic "
        "coverage against the CV.",
        requires=["cv"], produces=["ats"], status="analysing", run=_ats))
    reg.register(AgentSpec(
        "rewrite", "Rewrite CV bullets to match the JD (counts preserved, no "
        "fabrication). Can run again with critic feedback.",
        requires=["ats", "match"], produces=["rewritten_bullets"],
        status="writing", run=_rewrite, repeatable=True))
    reg.register(AgentSpec(
        "critic", "Review rewritten bullets for truthfulness and JD alignment; "
        "returns approval + issues.",
        requires=["rewritten_bullets"], produces=["critique"], status="writing",
        run=_critic, repeatable=True, optional=True))
    reg.register(AgentSpec(
        "cover_letter", "Write and edit a tailored cover letter.",
        requires=["match"], produces=["cover_letter"], status="reviewing",
        run=_cover_letter))
    return reg
