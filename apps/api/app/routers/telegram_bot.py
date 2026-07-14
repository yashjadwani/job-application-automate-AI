"""Telegram webhook + link-code endpoints."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .. import telegram
from ..auth import AuthedUser, CurrentUser
from ..config import get_settings
from ..db import service_client, user_client
from ..pipeline.worker import resume_analysis, run_analysis

router = APIRouter(tags=["telegram"])
log = logging.getLogger("telegram")


@router.post("/telegram/link-code")
def make_link_code(user: AuthedUser = CurrentUser):
    """Web app calls this (user-authed); shows the code to send to the bot."""
    if not telegram.enabled():
        raise HTTPException(501, "Telegram bot is not configured")
    client = user_client(user.token)
    code = telegram.create_link_code(client, user.user_id)
    return {"code": code, "bot_username": get_settings().telegram_bot_username}


@router.post("/telegram/webhook")
async def webhook(request: Request, tasks: BackgroundTasks):
    settings = get_settings()
    if not telegram.enabled():
        raise HTTPException(404)
    # Telegram echoes back the secret we registered with setWebhook
    if settings.telegram_webhook_secret and (
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        != settings.telegram_webhook_secret
    ):
        raise HTTPException(403)

    update = await request.json()
    sclient = service_client()

    def run_pipeline(user_id: str, chat_id: int, jd_text: str, company: str | None):
        # Quota check mirrors the web path
        from datetime import datetime, timezone
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        used = (sclient.table("analyses").select("id", count="exact")
                .eq("user_id", user_id).gte("created_at", month_start)
                .execute()).count or 0
        quota = get_settings().monthly_analysis_quota
        if used >= quota:
            telegram.send_message(chat_id, f"Monthly quota reached ({quota}). "
                                           "Resets on the 1st.")
            return

        cv_rows = (sclient.table("cv_structure").select("*")
                   .eq("user_id", user_id).execute()).data
        if not cv_rows:
            telegram.send_message(chat_id, "Upload your CV in the web app first, "
                                           "then send me the JD again.")
            return
        prof_rows = (sclient.table("profiles").select("*")
                     .eq("id", user_id).execute()).data
        profile = prof_rows[0] if prof_rows else {}

        row = (sclient.table("analyses").insert({
            "user_id": user_id,
            "jd_text": jd_text,
            "company_name": company,
            "status": "pending",
        }).execute()).data[0]

        telegram.send_message(
            chat_id,
            ("🔍 On it — researching *" + company + "*…") if company
            else "⚙️ On it — analysing your match…")

        tasks.add_task(run_analysis, sclient, user_id, row["id"], profile,
                       cv_rows[0], jd_text, company, None, chat_id)

    def resume_pipeline(user_id: str, chat_id: int, analysis_id: str):
        tasks.add_task(resume_analysis, sclient, user_id, analysis_id, chat_id)

    try:
        telegram.handle_update(update, sclient, run_pipeline, resume_pipeline)
    except Exception:
        log.exception("webhook handling failed")
    # Always 200 — Telegram retries anything else, which would duplicate work
    return {"ok": True}
