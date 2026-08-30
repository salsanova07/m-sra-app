from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env dosyasını proje köküne göre çöz — uvicorn hangi dizinden başlatılırsa
# başlatılsın aynı dosya okunur (CWD'ye bağlı değil).
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Ortam değişkenlerinden / .env dosyasından okunan ayarlar."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    max_tokens: int = 4096
    database_url: str = ""

    # /admin sayfası için şifre (boşsa /admin 503 döner)
    admin_password: str = ""

    # Geri bildirim e-posta bildirimi (Resend) — hepsi doluysa e-posta gönderilir
    resend_api_key: str = ""
    notify_email: str = ""
    feedback_from_email: str = "onboarding@resend.dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
