"""
Resolução de captcha de imagem via 2captcha.
Custo estimado: ~$1/mês para 6 sites × 3 execuções/dia.

Fluxo:
1. Captura screenshot do elemento captcha na página
2. Envia imagem em base64 para a API do 2captcha
3. Aguarda a resolução (10–30s)
4. Devolve o texto para preenchimento no input
"""

import base64
import time
import httpx
from playwright.sync_api import Page

from src.utils.logger import get_logger

log = get_logger("captcha")


class CaptchaError(Exception):
    pass


class CaptchaSolver:
    BASE_URL = "http://2captcha.com"

    def __init__(self, api_key: str):
        if not api_key:
            raise CaptchaError(
                "TWOCAPTCHA_API_KEY não está definida. É necessária para sites com captcha."
            )
        self.api_key = api_key

    def solve_image(
        self, page: Page, captcha_selector: str, max_wait: int = 120
    ) -> str:
        """
        Captura o elemento captcha e resolve via 2captcha.

        Args:
            page: Instância Playwright activa
            captcha_selector: CSS selector do elemento <img> do captcha
            max_wait: Segundos máximos de espera pela resposta

        Returns:
            Texto do captcha resolvido
        """
        log.info("Capturando imagem do captcha...")

        # 1. Screenshot do elemento captcha (mais preciso que página inteira)
        element = page.locator(captcha_selector)
        img_bytes = element.screenshot()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        # 2. Submete para 2captcha
        log.info("Enviando captcha ao 2captcha...")
        captcha_id = self._submit(img_b64)
        log.info(f"Captcha enviado — ID: {captcha_id}")

        # 3. Aguarda resultado (polling a cada 5s)
        result = self._poll(captcha_id, max_wait)
        log.info(f"Captcha resolvido: '{result}'")
        return result

    def solve_from_page_screenshot(self, page: Page, region: dict | None = None) -> str:
        """
        Alternativa: captura região específica da página em vez de elemento isolado.
        Útil quando o captcha é um canvas ou não tem selector claro.

        Args:
            region: {"x": int, "y": int, "width": int, "height": int}
        """
        if region:
            img_bytes = page.screenshot(clip=region)
        else:
            img_bytes = page.screenshot()

        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        captcha_id = self._submit(img_b64)
        return self._poll(captcha_id)

    def _submit(self, img_b64: str) -> str:
        """Envia imagem e devolve o ID da tarefa no 2captcha."""
        resp = httpx.post(
            f"{self.BASE_URL}/in.php",
            data={
                "key": self.api_key,
                "method": "base64",
                "body": img_b64,
                "json": 1,
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("status") != 1:
            raise CaptchaError(
                f"2captcha recusou a imagem: {data.get('error_text', data)}"
            )
        return str(data["request"])

    def _poll(self, captcha_id: str, max_wait: int = 120) -> str:
        """Aguarda resolução com polling a cada 5 segundos."""
        waited = 0
        interval = 5

        # 2captcha precisa de ~10s para processar — espera inicial
        time.sleep(10)

        while waited < max_wait:
            resp = httpx.get(
                f"{self.BASE_URL}/res.php",
                params={
                    "key": self.api_key,
                    "action": "get",
                    "id": captcha_id,
                    "json": 1,
                },
                timeout=15,
            )
            data = resp.json()

            if data.get("status") == 1:
                return str(data["request"])

            if data.get("request") != "CAPCHA_NOT_READY":
                raise CaptchaError(f"Erro 2captcha: {data}")

            time.sleep(interval)
            waited += interval

        raise CaptchaError(
            f"Tempo esgotado aguardando resolução do captcha ({max_wait}s)"
        )

    def report_bad(self, captcha_id: str) -> None:
        """Reporta captcha mal resolvido para reembolso automático."""
        try:
            httpx.get(
                f"{self.BASE_URL}/res.php",
                params={"key": self.api_key, "action": "reportbad", "id": captcha_id},
                timeout=10,
            )
        except Exception:
            pass
