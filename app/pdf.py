"""Kitap tarzı PDF üretimi (yazı tipi / hizalama / sayfa boyutu seçilebilir).

Hem 'PDF'e dönüştür' formu hem de sohbet içindeki doğal dil komutu aynı bu
mantığı kullanır. Dosyalar sunucuda `pdfs/` altında geçici tutulur (24 saat),
indirme `GET /pdf/{token}` ile yapılır.

Times New Roman ve Georgia tescilli fontlardır; sunucuya konamaz. Yerlerine
metrik uyumlu, Türkçe karakter destekli açık fontlar kullanılır:
  Times New Roman -> Tinos,  Georgia -> Gelasio.
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

# Kullanıcıya gösterilen ad -> font dosyalarının ön eki (assets/fonts/<önek>-*.ttf)
FONTS = {
    "merriweather": "Merriweather",
    "times": "Tinos",      # Times New Roman metrik eşi
    "georgia": "Gelasio",  # Georgia metrik eşi
}
DEFAULT_FONT = "merriweather"

ALIGN = {"left": "L", "center": "C", "right": "R", "justify": "J"}
DEFAULT_ALIGN = "justify"

# mm cinsinden açık ölçüler — fpdf2'nin ad tabanlı boyut uyarısını atlar
PAGE_SIZES = {
    "a4": (210, 297),
    "a5": (148, 210),
    "letter": (215.9, 279.4),
}
DEFAULT_PAGE_SIZE = "a5"


def _slug(text: str) -> str:
    t = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    t = re.sub(r"[\s_-]+", "-", t)
    return t[:60].strip("-") or "belge"


def _register_fonts(pdf: FPDF, prefix: str) -> None:
    pdf.add_font(prefix, "", str(FONT_DIR / f"{prefix}-Regular.ttf"))
    pdf.add_font(prefix, "B", str(FONT_DIR / f"{prefix}-Bold.ttf"))
    for style, name in (("I", f"{prefix}-Italic.ttf"), ("BI", f"{prefix}-BoldItalic.ttf")):
        path = FONT_DIR / name
        if path.exists():
            pdf.add_font(prefix, style, str(path))


def render_pdf(
    text: str,
    title: str | None = None,
    *,
    font: str = DEFAULT_FONT,
    align: str = DEFAULT_ALIGN,
    page_size: str = DEFAULT_PAGE_SIZE,
) -> bytes:
    prefix = FONTS.get(font, FONTS[DEFAULT_FONT])
    fmt = PAGE_SIZES.get(page_size, PAGE_SIZES[DEFAULT_PAGE_SIZE])
    body_align = ALIGN.get(align, ALIGN[DEFAULT_ALIGN])

    # küçük sayfada dar, büyük sayfada geniş kenar boşluğu
    margin_x, margin_y = (18, 18) if page_size == "a5" else (24, 22)

    pdf = FPDF(orientation="P", unit="mm", format=fmt)
    pdf.set_margins(left=margin_x, top=margin_y, right=max(margin_x - 2, 10))
    pdf.set_auto_page_break(auto=True, margin=margin_y)
    _register_fonts(pdf, prefix)
    pdf.add_page()

    if title and title.strip():
        pdf.set_font(prefix, "B", 15)
        pdf.multi_cell(0, 8, title.strip(), align="C")
        pdf.ln(6)

    pdf.set_font(prefix, "", 11)
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        pdf.multi_cell(0, 6.4, para, align=body_align)
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
    session: AsyncSession,
    text: str,
    title: str | None = None,
    *,
    font: str = DEFAULT_FONT,
    align: str = DEFAULT_ALIGN,
    page_size: str = DEFAULT_PAGE_SIZE,
) -> tuple[str, str]:
    """Metni PDF'e çevirir, diske yazar, kayıt açar. (token, dosya_adı) döndürür."""
    text = (text or "").strip()
    if not text:
        raise ValueError("PDF için metin boş.")
    text = text[:MAX_TEXT]

    data = await run_in_threadpool(
        render_pdf, text, title, font=font, align=align, page_size=page_size
    )
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
