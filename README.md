# Mısra — Edebiyat & Felsefe Asistanı

Claude API'ye bağlı, kullanıcıyla sohbet edebilen bir edebiyat/felsefe asistanı.
FastAPI backend + sade bir chat arayüzü + PWA desteği (telefonda ana ekrana eklenebilir).

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt

copy .env.example .env         # sonra .env içine ANTHROPIC_API_KEY yaz
```

## Çalıştırma

```bash
uvicorn app.main:app --reload
```

Tarayıcıda: http://localhost:8000

## Yapı

| Dosya | Görev |
|---|---|
| `app/main.py` | FastAPI uygulaması, rotalar, SSE chat endpoint'i (`POST /api/chat`) |
| `app/claude_client.py` | Claude API bağlantısı, sistem promptu, streaming yanıt |
| `app/config.py` | `.env` / ortam değişkeni ayarları |
| `static/index.html` `style.css` `app.js` | Chat arayüzü |
| `static/manifest.webmanifest` `service-worker.js` | PWA (offline app shell + ana ekrana ekleme) |
| `static/icons/` | Uygulama ikonları (`icon.svg`, `icon-192.png`, `icon-512.png`) |

## Ayarlar (.env)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Zorunlu. Anahtar yoksa chat "Sunucu hatası" döndürür. |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Kullanılacak model |
| `MAX_TOKENS` | `4096` | Yanıt başına maksimum token |

## PWA notları

- `display: standalone` — ana ekrandan açıldığında tarayıcı çubuğu görünmez.
- Service worker yalnız uygulama kabuğunu önbelleğe alır; `/api/*` istekleri her zaman ağdan gider.
- Telefonda "Ana ekrana ekle" için sitenin **HTTPS** üzerinden servis edilmesi gerekir
  (localhost geliştirmede istisna). Dağıtımda bir reverse proxy (Caddy/Nginx) ile TLS ekle.
- İkonlar basit yer tutucudur; kendi görselinle değiştir.

## Sonraki adımlar (iskelette yok)

- Sohbet geçmişini kalıcı saklama (DB / dosya)
- Kimlik doğrulama / oturum
- Uzun sohbetler için context yönetimi (compaction)
- Rate limiting
