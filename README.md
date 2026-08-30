# Mısra — Yazar Asistanı

Claude API'ye bağlı, kullanıcının yazma sürecine eşlik eden bir yazar asistanı.
FastAPI backend + sade bir chat arayüzü + PostgreSQL'de kalıcı konuşma geçmişi
+ PWA desteği (telefonda ana ekrana eklenebilir).

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt

copy .env.example .env         # sonra .env içine ANTHROPIC_API_KEY ve DATABASE_URL yaz
```

### PostgreSQL

Uygulama `DATABASE_URL` ortam değişkeninden bir PostgreSQL bağlantısı bekler.
Tablolar açılışta otomatik oluşturulur (migration aracı yok).

Docker ile hızlı bir yerel veritabanı:

```bash
docker run --name misra-db -e POSTGRES_USER=misra -e POSTGRES_PASSWORD=misra \
  -e POSTGRES_DB=misra -p 5432:5432 -d postgres:16
```

`.env`:

```
DATABASE_URL=postgresql://misra:misra@localhost:5432/misra
```

`postgres://` ve `postgresql://` şemaları otomatik olarak `asyncpg` sürücüsüne çevrilir.
Neon / Supabase gibi barındırılan sağlayıcıların bağlantı dizesindeki libpq'ya özgü
parametreler (`sslmode`, `channel_binding`, …) otomatik dönüştürülür/temizlenir —
dizeyi olduğu gibi `.env`'e yapıştırman yeterli.

## Çalıştırma

```bash
uvicorn app.main:app --reload
```

Tarayıcıda: http://localhost:8000

## Yapı

| Dosya | Görev |
|---|---|
| `app/main.py` | FastAPI uygulaması, rotalar, SSE chat endpoint'i |
| `app/claude_client.py` | Claude API bağlantısı, sistem promptu, streaming yanıt |
| `app/db.py` | Async SQLAlchemy motoru, oturum, tablo oluşturma |
| `app/models.py` | `Conversation`, `Message`, `Feedback` ORM modelleri |
| `app/notify.py` | Resend API ile geri bildirim e-posta bildirimi |
| `app/config.py` | `.env` / ortam değişkeni ayarları |
| `static/index.html` `style.css` `app.js` | Chat arayüzü + konuşma paneli + geri bildirim formu |
| `static/manifest.webmanifest` `service-worker.js` | PWA |
| `static/icons/` | Uygulama ikonları + `og-image.png` (link önizlemesi) |

## API

| Yöntem | Yol | Açıklama |
|---|---|---|
| `GET` | `/api/conversations` | Konuşmaları listeler (en son güncellenen üstte) |
| `POST` | `/api/conversations` | Yeni boş konuşma oluşturur |
| `GET` | `/api/conversations/{id}/messages` | Bir konuşmanın mesaj geçmişi |
| `DELETE` | `/api/conversations/{id}` | Konuşmayı ve mesajlarını siler |
| `POST` | `/api/chat` | `{conversation_id, content}` → yanıtı SSE ile akıtır, iki tarafı da DB'ye yazar |
| `POST` | `/api/feedback` | `{kind: "suggestion"\|"bug", message}` → DB'ye yazar, e-posta bildirir |
| `GET` | `/admin` | Şifre korumalı (HTTP Basic) geri bildirim listesi, tarih sırası |

## Geri bildirim

- Arayüzde sol panelin altındaki **Öneri / Hata Bildir** butonu kısa bir form açar
  (tür + mesaj). Gönderim `feedback` tablosuna yazılır.
- `RESEND_API_KEY`, `NOTIFY_EMAIL` (ve `FEEDBACK_FROM_EMAIL`) doluysa her yeni
  geri bildirimde `NOTIFY_EMAIL` adresine kısa bir bildirim e-postası gider.
  E-posta gönderimi başarısız olsa bile geri bildirim yine kaydedilir.
- `/admin` sayfası tüm geri bildirimleri en yeniden eskiye listeler. Giriş: HTTP
  Basic — kullanıcı adı fark etmez, şifre `ADMIN_PASSWORD`.

## Veri modeli

- **conversations**: `id`, `title` (ilk mesajdan türetilir), `created_at`, `updated_at`
- **messages**: `id`, `conversation_id` (FK, cascade delete), `role`, `content`, `created_at`
- **feedback**: `id`, `kind` (`suggestion` \| `bug`), `message`, `created_at`

Her konuşma kendi mesaj geçmişini tutar; geçmişler birbirine karışmaz. Arayüz
açılışta en son güncellenen konuşmayı yükler; panelden eski konuşmalara dönülebilir.

## Ayarlar (.env)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Zorunlu. Anahtar yoksa chat "Sunucu hatası" döndürür. |
| `DATABASE_URL` | — | Zorunlu. PostgreSQL bağlantısı. Yoksa uygulama açılışta hata verir. |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Kullanılacak model |
| `MAX_TOKENS` | `4096` | Yanıt başına maksimum token |
| `USER_NAME` | `Barış` | Asistanın zaman zaman adıyla hitap ettiği kişi (sistem promptuna geçer) |
| `ADMIN_PASSWORD` | — | `/admin` şifresi. Boşsa `/admin` 503 döner. |
| `RESEND_API_KEY` | — | Resend API anahtarı. Boşsa e-posta bildirimi atlanır. |
| `NOTIFY_EMAIL` | — | Bildirim e-postalarının gideceği adres. |
| `FEEDBACK_FROM_EMAIL` | `onboarding@resend.dev` | Gönderen adresi (doğrulanmış alan adın yoksa varsayılanı bırak). |

## PWA notları

- `display: standalone` — ana ekrandan açıldığında tarayıcı çubuğu görünmez.
- Service worker yalnız uygulama kabuğunu önbelleğe alır; `/api/*` ve `/admin` her zaman ağdan gider.
- Telefonda "Ana ekrana ekle" için sitenin **HTTPS** üzerinden servis edilmesi gerekir
  (localhost geliştirmede istisna). Dağıtımda bir reverse proxy (Caddy/Nginx) ile TLS ekle.
- İkonlar basit yer tutucudur; kendi görselinle değiştir.

## Link önizlemesi (Open Graph)

`GET /` sayfası `%OG_BASE%` yer tutucusunu isteğin mutlak adresiyle değiştirir, böylece
`og:image` / `og:url` WhatsApp, Telegram vb. için tam URL olur. Önizleme görseli:
`static/icons/og-image.png` (1200×630, cennet ağacı logosu).

Ters vekil arkasında `og:url`'nin `https://` ve doğru host ile üretilmesi için uvicorn'u
`--proxy-headers` ile çalıştır:

```bash
uvicorn app.main:app --proxy-headers --forwarded-allow-ips='*'
```

## Sonraki adımlar (iskelette yok)

- Kimlik doğrulama / oturum (şu an tüm konuşmalar tek kullanıcıya ait varsayılır)
- Şema değişiklikleri için migration aracı (Alembic)
- Uzun sohbetler için context yönetimi (compaction)
- Rate limiting
