"""Supabase client factories.

user_client    — acts AS the user (JWT pass-through, RLS enforced). All web
                 API request paths use this. The service-role key is never
                 used for browser-originated requests.
service_client — service-role, bypasses RLS. Used ONLY by the Telegram
                 webhook path, which authenticates via chat_id linkage and has
                 no user JWT to pass through. Every query in that module must
                 filter by the resolved user_id explicitly.
"""

from supabase import Client, create_client

from .config import get_settings


def user_client(user_token: str) -> Client:
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(user_token)
    # Storage requests also authorize as the user so bucket policies apply.
    client.storage._client.headers["Authorization"] = f"Bearer {user_token}"
    return client


def service_client() -> Client:
    settings = get_settings()
    if not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
