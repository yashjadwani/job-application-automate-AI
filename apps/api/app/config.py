from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Ignore unknown keys in .env (e.g. vars from older versions of the app)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    # JWTs are verified with asymmetric ES256 keys from the JWKS endpoint —
    # no shared secret on the API. Optional issuer override for custom domains;
    # defaults to {supabase_url}/auth/v1.
    supabase_jwt_issuer: str = ""
    # Service role — used ONLY by the Telegram webhook path (see db.py).
    supabase_service_role_key: str = ""

    # Telegram bot (optional — bot features disabled when empty)
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = ""

    tavily_api_key: str = ""

    # --- LLM providers -----------------------------------------------------
    # Agents run on OpenCode; on ANY failure they fall back to OpenRouter
    # (primary → fallback model). The planner (orchestrator) runs on Gemini,
    # itself falling back to the OpenRouter models. See app/pipeline/providers.py
    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    opencode_model: str = "deepseek-v4-flash-free"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_llm_primary: str = "openai/gpt-oss-20b:free"
    openrouter_llm_fallback: str = "nvidia/nemotron-3-super-120b-a12b:free"

    # Planner / orchestrator model (Gemini). Can be Google's OpenAI-compatible
    # endpoint, or leave the key empty to run the planner on OpenRouter instead.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3-flash-preview"
    #gemini_model: str = "gemini-2.5-flash-lite"
    #gemini_model: str = "gemini-2.5-flash"

    # Approximate $/1M tokens for cost tracking (flat across models; 0 = skip)
    openai_input_cost_per_1m: float = 0.0
    openai_output_cost_per_1m: float = 0.0

    monthly_analysis_quota: int = 30
    # Pause the pipeline for bullet review before writing the cover letter
    hitl_enabled: bool = True

    # Planner-based dynamic orchestration (opt-in). When false, the original
    # fixed-order linear pipeline runs — fully preserved as the fallback.
    planner_enabled: bool = False
    planner_max_retries: int = 1        # per-agent retries before skip/fail
    planner_max_revisions: int = 2      # rewrite<->critic loop cap

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
