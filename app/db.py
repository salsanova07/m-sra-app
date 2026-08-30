from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import ENV_FILE, get_settings

# libpq/psycopg'ye özgü, asyncpg'nin anlamadığı sorgu parametreleri
_LIBPQ_ONLY = {"channel_binding", "gssencmode", "target_session_attrs"}


class Base(DeclarativeBase):
    """Tüm ORM modellerinin ortak temeli."""


def _normalize(url: str) -> str:
    """DATABASE_URL'i asyncpg sürücüsüne uygun hale getir.

    - `postgres://` / `postgresql://` -> `postgresql+asyncpg://`
    - libpq'ya özgü sorgu parametrelerini temizle (`channel_binding`, ...)
    - `sslmode=require` gibi libpq stilini asyncpg'nin anladığı `ssl=require`'a çevir
      (Neon, Supabase vb. bağlantı dizeleri bu biçimde gelir).
    """
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    parts = urlsplit(url)
    if "asyncpg" not in parts.scheme or not parts.query:
        return url

    params = parse_qsl(parts.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    ssl_value: str | None = None
    for key, value in params:
        if key == "sslmode":
            if value not in ("disable", "allow", "prefer"):
                ssl_value = "require"
        elif key == "ssl":
            ssl_value = value
        elif key not in _LIBPQ_ONLY:
            kept.append((key, value))

    if ssl_value:
        kept.append(("ssl", ssl_value))

    return urlunsplit(parts._replace(query=urlencode(kept)))


_settings = get_settings()
if not _settings.database_url:
    _hint = f"(okunması beklenen .env: {ENV_FILE} — {'var' if ENV_FILE.exists() else 'YOK'})"
    raise RuntimeError(
        "DATABASE_URL ayarlanmadı. .env dosyasına bir PostgreSQL bağlantısı ekleyin, örn.:\n"
        "  DATABASE_URL=postgresql://kullanici:parola@localhost:5432/misra\n"
        f"{_hint}"
    )

engine = create_async_engine(_normalize(_settings.database_url), pool_pre_ping=True)
SessionMaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI bağımlılığı: istek başına bir DB oturumu."""
    async with SessionMaker() as session:
        yield session


async def init_db() -> None:
    """Uygulama açılışında tabloları oluştur (yoksa)."""
    from . import models  # noqa: F401 — modelleri Base.metadata'ya kaydeder

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
