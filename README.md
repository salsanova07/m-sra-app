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
| `app/claude_client.py` | Claude API bağlantısı, sistem promptu, `create_pdf` aracı, streaming |
| `app/db.py` | Async SQLAlchemy motoru, oturum, tablo oluşturma |
| `app/models.py` | `Conversation`, `Message`, `Feedback`, `Pin`, `PdfFile`, `LoginSession` |
| `app/pdf.py` | Kitap tarzı PDF üretimi (A5, iki yana yaslı, Merriweather) + geçici saklama |
| `app/notify.py` | Resend API ile geri bildirim e-posta bildirimi |
| `app/auth.py` | Kullanıcı adı + şifre girişi: oturum / bağımlılıklar |
| `app/config.py` | `.env` / ortam değişkeni ayarları |
| `assets/fonts/` | Merriweather statik TTF'leri (PDF için, repoda) |
| `templates/index.html` `login.html` | Chat arayüzü + giriş sayfası (static dışında — giriş yapmadan erişilemez) |
| `static/style.css` `app.js` | Arayüz stilleri + betiği |
| `static/manifest.webmanifest` `service-worker.js` | PWA |
| `static/icons/` | Uygulama ikonları + `og-image.png` (link önizlemesi) |
| `pdfs/` | Geçici üretilen PDF'ler (gitignore, 24 saat sonra silinir) |

## API

| Yöntem | Yol | Açıklama |
|---|---|---|
| `GET` | `/api/conversations` | Konuşmaları listeler (en son güncellenen üstte) |
| `POST` | `/api/conversations` | Yeni boş konuşma oluşturur |
| `GET` | `/api/conversations/{id}/messages` | Bir konuşmanın mesaj geçmişi |
| `DELETE` | `/api/conversations/{id}` | Konuşmayı ve mesajlarını siler |
| `POST` | `/api/chat` | `{conversation_id, content}` → yanıtı SSE ile akıtır, iki tarafı da DB'ye yazar |
| `POST` | `/api/feedback` | `{kind: "suggestion"\|"bug", message}` → DB'ye yazar, e-posta bildirir |
| `GET` `POST` `DELETE` | `/api/pins[/{id}]` | Panoya sabitlenen metinler: listele / ekle / kaldır |
| `POST` | `/api/pdf` | `{text, title?}` → metni PDF'e çevirir, `{url, filename}` döner |
| `GET` | `/pdf/{token}` | Üretilen PDF'i indirir (24 saat geçerli) |
| `GET` | `/admin` | Şifre korumalı (HTTP Basic) geri bildirim listesi, tarih sırası |
| `GET` | `/login` | Kullanıcı adı + şifre giriş formu (auth kapalıysa `/`'a yönlendirir) |
| `POST` | `/api/login` | `{username, password}` → doğruysa 1 yıllık oturum çerezi; yanlışsa 401 |
| `POST` | `/logout` | Oturumu ve çerezi siler |

## Giriş (kullanıcı adı + şifre)

`USER_LOGIN` ve `USER_PASSWORD` **ikisi de boşsa giriş kapalıdır** — herkes doğrudan
girer (varsayılan davranış).

İkisi de doluysa:

1. Ziyaretçi `/` adresine gidince giriş formu görür.
2. Bilgiler yanlışsa: **"Kullanıcı adı veya şifre hatalı."** (401).
3. Doğruysa **1 yıllık** `misra_session` çerezi kurulur — aynı cihaz/tarayıcıda bir
   daha giriş ekranı çıkmaz. Sol paneldeki **Çıkış yap** ile sonlandırılır.

Karşılaştırma sabit zamanlıdır (`secrets.compare_digest`). Oturumlar `login_sessions`
tablosunda opak jeton olarak tutulur; **konuşma geçmişi (`conversations`/`messages`)
bu sistemden tamamen bağımsızdır, hiçbir mesaj silinmez.**

Giriş yapılmadan hiçbir sohbet ekranı ya da geçmiş konuşma görüntülenemez: tüm
`/api/*` uçları 401 döner ve `index.html` `static/` dışında (`templates/`) tutulduğu
için doğrudan indirilemez. **`/admin` bundan bağımsızdır**, kendi `ADMIN_PASSWORD`
korumasını kullanır.

Kullanıcı adı UTF-8 destekler (ör. `barış`).

> Üretimde çereze `Secure` bayrağı isteğin şemasına göre konur — ters vekil arkasında
> `uvicorn ... --proxy-headers` şart.

## Mesaj işlemleri

Her mesajın altında (farenle üstüne gelince; mobilde hep görünür) sade çizgi ikonlar:

- **Kopyala** — düz metni tarayıcı panosuna kopyalar (bu, aşağıdaki "Pano" özelliğiyle ilgisizdir).
- **Düzenle** (yalnız kullanıcı mesajı) — mesajı düzenleyip tekrar gönderirsin; o mesajdan
  sonraki geçmiş silinir ve yeni cevap üretilir.
- **Yeniden oluştur** (yalnız Mısra'nın cevabı) — aynı soruya yeni bir cevap ürettirir.
- **PDF yap** ve **Panoya ekle** (aşağıya bakın).

## Pano

Sol panelde **Konuşmalar / Pano** sekmesi var. Bir mesajın altındaki 📌 ile o metni
panoya eklersin — arayüz otomatik olarak Pano sekmesine geçer ve yeni öğe kısa bir
vurgu (highlight) ile belirir. Pano öğeleri konuşmalardan bağımsız durur; her birinin
yanında 📄 (PDF yap) ve × (kaldır) vardır.

## PDF'e dönüştürme

İki yol, aynı mantık — kitap tarzı (A5, iki yana yaslı, Merriweather):

1. **Buton:** her mesajın ve her pano öğesinin altındaki 📄 → metni PDF yapar,
   yanında indirme linki belirir.
2. **Doğal dil:** sohbette "bunu PDF yap", "PDF olarak çıkar", "şunu PDF'e dönüştür"
   yazınca Claude `create_pdf` aracını çağırır. Hangi metin olduğunu bağlamdan çıkarır
   (son mesaj, önceki bir mesaj ya da `pin_id` ile panodaki bir öğe); belirsizse önce
   kısa bir soru sorar. Link asistanın yanıtının sonuna eklenir ve mesajla kaydedilir.

PDF'ler `pdfs/` altında **24 saat** tutulur, sonra bir sonraki üretimde temizlenir.
`GET /pdf/{token}` girişe bağlıdır. Merriweather statik TTF'leri `assets/fonts/`
içinde repoda gelir (OFL).

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
- **pins**: `id`, `content`, `created_at` — panoya sabitlenen metinler
- **pdf_files**: `id`, `token`, `filename`, `created_at` — geçici PDF kayıtları
- **login_sessions**: `id`, `token`, `email` (kullanıcı adını tutar), `expires_at` — 1 yıl

> Eski magic-link sürümünden kalan `login_tokens` tablosu artık kullanılmıyor;
> boş kalır, istersen elle silebilirsin (`DROP TABLE login_tokens`).

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
| `RESEND_API_KEY` | — | Resend API anahtarı. Boşsa geri bildirim e-postası atlanır. |
| `NOTIFY_EMAIL` | — | Geri bildirim bildirimlerinin gideceği adres. |
| `FEEDBACK_FROM_EMAIL` | `onboarding@resend.dev` | Geri bildirim e-postasının gönderen adresi. |
| `USER_LOGIN` | — | Giriş kullanıcı adı. `USER_PASSWORD` ile birlikte boşsa giriş kapalı. |
| `USER_PASSWORD` | — | Giriş şifresi. |

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
