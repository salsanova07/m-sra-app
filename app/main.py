import json
from pathlib import Path
from typing import Literal

import anthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .claude_client import stream_reply

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Mısra — Edebiyat & Felsefe Asistanı")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=100)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# PWA dosyaları kök kapsamdan (scope) servis edilmeli.
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


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Sohbet geçmişini alır, Claude'un yanıtını SSE (text/event-stream) olarak akıtır."""
    messages = [m.model_dump() for m in req.messages]

    async def event_stream():
        try:
            async for chunk in stream_reply(messages):
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except anthropic.APIError as exc:  # API / ağ hataları
            yield f"data: {json.dumps({'error': f'API hatası: {exc}'}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # ör. eksik API anahtarı
            yield f"data: {json.dumps({'error': f'Sunucu hatası: {exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
