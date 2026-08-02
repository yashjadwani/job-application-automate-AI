from fastapi import APIRouter, HTTPException, UploadFile

from ..auth import AuthedUser, CurrentUser
from ..db import user_client
from ..docx_parser import parse_docx

router = APIRouter(tags=["cv"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/cv/upload")
async def upload_cv(file: UploadFile, user: AuthedUser = CurrentUser):
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Please upload a .docx file")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 5 MB)")

    try:
        parsed = parse_docx(data)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse DOCX: {exc}") from exc

    if not any(s.get("bullets") for s in parsed["sections"]):
        raise HTTPException(422, "No bulleted sections found — this CV layout "
                                 "isn't supported yet (plain paragraphs / text boxes).")

    client = user_client(user.token)
    path = f"{user.user_id}/cv_original.docx"
    client.storage.from_("cv-originals").upload(
        path, data, {"content-type": DOCX_MIME, "upsert": "true"})

    row = {
        "user_id": user.user_id,
        "personal": parsed["personal"],
        "sections": parsed["sections"],
        "original_docx_url": path,
        "original_filename": file.filename,
        "links": parsed["links"],
    }
    result = client.table("cv_structure").upsert(row, on_conflict="user_id").execute()
    return result.data[0]


@router.put("/cv/sections")
def update_sections(sections: list[dict], user: AuthedUser = CurrentUser):
    """Manual inline bullet edits from the CV Manager."""
    client = user_client(user.token)
    result = (client.table("cv_structure").update({"sections": sections})
              .eq("user_id", user.user_id).execute())
    if not result.data:
        raise HTTPException(404, "No CV uploaded yet")
    return result.data[0]
