"""Multi-provider LLM routing with automatic fallback.

Roles decide the ordered chain of (provider, model) endpoints to try:

  agent    → OpenCode  →  OpenRouter(primary)  →  OpenRouter(fallback)
  planner  → Gemini    →  OpenRouter(primary)  →  OpenRouter(fallback)

`_chat` (in stages.py) walks the chain: it uses the first endpoint, and on any
transient failure moves to the next. Every attempt — success or failure — is
logged to llm_calls with its provider, model, latency, tokens and response, so a
fallback is fully visible in telemetry.

Endpoints whose api_key is empty are skipped, so the system degrades cleanly to
whatever providers are actually configured.
"""

from dataclasses import dataclass

from openai import OpenAI

from ..config import get_settings


@dataclass(frozen=True)
class Endpoint:
    provider: str
    model: str
    base_url: str
    api_key: str


def _providers() -> dict[str, tuple[str, str]]:
    s = get_settings()
    return {
        "opencode": (s.opencode_base_url, s.opencode_api_key),
        "openrouter": (s.openrouter_base_url, s.openrouter_api_key),
        "gemini": (s.gemini_base_url, s.gemini_api_key),
    }


def _ep(provider: str, model: str) -> Endpoint:
    base, key = _providers()[provider]
    return Endpoint(provider, model, base, key)


def _openrouter_fallbacks() -> list[Endpoint]:
    s = get_settings()
    return [_ep("openrouter", s.openrouter_llm_primary),
            _ep("openrouter", s.openrouter_llm_fallback)]


def agent_chain() -> list[Endpoint]:
    s = get_settings()
    chain = [_ep("opencode", s.opencode_model), *_openrouter_fallbacks()]
    return [e for e in chain if e.api_key]


def planner_chain() -> list[Endpoint]:
    s = get_settings()
    chain = [_ep("gemini", s.gemini_model), *_openrouter_fallbacks()]
    return [e for e in chain if e.api_key]


def chain_for(role: str) -> list[Endpoint]:
    chain = planner_chain() if role == "planner" else agent_chain()
    # If a role has nothing configured, borrow whatever is configured.
    return chain or agent_chain() or planner_chain()


# Cache one client per provider (keyed by base_url so config changes rebuild).
_clients: dict[str, OpenAI] = {}


def client_for(ep: Endpoint) -> OpenAI:
    key = f"{ep.provider}:{ep.base_url}"
    if key not in _clients:
        _clients[key] = OpenAI(api_key=ep.api_key, base_url=ep.base_url or None)
    return _clients[key]
