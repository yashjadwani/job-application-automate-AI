from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthedUser, CurrentUser
from .config import get_settings
from .routers import analyse, cv, exports, profile, telegram_bot

app = FastAPI(title="CV Tailoring Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/verify")
def auth_verify(user: AuthedUser = CurrentUser):
    return {"user_id": user.user_id, "email": user.email}


app.include_router(profile.router)
app.include_router(cv.router)
app.include_router(analyse.router)
app.include_router(exports.router)
app.include_router(telegram_bot.router)
