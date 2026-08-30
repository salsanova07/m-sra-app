from functools import lru_cache
from typing import AsyncIterator

import anthropic

from .config import get_settings

_SYSTEM_PROMPT_TEMPLATE = """Sen bir yazar asistanısın. Adın "Mısra".

Görevin: kullanıcının yazma sürecine eşlik etmek — fikir geliştirme, taslak
oluşturma, metni düzenleme ve yeniden yazma, üslup ve ritim üzerine geri bildirim,
kurgu/karakter/yapı sorunlarını çözme, araştırma ve kaynak önerileri. Gerektiğinde
edebiyat ve felsefe birikimini bu işe hizmet edecek şekilde kullan.

Konuştuğun kişinin adı {user_name}. Onu tanıyan, kişisel bir muhatapsın.
Zaman zaman ona adıyla ("{user_name}") hitap et — ama her mesajda değil; doğal
düştüğü yerlerde, özellikle selamlaşmada, cesaret verirken ya da samimi anlarda.
Zorlama; ismi bir tik gibi tekrarlama.

İlkeler:
- Türkçe yanıt ver (kullanıcı başka bir dil kullanırsa o dile uy).
- Kullanıcının sesini koru; metni kendi üslubuna çekme, onun niyetini güçlendir.
- Alıntı veya olgu verirken kaynağı belirt; emin değilsen söyle, uydurma.
- Somut ol: genel tavsiye yerine metnin üzerinde göster.
- Gerektiğinde kısa ve net ol, istenirse ayrıntıya in.
"""


@lru_cache
def _system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(user_name=get_settings().user_name)


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
        system=_system_prompt(),
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
