"""
Orquestrador principal do scraper de afiliados.

Fluxo por conta:
1. Busca contas activas no Supabase
2. Abre browser Playwright (headless)
3. Login com handler da plataforma (com ou sem captcha)
4. Download do CSV de relatório
5. Parse do CSV → schema unificado
6. Upsert no Supabase
7. Actualiza estado da conta

Uso:
    python main.py                        # todas as plataformas
    python main.py --platform netrefer    # só uma plataforma
    python main.py --dry-run              # sem escrita no DB
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.config import config
from src.scraper.captcha import CaptchaSolver
from src.scraper.login import get_handler, LoginResult
from src.scraper.status import check_login_status
from src.storage.db import db
from src.utils.notify import send_error_report
from src.storage.csv_parser import NetreferCsvParser
from src.utils.logger import get_logger

log = get_logger("main")


def process_account(
    account: dict, captcha_solver: CaptchaSolver | None, dry_run: bool = False
) -> None:
    """
    Processa uma conta completa: login → download CSV → parse → DB.
    Cada conta tem o seu próprio browser context (isolamento de cookies/sessão).
    """
    account_id = account["id"]
    platform = account["platforms"]
    slug = platform["slug"]
    login_url = account["login_url"]
    has_captcha = platform["has_captcha"]
    username = account["username"]
    operador = account.get("operador", "")

    env_key = f"PASS_{slug.upper()}_{operador.upper().replace('@','_').replace('.','_').replace(' ','_').replace('-','_')}_{username.upper().replace('@','_').replace('.','_').replace(' ','_').replace('-','_')}"
    password = __import__("os").getenv(env_key, "")
    if not password:
        log.error(f"Contraseña no encontrada para {username} — env: {env_key}")
        if not dry_run:
            db.update_account_status(
                account_id, "error", f"Contraseña env var no definida: {env_key}"
            )
        return

    log.info(f"── {platform['name']} / {operador} / {username}")

    solver = captcha_solver if has_captcha else None
    handler = get_handler(
        slug,
        captcha_solver=solver,
        timeout=config.default_timeout,
        slow_mo=config.slow_mo,
    )

    run_id = db.start_run(account_id) if not dry_run else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless, slow_mo=config.slow_mo)
        context: BrowserContext = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(config.default_timeout)

        try:
            # ── Login ──────────────────────────────────────────────────────
            status = handler.login(page, login_url, username, password)

            if status == "LIMITE DE EJECUCIÓN":
                log.warning(
                    f"Limite de ejecucion - aguardando {config.rate_limit_wait}s y intentando nuevamente..."
                )
                time.sleep(config.rate_limit_wait)
                # Nova tentativa com contexto limpo
                context.close()
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(config.default_timeout)
                status = handler.login(page, login_url, username, password)

            if status != "REALIZADO":
                log.warning(f"Login fallido: {status}")
                if not dry_run:
                    db.update_account_status(
                        account_id, "error", status, increment_retry=True
                    )
                    if run_id:
                        db.finish_run(run_id, "error", error=status)
                    if status == "CUENTA BLOQUEADA":
                        db.update_account_status(account_id, "disabled")
                browser.close()
                return

            log.info("Login realizado - navegando al informe...")

            # ── Download CSV ───────────────────────────────────────────────
            csv_path = download_report(page, account, slug)

            if not csv_path:
                log.warning("CSV no descargado - sin datos para importar")
                if not dry_run:
                    db.update_account_status(account_id, "success")
                    if run_id:
                        db.finish_run(run_id, "success", rows=0)
                browser.close()
                return

            # ── Parse + DB ────────────────────────────────────────────────
            parser = NetreferCsvParser(
                account_id=account_id,
                platform_id=platform["id"],
                operador=operador,
                username=username,
                platform_name=platform["name"],
            )
            rows = parser.parse(csv_path, scrape_run_id=run_id)

            if not dry_run and rows:
                imported = db.upsert_stats(rows)
                log.info(f"Importados {imported} registros en Supabase")
                db.update_account_status(account_id, "success")
                if run_id:
                    db.finish_run(run_id, "success", rows=imported)
            elif dry_run:
                log.info(f"[DRY RUN] {len(rows)} registros serían importados")

        except Exception as e:
            log.exception(f"Error inesperado en {username}: {e}")
            if not dry_run:
                db.update_account_status(
                    account_id, "error", str(e), increment_retry=True
                )
                if run_id:
                    db.finish_run(run_id, "error", error=str(e))
        finally:
            browser.close()


def download_report(page: Page, account: dict, slug: str) -> Path | None:
    """
    Navega para o relatório MarketingSourceDailyFigures, preenche o período,
    pesquisa e descarrega o CSV.

    Problemas conhecidos e soluções:
    - Campo de data não limpa com fill() → usa triple_click + type()
    - Tabela pode já ter dados do período default (não pesquisar novamente = dados errados)
    - Botão CSV só aparece depois da tabela renderizar
    """
    from urllib.parse import urlparse

    # ── 1. Calcula período ────────────────────────────────────────────────────
    date_from = (datetime.now() - timedelta(days=config.days_window)).strftime(
        "%d-%m-%Y"
    )
    date_to = datetime.now().strftime("%d-%m-%Y")
    log.info(f"Periodo: {date_from} → {date_to}")

    # ── 2. Navega directamente para o relatório ───────────────────────────────
    parsed = urlparse(account["login_url"])
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    report_url = f"{base_url}/affiliates/Reports/MarketingSourceDailyFigures"
    log.info(f"Navegando para: {report_url}")
    page.goto(report_url, wait_until="domcontentloaded")

    if "login" in page.url.lower():
        log.error("Sesión expirada - redirigido al login")
        return None

    # ── 2b. Força idioma Inglês ───────────────────────────────────────────────
    # Navega para o URL de mudança de idioma (languageID=1 = English)
    # Garante que os cabeçalhos do CSV são sempre em EN independentemente
    # do idioma configurado pelo operador
    lang_url = f"{base_url}/affiliates/Home/UpdateUserLanguage?languageID=1"
    page.goto(lang_url, wait_until="domcontentloaded")
    log.debug("Idioma establecido en EN")

    # Navega agora para o relatório
    page.goto(report_url, wait_until="domcontentloaded")
    if "login" in page.url.lower():
        log.error("Sesión expirada después del cambio de idioma")
        return None

    # ── 3. Preenche datas ─────────────────────────────────────────────────────
    # selectedDateTo já vem com hoje por default — só preenche o DateFrom
    for sel, val in [("#selectedDateFrom", date_from)]:
        try:
            page.wait_for_selector(sel, state="visible", timeout=8000)
            page.click(sel)
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.keyboard.type(val, delay=80)
            page.keyboard.press("Tab")
            time.sleep(0.3)
            log.debug(f"Fecha rellenada: {sel} = {val}")
        except Exception as e:
            log.warning(f"Error al rellenar {sel}: {e}")

    # ── 4. Clica em Pesquisar ─────────────────────────────────────────────────
    # Tenta vários selectores possíveis para o botão de pesquisa
    btn_candidates = [
        "#btnSearchMarketingDailyFigures",
        "#btnSearch",
        "button[id*='Search']",
        "input[id*='Search']",
        "button[id*='search']",
    ]
    btn_clicked = False
    for btn_sel in btn_candidates:
        try:
            el = page.locator(btn_sel).first
            if el.count() > 0 and el.is_visible():
                el.click()
                btn_clicked = True
                log.debug(f"botón de búsqueda presionado: {btn_sel}")
                break
        except Exception:
            continue
    if not btn_clicked:
        # Log todos os botões visíveis para debug
        btns = page.evaluate(
            "() => [...document.querySelectorAll('button,input[type=submit]')].map(b => ({id:b.id,text:b.textContent.trim().slice(0,30)}))"
        )
        log.error(f"No se encontró el botón de búsqueda. Botones en la página: {btns}")
        return None

    # ── 5. Aguarda resultado ──────────────────────────────────────────────────
    SELECTOR_DATA = "#marketingSourceDailyFiguresDataTable tbody tr"
    SELECTOR_NODATA = "#jsDivGenericValidation"

    # Espera o spinner desaparecer
    try:
        page.wait_for_selector(".dataTables_processing", state="hidden", timeout=5000)
    except Exception:
        pass

    # Aguarda linhas na tabela OU mensagem sem dados
    try:
        page.locator(f"{SELECTOR_DATA}, {SELECTOR_NODATA}").first.wait_for(
            state="visible", timeout=30000
        )
    except Exception:
        # Verifica se a tabela já tem linhas mesmo sem o wait ter disparado
        if page.locator(SELECTOR_DATA).count() > 0:
            log.debug("Tabla ya tenía datos - continuando")
        else:
            log.warning("Tiempo de espera agotado para los datos del informe (30s)")
            return None

    # Sem dados — não é erro
    if (
        page.locator(SELECTOR_NODATA).count() > 0
        and page.locator(SELECTOR_NODATA).is_visible()
    ):
        log.info("El relatório no tiene datos para el período")
        return None

    row_count = page.locator(SELECTOR_DATA).count()
    log.info(f"Tabla cargada con {row_count} filas")

    # ── 6. Download CSV ───────────────────────────────────────────────────────
    output_dir = Path(config.data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plataforma = account["platforms"]["name"].replace(" ", "_")
    file_name = (account.get("file_name") or "report").replace(" ", "_")
    csv_path = output_dir / f"{plataforma}_{file_name}.csv"

    try:
        # Garante que o botão CSV está visível antes de clicar
        csv_btn = page.locator("a.dt-button.buttons-csv, .dt-button.buttons-csv")
        csv_btn.wait_for(state="visible", timeout=5000)

        with page.expect_download() as dl_info:
            csv_btn.click()

        download = dl_info.value
        download.save_as(csv_path)
        log.info(f"Archivo CSV guardado: {csv_path}")
        return csv_path
    except Exception as e:
        log.error(f"Error al descargar el archivo CSV: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Scraper de afiliados de apuestas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py                                          # todas as contas
  python main.py --platform netrefer                     # só Netrefer
  python main.py --accounts 25                           # só conta ID 25
  python main.py --accounts 25 31 42                     # contas específicas
  python main.py --accounts 25 --dry-run                 # sem escrever no DB
  python main.py --platform netrefer --dry-run
        """,
    )
    parser.add_argument("--platform", help="Slug de la plataforma (p. ej. netrefer)")
    parser.add_argument(
        "--accounts",
        nargs="+",
        type=int,
        metavar="ID",
        help="IDs de cuentas específicas a procesar (ej. --accounts 25 31 42)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="No se guarda en la base de datos"
    )
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"Inicio — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        log.info("[DRY RUN] No hay entradas en Supabase")

    # Inicializa captcha solver (só se a key estiver definida)
    captcha_solver = None
    if config.captcha_api_key:
        captcha_solver = CaptchaSolver(config.captcha_api_key)
        log.info("2captcha: resolución iniciada")

    # Busca contas activas
    accounts = db.get_active_accounts(platform_slug=args.platform)

    # Filtra por IDs específicos se --accounts foi passado
    if args.accounts:
        accounts = [a for a in accounts if a["id"] in args.accounts]
        log.info(
            f"Se ha aplicado el filtro --accounts: {args.accounts} → {len(accounts)} cuenta(s)"
        )
    else:
        log.info(f"{len(accounts)} cuentas activas")

    if not accounts:
        log.warning(
            "No se ha encontrado ninguna cuenta con los criterios especificados — a terminar"
        )
        sys.exit(0)

    for i, account in enumerate(accounts, 1):
        log.info(f"[{i}/{len(accounts)}] Procesando cuenta ID {account['id']}")
        process_account(account, captcha_solver, dry_run=args.dry_run)
        time.sleep(config.sleep_between_accounts)

    log.info("=" * 60)

    # ── Relatório de erros por email ──────────────────────────────
    if not args.dry_run:
        error_accounts = db.get_error_accounts()
        if error_accounts:
            log.info(
                f"{len(error_accounts)} cuenta(s) con error — enviar correo electrónico..."
            )
            send_error_report(error_accounts)
        else:
            log.info("Sin errores: el correo electrónico no se ha enviado")

    log.info("Finalizado")


if __name__ == "__main__":
    main()
