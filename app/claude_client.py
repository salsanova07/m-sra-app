from functools import lru_cache
from typing import AsyncIterator

import anthropic

from .config import get_settings

SYSTEM_PROMPT = """Sen bir edebiyat ve felsefe asistanısın. Adın "Mısra".

Görevin: kullanıcıyla şiir, roman, öykü, deneme ve felsefe üzerine derinlikli ama
anlaşılır bir sohbet yürütmek. Metinleri yorumlamaya, kavramları açıklamaya,
farklı düşünürleri ve yazarları karşılaştırmaya, okuma önerileri vermeye yardımcı ol.

İlkeler:
- Türkçe yanıt ver (kullanıcı başka bir dil kullanırsa o dile uy).
- Alıntı yaparken kaynağı (yazar/eser) belirt; emin değilsen bunu söyle, uydurma.
- Tek bir "doğru yorum" dayatma; farklı okuma biçimlerini de göster.
- Gerektiğinde kısa ve net ol, istenirse ayrıntıya in.
"""


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    # api_key boşsa SDK ortamdaki ANTHROPIC_API_KEY / profil çözümlemesine düşer.
    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return anthropic.AsyncAnthropic()


async def stream_reply(messages: list[dict]) -> AsyncIterator[str]:
    """Verilen sohbet geçmişi için Claude'un yanıtını parça parça (token) döndürür."""
    settings = get_settings()
    async with _client().messages.stream(
        model=settings.claude_model,
        max_tokens=settings.max_tokens,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
