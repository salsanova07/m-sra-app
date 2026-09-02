"""Kitap tarzı PDF üretimi (A5, iki yana yaslı, Merriweather).

Hem 'PDF yap' butonu hem de sohbet içindeki doğal dil komutu aynı bu mantığı
kullanır. Dosyalar sunucuda `pdfs/` altında geçici tutulur (24 saat), indirme
`GET /pdf/{token}` ile yapılır.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from .models import PdfFile

BASE_DIR = Path(__file__).resolve().parent.parent
FONT_DIR = BASE_DIR / "assets" / "fonts"
PDF_DIR = BASE_DIR / "pdfs"
PDF_TTL = timedelta(hours=24)
MAX_TEXT = 200_000

PDF_DIR.mkdir(exist_ok=True)


def _slug(text: str) -> str:
    t = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    t = re.sub(r"[\s_-]+", "-", t)
    return t[:60].strip("-") or "belge"


def _register_fonts(pdf: FPDF) -> None:
    pdf.add_font("Merriweather", "", str(FONT_DIR / "Merriweather-Regular.ttf"))
    pdf.add_font("Merriweather", "B", str(FONT_DIR / "Merriweather-Bold.ttf"))
    for style, name in (("I", "Merriweather-Italic.ttf"), ("BI", "Merriweather-BoldItalic.ttf")):
        path = FONT_DIR / name
        if path.exists():
            pdf.add_font("Merriweather", style, str(path))


A5 = (148, 210)  # mm — açık ölçü (fpdf2'nin "A5" uyarısını atlar)


def render_pdf(text: str, title: str | None = None) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format=A5)
    pdf.set_margins(left=18, top=18, right=16)  # kitap: iç kenar biraz geniş
    pdf.set_auto_page_break(auto=True, margin=18)
    _register_fonts(pdf)
    pdf.add_page()

    if title and title.strip():
        pdf.set_font("Merriweather", "B", 15)
        pdf.multi_cell(0, 8, title.strip(), align="C")
        pdf.ln(6)

    pdf.set_font("Merriweather", "", 11)
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        pdf.multi_cell(0, 6.4, para, align="J")
        pdf.ln(3)

    return bytes(pdf.output())


async def _cleanup(session: AsyncSession) -> None:
    cutoff = datetime.now(timezone.utc) - PDF_TTL
    rows = (
        await session.execute(select(PdfFile).where(PdfFile.created_at < cutoff))
    ).scalars().all()
    for row in rows:
        (PDF_DIR / f"{row.token}.pdf").unlink(missing_ok=True)
        await session.delete(row)
    if rows:
        await session.commit()


async def save_pdf(
    session: AsyncSession, text: str, title: str | None = None
) -> tuple[str, str]:
    """Metni PDF'e çevirir, diske yazar, kayıt açar. (token, dosya_adı) döndürür."""
    text = (text or "").strip()
    if not text:
        raise ValueError("PDF için metin boş.")
    text = text[:MAX_TEXT]

    data = await run_in_threadpool(render_pdf, text, title)
    token = secrets.token_urlsafe(16)
    base = _slug(title) if title and title.strip() else _slug(text[:40])
    filename = f"{base}.pdf"
    (PDF_DIR / f"{token}.pdf").write_bytes(data)

    session.add(PdfFile(token=token, filename=filename))
    await session.commit()
    await _cleanup(session)
    return token, filename


def pdf_path(token: str) -> Path:
    return PDF_DIR / f"{token}.pdf"
