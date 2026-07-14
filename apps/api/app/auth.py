"""Supabase JWT verification — asymmetric ES256 only.

Every request carries `Authorization: Bearer <supabase_jwt>`. We verify the
token's signature (ES256, public key from Supabase's JWKS endpoint), algorithm,
audience, issuer and expiry, then pass the SAME token through to
PostgREST/Storage so Postgres RLS enforces tenant isolation — the service-role
key is never used on browser-originated request paths.

No shared secret lives on the API: verification uses only public keys, so an
API compromise cannot forge a token. Tokens signed with any algorithm other
than ES256 (e.g. HS256) are rejected outright, which also closes the classic
algorithm-confusion attack.

Supabase setup: Project → Auth → JWT keys → use asymmetric keys (ECC / ES256).
"""

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from .config import get_settings

_AUDIENCE = "authenticated"
_ALGORITHMS = ["ES256"]
# Every token must carry these claims; verify_exp/aud/iss are on by default.
_DECODE_OPTIONS = {"require": ["exp", "sub", "aud", "iss"]}
_LEEWAY = 30  # seconds of clock-skew tolerance

_jwks_client: PyJWKClient | None = None


def _issuer() -> str:
    s = get_settings()
    return s.supabase_jwt_issuer or (s.supabase_url.rstrip("/") + "/auth/v1")


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = get_settings().supabase_url.rstrip("/")
        _jwks_client = PyJWKClient(
            f"{url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,   # cache fetched keys; refetches on unknown kid (rotation)
            lifespan=600,
        )
    return _jwks_client


@dataclass
class AuthedUser:
    user_id: str
    email: str | None
    token: str  # raw JWT, passed through to Supabase for RLS


def verify_token(token: str) -> AuthedUser:
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Malformed token: {exc}") from exc

    if alg not in _ALGORITHMS:
        raise HTTPException(status_code=401,
                            detail=f"Unsupported token algorithm: {alg} (expected ES256)")

    try:
        key = _get_jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
            issuer=_issuer(),
            leeway=_LEEWAY,
            options=_DECODE_OPTIONS,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return AuthedUser(user_id=sub, email=claims.get("email"), token=token)


def get_current_user(request: Request) -> AuthedUser:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_token(header.removeprefix("Bearer "))


CurrentUser = Depends(get_current_user)
