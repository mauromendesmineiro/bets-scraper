"""
Motor de login para plataformas de afiliados.
Suporta login padrão e login com captcha de imagem (via 2captcha).

Cada plataforma tem o seu handler específico que herda de BaseLoginHandler.
Adicionar uma nova plataforma = criar uma nova subclasse.
"""

import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page, BrowserContext

from src.scraper.status import check_login_status, LoginStatus
from src.scraper.captcha import CaptchaSolver, CaptchaError
from src.utils.logger import get_logger

log = get_logger("login")


@dataclass
class LoginResult:
    status: LoginStatus
    error: str = ""
    cookies: list = None


# ── Handler base ──────────────────────────────────────────────────────────────


class BaseLoginHandler:
    """
    Handler base. Subclasses sobrepõem apenas o que for diferente.
    A maioria das plataformas só precisa de redefinir os selectores.
    """

    # Selectores padrão (Netrefer e similares)
    SEL_USERNAME = "#txtUsername"
    SEL_PASSWORD = "#txtPassword"
    SEL_SUBMIT = "#btnLogin"
    SEL_AGREE = "#agreeButton"  # popup de termos — opcional
    SEL_CAPTCHA = None  # None = sem captcha
    SEL_CAPTCHA_INPUT = None

    HAS_CAPTCHA = False

    def __init__(
        self,
        captcha_solver: Optional[CaptchaSolver] = None,
        timeout: int = 15000,
        slow_mo: int = 200,
    ):
        self.captcha_solver = captcha_solver
        self.timeout = timeout
        self.slow_mo = slow_mo

    def login(self, page: Page, url: str, username: str, password: str) -> LoginStatus:
        """Executa o fluxo completo de login e devolve o status."""
        log.info(f"Acessando {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)

        self._fill_credentials(page, username, password)

        if self.HAS_CAPTCHA:
            self._solve_captcha(page)

        self._submit(page)
        self._handle_agree_popup(page)
        self._wait_after_login(page)

        status = check_login_status(page)
        log.info(f"Status após login: {status}")
        return status

    def _fill_credentials(self, page: Page, username: str, password: str) -> None:
        page.wait_for_selector(self.SEL_USERNAME, timeout=self.timeout)
        page.fill(self.SEL_USERNAME, username)
        page.fill(self.SEL_PASSWORD, password)

    def _solve_captcha(self, page: Page) -> None:
        if not self.captcha_solver:
            raise CaptchaError(
                "Esta plataforma requer captcha, mas TWOCAPTCHA_API_KEY não está definida."
            )
        if not self.SEL_CAPTCHA or not self.SEL_CAPTCHA_INPUT:
            raise CaptchaError(
                f"Seletores de captcha não definidos em {self.__class__.__name__}"
            )

        log.info("Captcha detectado — resolvendo via 2captcha...")
        solution = self.captcha_solver.solve_image(page, self.SEL_CAPTCHA)
        page.fill(self.SEL_CAPTCHA_INPUT, solution)

    def _submit(self, page: Page) -> None:
        page.click(self.SEL_SUBMIT)
        page.wait_for_load_state("domcontentloaded", timeout=self.timeout)

    def _handle_agree_popup(self, page: Page) -> None:
        """
        Clica em botão de aceitação de termos se aparecer.
        Suporta dois tipos conhecidos no Netrefer:
          1. #agreeButton — popup de sessão activa
          2. "I agree to the terms and conditions" — página de T&C após login
        """
        # Tipo 1: botão de sessão (#agreeButton)
        if self.SEL_AGREE:
            try:
                page.wait_for_selector(self.SEL_AGREE, timeout=3000)
                page.click(self.SEL_AGREE)
                page.wait_for_load_state("domcontentloaded", timeout=self.timeout)
            except Exception:
                pass

        # Tipo 2: página de T&C do Netrefer (terms and conditions update)
        # Detecta pela presença do campo hidden tosContentID ou pelo botão de submit
        try:
            tos_btn = page.locator(
                "input[value*='I agree to the terms'], input.btn-blue[type='submit']"
            )
            if tos_btn.count() > 0 and tos_btn.first.is_visible():
                log.info(
                    "Página de termos e condições detectada — aceitando automaticamente..."
                )
                tos_btn.first.click()
                page.wait_for_load_state("domcontentloaded", timeout=self.timeout)
                log.info("Termos e condições aceitos")
        except Exception:
            pass

    def _wait_after_login(self, page: Page) -> None:
        """Aguarda elemento que indica login bem-sucedido (melhor que networkidle fixo)."""
        try:
            page.wait_for_selector(
                "a[href*='Reports'], a[href*='reports'], a[href*='logout']",
                timeout=5000,
            )
        except Exception:
            pass  # se não aparecer, check_login_status determinará o estado real


# ── Handlers específicos por plataforma ──────────────────────────────────────


class NetreferLoginHandler(BaseLoginHandler):
    """Netrefer — sem captcha, selectores padrão."""

    pass  # herda tudo do base


class IncomeAccessLoginHandler(BaseLoginHandler):
    """Income Access (ex: Betano affiliates) — captcha de imagem via 2captcha."""

    SEL_USERNAME = "#username"
    SEL_PASSWORD = "#password"
    SEL_SUBMIT = "button.btn.btn-primary"
    SEL_AGREE = None
    SEL_CAPTCHA = "img[alt='This Is verification Image']"
    SEL_CAPTCHA_INPUT = "#strverifyimg"
    HAS_CAPTCHA = True


class MyAffiliatesLoginHandler(BaseLoginHandler):
    """MyAffiliates — sem captcha, selectores próprios."""

    SEL_USERNAME = "input[name='username'], #login"
    SEL_PASSWORD = "input[name='password'], #password"
    SEL_SUBMIT = "button[type='submit'], input[type='submit']"
    SEL_AGREE = None


class AffilkaLoginHandler(BaseLoginHandler):
    """Affilka — sem captcha."""

    SEL_USERNAME = "input[type='email'], input[name='email']"
    SEL_PASSWORD = "input[type='password']"
    SEL_SUBMIT = "button[type='submit']"
    SEL_AGREE = None


# ── Registo de handlers por slug de plataforma ────────────────────────────────

HANDLERS: dict[str, type[BaseLoginHandler]] = {
    "netrefer": NetreferLoginHandler,
    "income_access": IncomeAccessLoginHandler,
    "myaffiliates": MyAffiliatesLoginHandler,
    "affilka": AffilkaLoginHandler,
}


def get_handler(
    platform_slug: str, captcha_solver: Optional[CaptchaSolver] = None, **kwargs
) -> BaseLoginHandler:
    """
    Factory — devolve o handler correcto para a plataforma.
    Lança ValueError se o slug não estiver registado.
    """
    cls = HANDLERS.get(platform_slug)
    if not cls:
        raise ValueError(
            f"Plataforma não reconhecida: '{platform_slug}'. "
            f"Registradas: {list(HANDLERS.keys())}"
        )
    return cls(captcha_solver=captcha_solver, **kwargs)
