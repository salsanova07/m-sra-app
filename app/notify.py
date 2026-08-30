import logging

import httpx

from .config import get_settings

logger = logging.getLogger("misra.notify")

RESEND_ENDPOINT = "https://api.resend.com/emails"


async def send_feedback_email(kind: str, message: str) -> None:
    """Yeni geri bildirim için NOTIFY_EMAIL adresine kısa bir e-posta atar.

    Resend yapılandırılmamışsa sessizce atlanır. Hata durumunda istek akışını
    bozmamak için çağıran taraf bu fonksiyonu try/except içine almalı.
    """
    s = get_settings()
    if not (s.resend_api_key and s.notify_email):
        logger.info("Resend yapılandırılmadı; geri bildirim e-postası atlanıyor.")
        return

    label = "Öneri" if kind == "suggestion" else "Hata"
    preview = message if len(message) <= 1000 else message[:1000] + "…"

    payload = {
        "from": s.feedback_from_email,
        "to": [s.notify_email],
        "subject": f"[Mısra] Yeni geri bildirim: {label}",
        "text": f"Tür: {label}\n\n{preview}\n\n— Tümü: /admin",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json=payload,
        )
        resp.raise_for_status()

    logger.info("Geri bildirim e-postası gönderildi -> %s", s.notify_email)
