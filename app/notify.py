import logging

import httpx

from .config import get_settings

logger = logging.getLogger("misra.notify")

RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailNotConfigured(RuntimeError):
    """RESEND_API_KEY ayarlı değil."""


async def _send_email(to: str, subject: str, text: str) -> None:
    s = get_settings()
    if not s.resend_api_key:
        raise EmailNotConfigured

    payload = {
        "from": s.feedback_from_email,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
    logger.info("E-posta gönderildi -> %s (%s)", to, subject)


async def send_feedback_email(kind: str, message: str) -> None:
    """Yeni geri bildirim için NOTIFY_EMAIL adresine kısa bir e-posta atar.

    Resend / NOTIFY_EMAIL yapılandırılmamışsa sessizce atlanır. Hata durumunda
    istek akışını bozmamak için çağıran taraf bunu try/except içine almalı.
    """
    s = get_settings()
    if not (s.resend_api_key and s.notify_email):
        logger.info("Resend/NOTIFY_EMAIL yok; geri bildirim e-postası atlanıyor.")
        return

    label = "Öneri" if kind == "suggestion" else "Hata"
    preview = message if len(message) <= 1000 else message[:1000] + "…"
    await _send_email(
        s.notify_email,
        f"[Mısra] Yeni geri bildirim: {label}",
        f"Tür: {label}\n\n{preview}\n\n— Tümü: /admin",
    )
