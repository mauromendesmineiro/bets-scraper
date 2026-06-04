"""
Detecção de status de login após submissão do formulário.
Suporta múltiplos idiomas (PT, ES, IT, EN) e vários padrões de erro.

ORDEM DE PRIORIDADE (importante):
  1. Alertas de erro visíveis  ← sempre primeiro, antes de qualquer outra verificação
  2. Reset de password obrigatório
  3. Elementos de sessão activa
  4. URL
"""

from playwright.sync_api import Page
from src.utils.logger import get_logger

log = get_logger("status")

LoginStatus = str
# Valores possíveis:
# SUCCESS | INVALID_CREDENTIALS | RATE_LIMIT | ACCESS_DENIED
# ACCOUNT_DISABLED | PASSWORD_RESET_REQUIRED | UNKNOWN
# (estes valores devem corresponder exactamente às comparações em main.py)


# ── Padrões de erro por categoria ─────────────────────────────────────────────
# Testados contra texto real do Netrefer em ES, PT, IT, EN

_PATTERNS: dict[str, list[str]] = {
    "ACCOUNT_DISABLED": [
        # ES
        "bloqueado",
        "bloqueada",
        "ha sido bloqueado",
        "ha sido bloqueada",
        "cuenta bloqueada",
        "cuenta ha sido bloqueada",
        "desactivado",
        "desactivada",
        # PT
        "bloqueada",
        "desativada",
        "conta bloqueada",
        # IT
        "bloccato",
        "disattivata",
        # EN
        "blocked",
        "account has been blocked",
        "account is blocked",
        "locked",
        "account has been locked",
        "has been locked",
        "disabled",
        "suspended",
    ],
    "INVALID_CREDENTIALS": [
        # ES
        "no son válidos",
        "usuario o contraseña",
        "credenciales",
        # PT
        "inválido",
        "utilizador ou password",
        # IT
        "non validi",
        "non corretti",
        "errati",
        "errato",
        # EN
        "incorrect",
        "incorret",
        "invalid",
        "wrong password",
        "username or password",
    ],
    "RATE_LIMIT": [
        "60 segundos",
        "60 seconds",
        "consecutivos",
        "consecutive",
        "demasiados intentos",
        "too many",
        "muitos pedidos",
        "rate limit",
    ],
    "ACCESS_DENIED": [
        "permiso denegado",
        "acceso denegado",
        "denegado",
        "permission denied",
        "access denied",
        "permesso negato",
        "acesso negado",
    ],
}

# Selectores de alertas de erro — a ordem importa (mais específico primeiro)
_ERROR_SELECTORS = (
    ".alert-danger, .alert.alert-danger, "
    "#login-error, .login-error, "
    ".error-message, .validation-summary-errors, "
    ".alert-error, .form-error, #errorMessage"
)

# Apenas links que SÓ existem depois de login bem-sucedido
# (evita falsos positivos com elementos do DOM da página de login)
_AUTHENTICATED_HREFS = [
    "/affiliates/Reports",
    "/affiliates/Setting",
    "/affiliates/Earnings",
    "/affiliates/Payment",
    "/affiliates/Favourite",
]

_SUCCESS_URL_FRAGMENTS = ["affiliates", "dashboard"]
_LOGIN_URL_FRAGMENTS = ["login", "signin", "sign-in", "account/login"]


def check_login_status(page: Page) -> LoginStatus:
    """
    Avalia o estado da página após tentativa de login.

    CRÍTICO: os alertas de erro são verificados ANTES de qualquer
    indicador de sucesso — evita falsos SUCCESS quando a conta está
    bloqueada mas o DOM ainda contém links autenticados.
    """
    # 1. Alertas de erro — PRIORIDADE MÁXIMA
    alerts_text = _collect_error_text(page)

    if alerts_text:
        log.debug(f"Texto de alerta detectado: '{alerts_text[:120]}'")
        for status, patterns in _PATTERNS.items():
            if any(p in alerts_text for p in patterns):
                log.debug(f"Padrão '{status}' encontrado")
                return status
        # Há alerta mas nenhum padrão reconhecido — regista para debug
        log.warning(f"Alerta não reconhecido: '{alerts_text[:120]}'")

    # 2. Reset de password obrigatório
    if _has_password_reset(page):
        return "PASSWORD_RESET_REQUIRED"

    # 3. Elementos que só existem em sessão autenticada
    if _has_authenticated_elements(page):
        return "SUCCESS"

    # 4. URL indica sessão activa
    url = page.url.lower()
    in_success_url = any(f in url for f in _SUCCESS_URL_FRAGMENTS)
    in_login_url = any(f in url for f in _LOGIN_URL_FRAGMENTS)
    if in_success_url and not in_login_url:
        return "SUCCESS"

    return "UNKNOWN"


def _collect_error_text(page: Page) -> str:
    """Recolhe texto de todos os elementos de erro visíveis."""
    try:
        elements = page.locator(_ERROR_SELECTORS)
        count = elements.count()
        if count > 0:
            texts = []
            for i in range(count):
                el = elements.nth(i)
                try:
                    if el.is_visible():
                        t = el.text_content()
                        if t:
                            texts.append(t.strip())
                except Exception:
                    pass
            return " ".join(texts).lower().strip()
    except Exception as e:
        log.debug(f"Erro ao recolher alertas: {e}")
    return ""


def _has_password_reset(page: Page) -> bool:
    url = page.url.lower()
    try:
        return (
            "resetpassword" in url
            or page.locator(
                "form[action*='ResetPassword'], form[action*='resetpassword']"
            ).count()
            > 0
            or page.locator(
                ".loginbox-title:has-text('Recuperar'), .loginbox-title:has-text('Reset')"
            ).count()
            > 0
        )
    except Exception:
        return False


def _has_authenticated_elements(page: Page) -> bool:
    """
    Verifica presença de elementos que SÓ existem em sessão autenticada.
    Usa hrefs específicos do Netrefer para evitar falsos positivos.
    """
    try:
        for href in _AUTHENTICATED_HREFS:
            if page.locator(f"a[href='{href}'], a[href^='{href}']").count() > 0:
                return True
    except Exception:
        pass
    return False
