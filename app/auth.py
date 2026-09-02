"""账号注册、密码校验和基于 HttpOnly Cookie 的会话管理。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import Request, Response

from . import storage

SESSION_COOKIE = "latex_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
PBKDF2_ROUNDS = 310_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt), int(rounds)
        )
        return hmac.compare_digest(_b64(digest), expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名需为 3-32 位字母、数字或下划线")
    if len(password or "") < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 位")
    return username, password


def register(username: str, password: str) -> dict:
    username, password = validate_credentials(username, password)
    return storage.create_user(username, hash_password(password))


def authenticate(username: str, password: str) -> dict:
    username = (username or "").strip()
    user = storage.find_user_by_username(username)
    if user is None or not verify_password(password or "", user["password_hash"]):
        raise ValueError("用户名或密码错误")
    user.pop("password_hash", None)
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(response: Response, user_id: int) -> None:
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    storage.create_session(_token_hash(token), user_id, now, now + SESSION_MAX_AGE)
    secure = os.environ.get("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def current_user(request: Request) -> dict | None:
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 256:
        return None
    user = storage.find_user_by_session(_token_hash(token), int(time.time()))
    request.state.user = user
    return user


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise PermissionError("请先登录")
    return user


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        storage.delete_session(_token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
