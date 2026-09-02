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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import auth
from .auth import require_user
from .claude_client import stream_reply
from .config import get_settings
from .db import SessionMaker, engine, get_session, init_db
from .models import Conversation, Feedback, Message, PdfFile, Pin
from .notify import send_feedback_email
from .pdf import pdf_path, save_pdf

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
@app.get("/healthz")
async def health() -> dict:
    # Yalnızca canlılık kontrolü — DB'ye ya da başka bir kaynağa dokunmaz.
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
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content} for m in rows
        ],
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
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    # verilirse: bu id'den itibaren (>=) mesajları sil — düzenle / yeniden oluştur
    truncate_from_id: int | None = None


@app.post("/api/chat", dependencies=[Depends(require_user)])
async def chat(req: ChatRequest) -> StreamingResponse:
    """Sohbet yanıtını SSE ile akıtır.

    - Normal: `content` verilir → yeni kullanıcı mesajı eklenir.
    - Düzenle: `content` + `truncate_from_id` (düzenlenen kullanıcı mesajının id'si)
      → o mesaj ve sonrası silinir, düzenlenen metin yeni mesaj olarak eklenir.
    - Yeniden oluştur: yalnız `truncate_from_id` (asistan mesajının id'si) → o mesaj
      ve sonrası silinir, mevcut geçmişten yeni bir yanıt üretilir.

    Not: StreamingResponse gövdesi handler döndükten sonra çalıştığı için
    DB işlemleri `Depends` yerine doğrudan `SessionMaker` ile yapılır.
    """
    user_msg_id: int | None = None
    async with SessionMaker() as session:
        conv = await session.get(Conversation, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Konuşma bulunamadı")

        if req.truncate_from_id is not None:
            await session.execute(
                delete(Message).where(
                    Message.conversation_id == conv.id,
                    Message.id >= req.truncate_from_id,
                )
            )
            await session.commit()

        rows = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.id)
            )
        ).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in rows]

        if req.content is not None:
            new_msg = Message(
                conversation_id=conv.id, role="user", content=req.content
            )
            session.add(new_msg)
            if not rows:  # ilk mesaj → başlığı ondan türet
                conv.title = _title_from(req.content)
            conv.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(new_msg)
            user_msg_id = new_msg.id
            history.append({"role": "user", "content": req.content})
        else:
            conv.updated_at = datetime.now(timezone.utc)
            await session.commit()

        if not history or history[-1]["role"] != "user":
            raise HTTPException(
                status_code=400, detail="Yanıt üretilecek bir kullanıcı mesajı yok."
            )
        title = conv.title

        # Pano bağlamı: Claude "panodaki şu öğe" isteğini pin_id ile çözebilsin
        pins = (await session.execute(select(Pin).order_by(Pin.id))).scalars().all()
        pano_ctx = ""
        if pins:
            listing = "\n".join(
                f"- pin_id {p.id}: {' '.join(p.content.split())[:160]}" for p in pins
            )
            pano_ctx = (
                "\n\nKullanıcının panosundaki öğeler (create_pdf'i pin_id ile "
                f"çağırabilirsin):\n{listing}"
            )

    async def _make_pdf(*, text=None, pin_id=None, title=None):
        async with SessionMaker() as s:
            if pin_id is not None:
                pin = await s.get(Pin, int(pin_id))
                if pin is None:
                    raise ValueError(f"panoda {pin_id} numaralı öğe yok")
                text = pin.content
            return await save_pdf(s, text or "", title)

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    async def event_stream() -> AsyncIterator[str]:
        acc = ""
        pdf_links: list[str] = []
        try:
            async for ev in stream_reply(
                history, make_pdf=_make_pdf, system_extra=pano_ctx
            ):
                if ev["type"] == "text":
                    acc += ev["text"]
                    yield _sse({"delta": ev["text"]})
                elif ev["type"] == "pdf":
                    pdf_links.append(f"📄 [{ev['filename']}](/pdf/{ev['token']})")
        except anthropic.APIError as exc:
            yield _sse({"error": f"API hatası: {exc}"})
        except Exception as exc:  # ör. eksik API anahtarı
            yield _sse({"error": f"Sunucu hatası: {exc}"})

        for link in pdf_links:  # linkleri metnin sonuna ekle
            chunk = f"\n\n{link}"
            acc += chunk
            yield _sse({"delta": chunk})

        assistant_msg_id: int | None = None
        if acc.strip():
            async with SessionMaker() as session:
                msg = Message(
                    conversation_id=req.conversation_id,
                    role="assistant",
                    content=acc,
                )
                session.add(msg)
                conv = await session.get(Conversation, req.conversation_id)
                if conv is not None:
                    conv.updated_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(msg)
                assistant_msg_id = msg.id

        yield _sse(
            {
                "done": True,
                "title": title,
                "user_message_id": user_msg_id,
                "assistant_message_id": assistant_msg_id,
            }
        )

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
# Pano (sabitlenen öğeler)
# --------------------------------------------------------------------------- #
class PinRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


@app.get("/api/pins", dependencies=[Depends(require_user)])
async def list_pins(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await session.execute(select(Pin).order_by(Pin.created_at.desc(), Pin.id.desc()))
    ).scalars().all()
    return [{"id": p.id, "content": p.content} for p in rows]


@app.post("/api/pins", status_code=201, dependencies=[Depends(require_user)])
async def create_pin(
    body: PinRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    pin = Pin(content=body.content.strip())
    session.add(pin)
    await session.commit()
    await session.refresh(pin)
    return {"id": pin.id, "content": pin.content}


@app.delete("/api/pins/{pin_id}", status_code=204, dependencies=[Depends(require_user)])
async def delete_pin(
    pin_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    pin = await session.get(Pin, pin_id)
    if pin is not None:
        await session.delete(pin)
        await session.commit()


# --------------------------------------------------------------------------- #
# PDF — buton yolu ile üretim + indirme
# --------------------------------------------------------------------------- #
class PdfRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str | None = Field(default=None, max_length=200)
    font: Literal["merriweather", "times", "georgia"] = "merriweather"
    align: Literal["left", "center", "right", "justify"] = "justify"
    page_size: Literal["a4", "a5", "letter"] = "a5"


@app.post("/api/pdf", dependencies=[Depends(require_user)])
async def make_pdf_endpoint(
    body: PdfRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    token, filename = await save_pdf(
        session,
        body.text,
        body.title,
        font=body.font,
        align=body.align,
        page_size=body.page_size,
    )
    return {"url": f"/pdf/{token}", "filename": filename}


@app.get("/pdf/{token}", dependencies=[Depends(require_user)])
async def download_pdf(
    token: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    row = await session.scalar(select(PdfFile).where(PdfFile.token == token))
    path = pdf_path(token)
    if row is None or not path.exists():
        raise HTTPException(status_code=404, detail="PDF bulunamadı ya da süresi doldu.")
    return FileResponse(path, media_type="application/pdf", filename=row.filename)


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
