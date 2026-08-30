"""Ana sayfa için kullanıcı adı + şifre girişi.

- `USER_LOGIN` ve `USER_PASSWORD` boşsa giriş zorunluluğu kapalıdır (herkes girer).
- Doluysa doğru bilgilerle giriş yapılınca `login_sessions` tablosuna opak bir
  jeton yazılır ve çerezde 1 yıl saklanır.

Not: /admin sayfası bundan bağımsız, kendi HTTP Basic korumasını kullanır.
Not: `login_sessions.email` sütunu geçmiş sürümden kalma addır; burada oturum
sahibinin kullanıcı adını tutar.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import SessionMaker
from .models import LoginSession

COOKIE_NAME = "misra_session"
SESSION_TTL = timedelta(days=365)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def auth_enabled() -> bool:
    s = get_settings()
    return bool(s.user_login and s.user_password)


def check_credentials(username: str, password: str) -> bool:
    s = get_settings()
    # sabit zamanlı karşılaştırma; ikisi de eşleşmeli
    ok_user = secrets.compare_digest(username.strip(), s.user_login)
    ok_pass = secrets.compare_digest(password, s.user_password)
    return ok_user and ok_pass


# --------------------------------------------------------------------------- #
# Oturum işlemleri
# --------------------------------------------------------------------------- #
async def create_session(session: AsyncSession, subject: str) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        LoginSession(token=token, email=subject, expires_at=_now() + SESSION_TTL)
    )
    await session.commit()
    return token


async def _resolve_session(token: str | None) -> str | None:
    if not token:
        return None
    async with SessionMaker() as session:
        row = await session.scalar(
            select(LoginSession).where(LoginSession.token == token)
        )
        if row is None or row.expires_at < _now():
            return None
        return row.email


async def destroy_session(token: str | None) -> None:
    if not token:
        return
    async with SessionMaker() as session:
        await session.execute(
            delete(LoginSession).where(LoginSession.token == token)
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# FastAPI bağımlılıkları
# --------------------------------------------------------------------------- #
async def optional_user(request: Request) -> str | None:
    """Giriş yapılmışsa kullanıcı adı, değilse None. Auth kapalıysa "" döner."""
    if not auth_enabled():
        return ""
    return await _resolve_session(request.cookies.get(COOKIE_NAME))


async def require_user(request: Request) -> str:
    """API rotaları için: giriş yoksa 401."""
    user = await optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Giriş gerekli")
    return user
