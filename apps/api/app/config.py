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

    openai_api_key: str = ""
    # OpenAI-compatible gateway (e.g. OpenCode). Empty = api.openai.com.
    openai_base_url: str = ""
    # PRD: exact model TBD — override via env once verified against current pricing.
    openai_model: str = "gpt-4o"
    # $ per 1M tokens for cost tracking in llm_calls (0 = don't compute cost)
    openai_input_cost_per_1m: float = 0.0
    openai_output_cost_per_1m: float = 0.0

    monthly_analysis_quota: int = 30
    # Pause the pipeline for bullet review before writing the cover letter
    hitl_enabled: bool = True

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
