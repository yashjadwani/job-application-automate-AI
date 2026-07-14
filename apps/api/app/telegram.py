"""Telegram bot: account linking, JD analysis from chat, completion pings.

Webhook-based (fits Modal serverless — no long polling). The webhook has no
user JWT, so this module uses the service-role client with EVERY query
explicitly filtered by the user_id resolved from the chat_id linkage.
"""

import logging
import secrets

import httpx

from .config import get_settings

log = logging.getLogger("telegram")

MAX_MSG = 4000  # Telegram hard limit is 4096


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{get_settings().telegram_bot_token}/{method}"


def enabled() -> bool:
    return bool(get_settings().telegram_bot_token)


def send_message(chat_id: int, text: str, markdown: bool = True):
    if not enabled():
        return
    try:
        httpx.post(_api("sendMessage"), json={
            "chat_id": chat_id,
            "text": text[:MAX_MSG],
            **({"parse_mode": "Markdown"} if markdown else {}),
            "disable_web_page_preview": True,
        }, timeout=15)
    except Exception:
        log.exception("sendMessage failed")


def send_document(chat_id: int, filename: str, data: bytes, caption: str = ""):
    if not enabled():
        return
    try:
        httpx.post(_api("sendDocument"),
                   data={"chat_id": str(chat_id), "caption": caption[:1000]},
                   files={"document": (filename, data)},
                   timeout=60)
    except Exception:
        log.exception("sendDocument failed")


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------
def create_link_code(client, user_id: str) -> str:
    """Called from the web app (user-authed route) — issue a one-time code."""
    code = secrets.token_hex(4)  # 8 chars, easy to type
    client.table("telegram_links").upsert({
        "user_id": user_id, "link_code": code, "chat_id": None,
    }, on_conflict="user_id").execute()
    return code


def resolve_user(sclient, chat_id: int) -> str | None:
    rows = (sclient.table("telegram_links").select("user_id")
            .eq("chat_id", chat_id).execute()).data
    return rows[0]["user_id"] if rows else None


def notify_done(chat_id: int, analysis: dict):
    """Completion ping — used for BOTH web- and bot-initiated analyses."""
    title = analysis.get("jd_title") or analysis.get("company_name") or "your application"
    if analysis.get("status") == "failed":
        send_message(chat_id, f"❌ Analysis for *{title}* failed. Try again in the app.")
        return
    gaps = (analysis.get("gaps") or [])[:3]
    missing = ((analysis.get("ats_keywords") or {}).get("missing") or [])[:4]
    lines = [
        f"✅ *{title}* — analysis complete",
        f"Match *{analysis.get('match_score', '—')}*/100 · ATS *{analysis.get('ats_score', '—')}*/100",
    ]
    if gaps:
        lines.append("Gaps: " + ", ".join(gaps))
    if missing:
        lines.append("Missing keywords: " + ", ".join(missing))
    research = analysis.get("employer_research") or {}
    points = (research.get("talking_points") or [])[:2]
    if points:
        lines.append("💡 " + " / ".join(points))
    send_message(chat_id, "\n".join(lines))


# ---------------------------------------------------------------------------
# Webhook conversation
# ---------------------------------------------------------------------------
HELP = (
    "*CV Tailor bot*\n\n"
    "Paste a full job description and I'll research the company, score your "
    "match, rewrite your CV and send it back as a DOCX.\n\n"
    "Tip: start the first line with `Company: <name>` for employer research.\n\n"
    "/status — latest analysis\n"
    "/approve — approve bullets awaiting review\n"
    "/quota — monthly usage\n"
    "/help — this message"
)

NOT_LINKED = (
    "This chat isn't linked yet. Open your *Profile* page in the web app, "
    "tap *Connect Telegram*, and send me the code like:\n`/start YOURCODE`"
)


def handle_update(update: dict, sclient, run_pipeline,
                  resume_pipeline=None) -> None:
    """Process one webhook update. `run_pipeline(user_id, chat_id, jd, company)`
    and `resume_pipeline(user_id, chat_id, analysis_id)` are injected by the
    router to avoid a circular import."""
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    # --- /start [code] ------------------------------------------------------
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            send_message(chat_id, NOT_LINKED)
            return
        rows = (sclient.table("telegram_links").select("user_id")
                .eq("link_code", code).execute()).data
        if not rows:
            send_message(chat_id, "That code didn't match. Generate a fresh one "
                                  "from your Profile page.")
            return
        (sclient.table("telegram_links")
         .update({"chat_id": chat_id, "link_code": None})
         .eq("user_id", rows[0]["user_id"]).execute())
        send_message(chat_id, "🔗 Connected! Paste a job description whenever "
                              "you're ready.\n\n" + HELP)
        return

    user_id = resolve_user(sclient, chat_id)
    if not user_id:
        send_message(chat_id, NOT_LINKED)
        return

    # --- commands -----------------------------------------------------------
    if text.startswith("/help"):
        send_message(chat_id, HELP)
        return

    if text.startswith("/status"):
        rows = (sclient.table("analyses")
                .select("jd_title, company_name, status, match_score, ats_score")
                .eq("user_id", user_id)
                .order("created_at", desc=True).limit(1).execute()).data
        if not rows:
            send_message(chat_id, "No analyses yet — paste a job description to start.")
        else:
            a = rows[0]
            name = a["jd_title"] or a["company_name"] or "Latest"
            if a["status"] == "done":
                send_message(chat_id, f"*{name}*: done — match {a['match_score']}/100, "
                                      f"ATS {a['ats_score']}/100")
            else:
                send_message(chat_id, f"*{name}*: {a['status']}…")
        return

    if text.startswith("/approve"):
        rows = (sclient.table("analyses").select("id, jd_title, company_name")
                .eq("user_id", user_id).eq("status", "awaiting_approval")
                .order("created_at", desc=True).limit(1).execute()).data
        if not rows:
            send_message(chat_id, "Nothing is awaiting approval right now.")
        elif resume_pipeline is None:
            send_message(chat_id, "Approval isn't available here — use the app.")
        else:
            name = rows[0]["jd_title"] or rows[0]["company_name"] or "analysis"
            send_message(chat_id, f"👍 Approved *{name}* — writing your cover letter…")
            resume_pipeline(user_id, chat_id, rows[0]["id"])
        return

    if text.startswith("/quota"):
        from datetime import datetime, timezone
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        used = (sclient.table("analyses").select("id", count="exact")
                .eq("user_id", user_id).gte("created_at", month_start)
                .execute()).count or 0
        quota = get_settings().monthly_analysis_quota
        send_message(chat_id, f"{used} of {quota} analyses used this month.")
        return

    if text.startswith("/"):
        send_message(chat_id, HELP)
        return

    # --- plain text: treat as a job description -----------------------------
    if len(text) < 100:
        send_message(chat_id, "That looks too short to be a job description. "
                              "Paste the full JD (or /help).")
        return

    company = None
    first, _, rest = text.partition("\n")
    if first.lower().startswith("company:"):
        company = first.split(":", 1)[1].strip()
        text = rest.strip()

    run_pipeline(user_id, chat_id, text, company)
