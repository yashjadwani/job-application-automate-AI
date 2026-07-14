import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from supabase import Client

from ..auth import AuthedUser, CurrentUser
from ..db import user_client
from ..docx_parser import rewrite_docx
from ..pdf import cover_letter_pdf, docx_to_pdf

router = APIRouter(tags=["exports"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------------------
# Shared builders (also used by the Telegram bot)
# ---------------------------------------------------------------------------
def load_completed_analysis(client: Client, user_id: str, analysis_id: str) -> dict:
    rows = (client.table("analyses").select("*")
            .eq("id", analysis_id).eq("user_id", user_id).execute()).data
    if not rows:
        raise HTTPException(404, "Analysis not found")
    analysis = rows[0]
    if analysis["status"] != "done" or not analysis.get("rewritten_bullets"):
        raise HTTPException(409, "Analysis is not complete yet")
    return analysis


def build_tailored_docx(client: Client, user_id: str, analysis: dict) -> bytes:
    cv_rows = (client.table("cv_structure").select("*")
               .eq("user_id", user_id).execute()).data
    if not cv_rows or not cv_rows[0].get("original_docx_url"):
        raise HTTPException(409, "Original CV not found in storage")
    cv = cv_rows[0]
    original = client.storage.from_("cv-originals").download(cv["original_docx_url"])
    tailored = rewrite_docx(original, cv["sections"], analysis["rewritten_bullets"])

    export_path = f"{user_id}/{analysis['id']}/cv.docx"
    try:
        client.storage.from_("exports").upload(
            export_path, tailored, {"content-type": DOCX_MIME, "upsert": "true"})
    except Exception:
        pass  # persistence is best-effort; the download itself must not fail
    return tailored


def build_cover_pdf(client: Client, user_id: str, analysis: dict) -> bytes:
    if not analysis.get("cover_letter_text"):
        raise HTTPException(409, "No cover letter on this analysis")
    prof_rows = (client.table("profiles").select("*")
                 .eq("id", user_id).execute()).data
    profile = prof_rows[0] if prof_rows else {}
    contact = " · ".join(x for x in [profile.get("email"), profile.get("linkedin_url")] if x)
    try:
        pdf = cover_letter_pdf(profile.get("name") or "", contact,
                               analysis["cover_letter_text"])
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc

    try:
        client.storage.from_("exports").upload(
            f"{user_id}/{analysis['id']}/cover_letter.pdf", pdf,
            {"content-type": "application/pdf", "upsert": "true"})
    except Exception:
        pass
    return pdf


def _filename(analysis: dict, stem: str, ext: str) -> str:
    company = (analysis.get("company_name") or "tailored").replace(" ", "_")
    return f"{stem}_{company}.{ext}"


def _stream(data: bytes, media_type: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/export/docx/{analysis_id}")
def export_docx(analysis_id: str, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    analysis = load_completed_analysis(client, user.user_id, analysis_id)
    tailored = build_tailored_docx(client, user.user_id, analysis)
    return _stream(tailored, DOCX_MIME, _filename(analysis, "CV", "docx"))


@router.post("/export/pdf/{analysis_id}")
def export_cv_pdf(analysis_id: str, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    analysis = load_completed_analysis(client, user.user_id, analysis_id)
    tailored = build_tailored_docx(client, user.user_id, analysis)
    try:
        pdf = docx_to_pdf(tailored)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"PDF conversion failed: {exc}") from exc

    try:
        client.storage.from_("exports").upload(
            f"{user.user_id}/{analysis_id}/cv.pdf", pdf,
            {"content-type": "application/pdf", "upsert": "true"})
    except Exception:
        pass
    return _stream(pdf, "application/pdf", _filename(analysis, "CV", "pdf"))


@router.post("/export/cover-pdf/{analysis_id}")
def export_cover_pdf(analysis_id: str, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    analysis = load_completed_analysis(client, user.user_id, analysis_id)
    pdf = build_cover_pdf(client, user.user_id, analysis)
    return _stream(pdf, "application/pdf", _filename(analysis, "Cover_Letter", "pdf"))
