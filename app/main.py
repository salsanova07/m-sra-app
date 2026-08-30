import html
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import auth
from .auth import require_user
from .claude_client import stream_reply
from .config import get_settings
from .db import SessionMaker, engine, get_session, init_db
from .models import Conversation, Feedback, Message
from .notify import send_feedback_email

log = logging.getLogger("misra")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
# HTML şablonları static dışında tutulur ki giriş yapmadan /static/index.html
# üzerinden sohbet ekranına erişilemesin.
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield
    await engine.dispose()  # kapanışta DB bağlantı havuzunu temiz kapat


app = FastAPI(title="Mısra — Yazar Asistanı", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _title_from(text: str) -> str:
    """İlk kullanıcı mesajından kısa bir başlık üret."""
    flat = " ".join(text.strip().split())
    return (flat[:57] + "…") if len(flat) > 58 else flat


def _conv_dict(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()}


# --------------------------------------------------------------------------- #
# Statik / PWA
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # Giriş zorunluysa ve oturum yoksa: giriş sayfasını göster.
    if auth.auth_enabled() and await auth.optional_user(request) is None:
        return HTMLResponse((TEMPLATES_DIR / "login.html").read_text(encoding="utf-8"))

    # %OG_BASE% yer tutucusunu isteğin mutlak adresiyle değiştir — böylece
    # og:image / og:url link önizlemelerinde (WhatsApp, Telegram) mutlak URL olur.
    # Ters vekil arkasında doğru şema/host için uvicorn'u --proxy-headers ile çalıştır.
    base = str(request.base_url).rstrip("/")
    html_text = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    html_text = html_text.replace("%OG_BASE%", base).replace(
        "%AUTH%", "1" if auth.auth_enabled() else ""
    )
    return HTMLResponse(html_text)


# --------------------------------------------------------------------------- #
# Kullanıcı adı + şifre girişi — /admin'den bağımsız
# --------------------------------------------------------------------------- #
_YEAR_SECONDS = 365 * 24 * 3600


def _set_session_cookie(response, request: Request, token: str) -> None:
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=_YEAR_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not auth.auth_enabled() or await auth.optional_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse((TEMPLATES_DIR / "login.html").read_text(encoding="utf-8"))


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


@app.post("/api/login")
async def do_login(
    body: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)
):
    if not auth.auth_enabled():
        return {"ok": True}

    if not auth.check_credentials(body.username, body.password):
        raise HTTPException(
            status_code=401, detail="Kullanıcı adı veya şifre hatalı."
        )

    token = await auth.create_session(session, body.username.strip())
    response = JSONResponse({"ok": True})
    _set_session_cookie(response, request, token)
    return response


@app.post("/logout")
async def logout(request: Request):
    await auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@app.get("/manifest.webmanifest")
async def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js")
async def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Konuşmalar
# --------------------------------------------------------------------------- #
@app.get("/api/conversations", dependencies=[Depends(require_user)])
async def list_conversations(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await session.execute(
            select(Conversation).order_by(
                Conversation.updated_at.desc(), Conversation.id.desc()
            )
        )
    ).scalars().all()
    return [_conv_dict(c) for c in rows]


@app.post("/api/conversations", status_code=201, dependencies=[Depends(require_user)])
async def create_conversation(session: AsyncSession = Depends(get_session)) -> dict:
    conv = Conversation()
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return _conv_dict(conv)


@app.get("/api/conversations/{conv_id}/messages", dependencies=[Depends(require_user)])
async def conversation_messages(
    conv_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Konuşma bulunamadı")
    rows = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
        )
    ).scalars().all()
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [{"role": m.role, "content": m.content} for m in rows],
    }


@app.delete(
    "/api/conversations/{conv_id}", status_code=204, dependencies=[Depends(require_user)]
)
async def delete_conversation(
    conv_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    conv = await session.get(Conversation, conv_id)
    if conv is not None:
        await session.delete(conv)
        await session.commit()


# --------------------------------------------------------------------------- #
# Sohbet (SSE streaming)
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    conversation_id: int
    content: str = Field(min_length=1, max_length=20000)


@app.post("/api/chat", dependencies=[Depends(require_user)])
async def chat(req: ChatRequest) -> StreamingResponse:
    """Yeni kullanıcı mesajını ilgili konuşmaya kaydeder, Claude'un yanıtını
    akıtır ve yanıt tamamlanınca onu da kaydeder.

    Not: StreamingResponse gövdesi handler döndükten sonra çalıştığı için
    DB işlemleri `Depends` yerine doğrudan `SessionMaker` ile yapılır.
    """
    async with SessionMaker() as session:
        conv = await session.get(Conversation, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Konuşma bulunamadı")

        rows = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.id)
            )
        ).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in rows]

        session.add(Message(conversation_id=conv.id, role="user", content=req.content))
        if not rows:  # ilk mesaj → başlığı ondan türet
            conv.title = _title_from(req.content)
        conv.updated_at = datetime.now(timezone.utc)
        await session.commit()
        title = conv.title

    history.append({"role": "user", "content": req.content})

    async def event_stream() -> AsyncIterator[str]:
        acc = ""
        try:
            async for chunk in stream_reply(history):
                acc += chunk
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
        except anthropic.APIError as exc:
            yield f"data: {json.dumps({'error': f'API hatası: {exc}'}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # ör. eksik API anahtarı
            yield f"data: {json.dumps({'error': f'Sunucu hatası: {exc}'}, ensure_ascii=False)}\n\n"

        if acc:
            async with SessionMaker() as session:
                session.add(
                    Message(
                        conversation_id=req.conversation_id,
                        role="assistant",
                        content=acc,
                    )
                )
                conv = await session.get(Conversation, req.conversation_id)
                if conv is not None:
                    conv.updated_at = datetime.now(timezone.utc)
                await session.commit()

        yield f"data: {json.dumps({'done': True, 'title': title}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# Geri bildirim
# --------------------------------------------------------------------------- #
class FeedbackRequest(BaseModel):
    kind: Literal["suggestion", "bug"]
    message: str = Field(min_length=1, max_length=5000)


@app.post("/api/feedback", status_code=201, dependencies=[Depends(require_user)])
async def create_feedback(
    req: FeedbackRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    fb = Feedback(kind=req.kind, message=req.message.strip())
    session.add(fb)
    await session.commit()
    await session.refresh(fb)

    try:  # e-posta bildirimi en iyi çaba — başarısızlığı isteği bozmasın
        await send_feedback_email(fb.kind, fb.message)
    except Exception:
        log.warning("Geri bildirim e-postası gönderilemedi", exc_info=True)

    return {"id": fb.id}


# --------------------------------------------------------------------------- #
# /admin — şifre korumalı geri bildirim listesi (HTTP Basic Auth)
# --------------------------------------------------------------------------- #
_basic = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(_basic)) -> None:
    password = get_settings().admin_password
    if not password:
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD ayarlanmadı")
    if not secrets.compare_digest(creds.password, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yetkisiz",
            headers={"WWW-Authenticate": "Basic"},
        )


def _render_admin(rows: list[Feedback]) -> str:
    cards = []
    for fb in rows:
        label = "Öneri" if fb.kind == "suggestion" else "Hata"
        when = fb.created_at.strftime("%d.%m.%Y %H:%M")
        cards.append(
            f'<article class="fb {fb.kind}">'
            f'<header><span class="badge">{label}</span>'
            f'<time>{when} UTC</time></header>'
            f"<p>{html.escape(fb.message)}</p></article>"
        )
    body = "\n".join(cards) or '<p class="empty">Henüz geri bildirim yok.</p>'
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mısra — Geri Bildirimler</title>
<style>
  body {{ margin:0; padding:24px; background:#1b1a17; color:#ece7de;
         font-family:"Merriweather",Georgia,serif; line-height:1.5; }}
  h1 {{ color:#c9a227; font-size:1.4rem; margin:0 0 18px; }}
  h1 .count {{ color:#a49d8e; font-size:1rem; }}
  .fb {{ max-width:720px; margin:0 auto 12px; padding:12px 14px;
         background:#262420; border:1px solid #3a372f; border-radius:12px; }}
  .fb header {{ display:flex; gap:10px; align-items:center; margin-bottom:6px; }}
  .badge {{ font-size:.8rem; padding:2px 8px; border-radius:999px;
            background:#38342c; color:#c9a227; }}
  .fb.bug .badge {{ color:#e0908a; }}
  time {{ color:#a49d8e; font-size:.85rem; }}
  .fb p {{ margin:0; white-space:pre-wrap; word-wrap:break-word; }}
  .empty {{ color:#a49d8e; text-align:center; }}
</style></head>
<body>
<h1>Geri Bildirimler <span class="count">({len(rows)})</span></h1>
{body}
</body></html>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin(
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    rows = (
        await session.execute(
            select(Feedback).order_by(Feedback.created_at.desc(), Feedback.id.desc())
        )
    ).scalars().all()
    return HTMLResponse(_render_admin(rows))
