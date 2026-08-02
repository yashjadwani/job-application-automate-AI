"""Shared working memory + session memory passed between agents.

One AnalysisContext flows through the whole planner run. Agents READ their
inputs from it and WRITE their outputs back, so nothing is ever reloaded or
recomputed. It also carries session memory (what's done, what failed, retry
counts, planner decisions) so the Planner never schedules duplicate work.
"""

from dataclasses import dataclass, field

from .agents import Trace

# Base inputs that are always present (satisfy `requires` without an agent)
_BASE_KEYS = {"cv", "profile", "jd_text", "jd_safe", "company", "user_notes"}


@dataclass
class AnalysisContext:
    # --- inputs -----------------------------------------------------------
    user_id: str
    analysis_id: str
    profile: dict
    cv: dict
    jd_text: str
    company: str | None = None
    user_notes: str | None = None

    # --- working memory (agent outputs) ----------------------------------
    data: dict = field(default_factory=dict)

    # --- session memory ---------------------------------------------------
    completed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    retries: dict[str, int] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    trace: Trace = field(default_factory=Trace)

    # Set true when resuming after human approval (skips the HITL pause)
    approved: bool = False

    # -- helpers -----------------------------------------------------------
    def has(self, key: str) -> bool:
        """A required key is satisfied if it's a populated agent output or a
        present base input."""
        if key in _BASE_KEYS:
            return getattr(self, key, None) is not None or key in self.data
        return self.data.get(key) is not None

    def sections(self) -> list[dict]:
        return [s for s in self.cv.get("sections", []) if s.get("bullets")]

    def note_decision(self, plan: list[str], reasoning: str):
        self.decisions.append({"plan": plan, "reasoning": reasoning})
