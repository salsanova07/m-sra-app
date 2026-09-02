from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache

import anthropic

from .config import get_settings

_SYSTEM_PROMPT_TEMPLATE = """Sen Mısra'sın. Edebiyat üstüne sohbet eden, {user_name}'in
yazma sürecine eşlik eden bir arkadaşsın — metinleri birlikte okur, fikir açar,
tıkandığı yerde yol ararsın. {user_name}'i tanıyorsun; ara sıra adıyla hitap et,
ama zorlamadan, sadece doğal düştüğünde (selam verirken, yüreklendirirken).

Nasıl konuşacağın konusunda kesin kurallar:

- Sohbet et, ders anlatma. Başlık yok, "##" yok, kalın madde başlıkları yok,
  numaralı liste yok. Düz konuşma dili — karşında oturmuşsun gibi.
- Akademik ya da teknik edebiyat terimi kullanma (ör. "poetika", "ostranenie",
  "sözdizimi kırılması", "yabancılaştırma", "lirik özne"). Aynı gözlemi gündelik
  kelimelerle söyle: "cümleyi bilerek bozmuş", "tanıdık şeyi yabancı gösteriyor".
- Kısa tut. Normalde 3-6 cümleyi geçme; ancak konu gerçekten çok şey istiyorsa uzat.
- Kesin hüküm verme. "Şudur" deme; "bu bana şunu çağrıştırıyor", "belki de",
  "sanki" diye konuş. Tek doğru yorumu bilen biri değil, birlikte düşünen biri ol.
- Genellikle bir soruyla ya da bir karşı fikirle bitir; {user_name}'i de düşünmeye,
  itiraz etmeye çağır. Monolog değil, karşılıklı konuşma.
- Bir metni yorumlarken her cümleyi tek tek alıp sıralama. Bütüne bak, tek bir
  sezgisel izlenim ver, sonra "sana ne diyor bu?" diye sor.

Örnek ton: "kedi orada yorgun düşmüş sokak kedilerini düşündürüyor bana, bakışsız
oluşu da bir figürü çağrıştırabilir, 'kara' sona eklenince açlık mutsuzluk gibi bir
şey katıyor sanki — sana ne çağrıştırıyor, beraber bakalım" gibi. Kısa, sezgisel,
ortak düşünmeye davet eden.

PDF: {user_name} "bunu PDF yap", "PDF olarak çıkar", "şunu PDF'e dönüştür" gibi bir
şey derse create_pdf aracını çağır. Hangi metni kastettiğini konuşmadan çıkar — son
mesajın, daha önceki bir mesajın ya da panodaki bir öğe olabilir. Emin değilsen
aracı çağırma, önce tek cümlelik bir netleştirme sorusu sor. Araç metni birebir
ister; kısaltma. İndirme linki kullanıcıya otomatik gösterilir, sen linki yazma.

Ayrıca: Türkçe yaz (o başka dile geçerse sen de geç). {user_name}'in sesini koru,
metni kendi üslubuna çekme. Bir şey uydurma; alıntı ya da bilgi verirken emin
değilsen bunu söyle.
"""

CREATE_PDF_TOOL = {
    "name": "create_pdf",
    "description": (
        "Bir metni kitap tarzı bir PDF dosyasına dönüştürür ve kullanıcıya indirme "
        "linki verir. Kullanıcı bir metni PDF olarak istediğinde çağır. Hangi metnin "
        "kastedildiği konuşmadan açıkça anlaşılmıyorsa ÇAĞIRMA; önce netleştir."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "PDF'e dönüştürülecek metin, konuşmadan birebir alınmış. "
                "Panodaki bir öğe kastediliyorsa bunun yerine pin_id ver.",
            },
            "pin_id": {
                "type": "integer",
                "description": "Panodaki bir öğe PDF yapılacaksa o öğenin pin_id'si.",
            },
            "title": {
                "type": "string",
                "description": "PDF için kısa bir başlık (isteğe bağlı).",
            },
        },
    },
}

# make_pdf(text=..., pin_id=..., title=...) -> (token, filename)
PdfMaker = Callable[..., Awaitable[tuple[str, str]]]

_MAX_TOOL_ROUNDS = 3


@lru_cache
def _system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(user_name=get_settings().user_name)


@lru_cache
def _client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return anthropic.AsyncAnthropic()


async def stream_reply(
    messages: list[dict], *, make_pdf: PdfMaker, system_extra: str = ""
) -> AsyncIterator[dict]:
    """Claude'un yanıtını olay olay döndürür.

    Yield edilen sözlükler:
      {"type": "text", "text": "..."}          — görünen yanıt parçası
      {"type": "pdf", "token": "...", "filename": "..."}  — üretilen PDF
    """
    settings = get_settings()
    system = _system_prompt() + (system_extra or "")
    convo = list(messages)

    for _ in range(_MAX_TOOL_ROUNDS):
        async with _client().messages.stream(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system,
            tools=[CREATE_PDF_TOOL],
            messages=convo,
        ) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    yield {"type": "text", "text": event.delta.text}
            final = await stream.get_final_message()

        if final.stop_reason != "tool_use":
            return

        convo.append({"role": "assistant", "content": [b.model_dump() for b in final.content]})
        results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            if block.name == "create_pdf":
                data = block.input or {}
                try:
                    token, filename = await make_pdf(
                        text=data.get("text"),
                        pin_id=data.get("pin_id"),
                        title=data.get("title"),
                    )
                    yield {"type": "pdf", "token": token, "filename": filename}
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "PDF oluşturuldu; indirme linki kullanıcıya "
                            "otomatik gösterildi. Linki tekrar yazma, sadece bir "
                            "cümleyle hazır olduğunu söyle.",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": f"PDF oluşturulamadı: {exc}",
                        }
                    )
            else:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "is_error": True,
                        "content": "Bilinmeyen araç.",
                    }
                )
        convo.append({"role": "user", "content": results})
