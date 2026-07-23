import base64
import hashlib
import hmac
import os
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from switchgear.config import Settings, get_settings

router = APIRouter()

SESSION_MAX_AGE = 30 * 86400
LOGIN_CSRF_MAX_AGE = 600


def _serializer(settings: Settings, salt: str = "session") -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=salt)


def sign_session(settings: Settings, email: str) -> str:
    return _serializer(settings).dumps({"email": email})


def verify_session(settings: Settings, cookie: str | None) -> str | None:
    if not cookie:
        return None
    try:
        data = _serializer(settings).loads(cookie, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    email = data.get("email")
    return email if email == settings.owner_email else None


def verify_password(password: str, encoded: str) -> bool:
    try:
        separator = ":" if ":" in encoded else "$"
        algorithm, n, r, p, salt, expected = encoded.split(separator, 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=base64.urlsafe_b64decode(salt),
            n=int(n), r=int(r), p=int(p),
        )
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt:16384:8:1:" + base64.urlsafe_b64encode(salt).decode() + ":" + \
        base64.urlsafe_b64encode(digest).decode()


def login_csrf(settings: Settings) -> str:
    return _serializer(settings, salt="login-csrf").dumps(secrets.token_urlsafe(16))


@router.post("/auth/local")
async def local_login(request: Request, settings: Settings = Depends(get_settings)):
    fields = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    token = (fields.get("csrf") or [""])[0]
    cookie = request.cookies.get("login_csrf")
    if not token or not cookie or not hmac.compare_digest(token, cookie):
        raise HTTPException(403, "invalid login csrf token")
    try:
        _serializer(settings, salt="login-csrf").loads(token, max_age=LOGIN_CSRF_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(403, "invalid login csrf token") from None
    password = (fields.get("password") or [""])[0]
    if not verify_password(password, settings.local_password_hash):
        raise HTTPException(403, "invalid credentials")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("session", sign_session(settings, settings.owner_email), httponly=True,
                        secure=settings.cookie_secure, samesite=settings.cookie_samesite,
                        max_age=SESSION_MAX_AGE)
    response.delete_cookie("login_csrf")
    return response


async def require_owner(request: Request, settings: Settings = Depends(get_settings)) -> str:
    email = verify_session(settings, request.cookies.get("session"))
    if email is None:
        raise HTTPException(401, "not authenticated")
    return email


@router.post("/auth/logout")
async def logout(settings: Settings = Depends(get_settings)):
    response = JSONResponse({"ok": True})
    response.delete_cookie("session", secure=settings.cookie_secure,
                           samesite=settings.cookie_samesite)
    return response
