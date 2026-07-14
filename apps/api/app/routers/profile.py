from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import AuthedUser, CurrentUser
from ..db import user_client

router = APIRouter(tags=["profile"])


class ProfileIn(BaseModel):
    name: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    bio: str | None = None
    skills: list[str] = []
    additional_context: str | None = None


@router.get("/profile")
def get_profile(user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    profile = client.table("profiles").select("*").eq("id", user.user_id).execute()
    cv = client.table("cv_structure").select("*").eq("user_id", user.user_id).execute()
    return {
        "profile": profile.data[0] if profile.data else None,
        "cv": cv.data[0] if cv.data else None,
    }


@router.post("/profile")
def upsert_profile(body: ProfileIn, user: AuthedUser = CurrentUser):
    client = user_client(user.token)
    row = {"id": user.user_id, **body.model_dump(exclude_none=True)}
    result = client.table("profiles").upsert(row).execute()
    return result.data[0]
