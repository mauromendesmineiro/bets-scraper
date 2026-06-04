"""
Configuração central — lê SEMPRE de variáveis de ambiente.
Nunca coloca credenciais no código ou em ficheiros committed.

Cria um ficheiro .env local (não commitar) ou define as vars no sistema.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Variable de entorno obligatoria no definida: {key}")
    return val.strip()


def _optional(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


@dataclass(frozen=True)
class Config:
    # ── Supabase ──────────────────────────────────────────────
    supabase_url: str = field(default_factory=lambda: _require("SUPABASE_URL"))
    supabase_key: str = field(default_factory=lambda: _require("SUPABASE_KEY"))

    # ── Captcha (2captcha) ────────────────────────────────────
    captcha_api_key: str = field(
        default_factory=lambda: _optional("TWOCAPTCHA_API_KEY")
    )

    # ── Playwright ────────────────────────────────────────────
    headless: bool = field(
        default_factory=lambda: _optional("HEADLESS", "true").lower() == "true"
    )
    slow_mo: int = field(default_factory=lambda: int(_optional("SLOW_MO", "0")))
    default_timeout: int = field(
        default_factory=lambda: int(_optional("DEFAULT_TIMEOUT", "15000"))
    )

    # ── Scraping behaviour ────────────────────────────────────
    rate_limit_wait: int = field(
        default_factory=lambda: int(_optional("RATE_LIMIT_WAIT", "65"))
    )
    sleep_between_accounts: int = field(
        default_factory=lambda: int(_optional("SLEEP_BETWEEN", "3"))
    )
    days_window: int = field(default_factory=lambda: int(_optional("DAYS_WINDOW", "3")))

    # ── Storage local (para desenvolvimento) ──────────────────
    data_dir: str = field(default_factory=lambda: _optional("DATA_DIR", "data"))
    logs_dir: str = field(default_factory=lambda: _optional("LOGS_DIR", "logs"))

    # ── Google Drive (opcional) ───────────────────────────────
    gdrive_folder_id: str = field(default_factory=lambda: _optional("GDRIVE_FOLDER_ID"))

    # ── Resend (notificações por email) ──────────────────────────
    smtp_user: str = field(default_factory=lambda: _optional("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _optional("SMTP_PASSWORD"))
    # resend_api_key: str = field(default_factory=lambda: _optional("RESEND_API_KEY"))
    # notify_from: str = field(default_factory=lambda: _optional("NOTIFY_FROM"))
    notify_to: str = field(default_factory=lambda: _optional("NOTIFY_TO"))
    notify_cc: str = field(default_factory=lambda: _optional("NOTIFY_CC"))
    notify_bcc: str = field(default_factory=lambda: _optional("NOTIFY_BCC"))


# Singleton — importa este objeto em todo o projecto
config = Config()
