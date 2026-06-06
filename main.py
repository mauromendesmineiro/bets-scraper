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
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.config import config
from src.scraper.captcha import CaptchaSolver
from src.scraper.login import get_handler
from src.storage.db import db
from src.utils.notify import send_error_report
from src.storage.csv_parser import NetreferCsvParser
from datetime import date as date_type
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
        log.error(f"Password não encontrada para {username} — env: {env_key}")
        if not dry_run:
            db.update_account_status(
                account_id, "error", f"Password env var não definida: {env_key}"
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

            if status == "RATE_LIMIT":
                log.warning(
                    f"Rate limit — aguardando {config.rate_limit_wait}s e a tentar novamente..."
                )
                time.sleep(config.rate_limit_wait)
                # Nova tentativa com contexto limpo
                context.close()
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(config.default_timeout)
                status = handler.login(page, login_url, username, password)

            if status != "SUCCESS":
                log.warning(f"Login falhou: {status}")
                if not dry_run:
                    db.update_account_status(
                        account_id, "error", status, increment_retry=True
                    )
                    if run_id:
                        db.finish_run(run_id, "error", error=status)
                    if status == "ACCOUNT_DISABLED":
                        db.update_account_status(account_id, "disabled")
                browser.close()
                return

            log.info("Login OK — a navegar para relatório...")

            # ── Download CSV ───────────────────────────────────────────────
            csv_path = download_report(page, account, handler=handler, username=username, password=password)

            if not csv_path:
                log.warning("CSV não descarregado — sem dados para importar")
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
            # report_month: primeiro dia do mês actual (ex: "2026-06-01")
            report_month = date_type.today().replace(day=1).isoformat()
            rows = parser.parse_monthly(
                csv_path, report_month=report_month, scrape_run_id=run_id
            )

            if not dry_run:
                if rows:
                    imported = db.upsert_stats(rows)
                    log.info(f"Importados {imported} registos no Supabase")
                else:
                    imported = 0
                db.update_account_status(account_id, "success")
                if run_id:
                    db.finish_run(run_id, "success", rows=imported)
            elif dry_run:
                log.info(f"[DRY RUN] {len(rows)} registos seriam importados")

        except Exception as e:
            log.exception(f"Erro inesperado em {username}: {e}")
            if not dry_run:
                db.update_account_status(
                    account_id, "error", str(e), increment_retry=True
                )
                if run_id:
                    db.finish_run(run_id, "error", error=str(e))
        finally:
            browser.close()


def download_report(
    page: Page, account: dict, handler=None, username: str = "", password: str = ""
) -> Path | None:
    """
    Navega para o relatório MarketingSourceDailyFigures, preenche o período,
    pesquisa e descarrega o CSV.

    Problemas conhecidos e soluções:
    - Campo de data não limpa com fill() → usa triple_click + type()
    - Tabela pode já ter dados do período default (não pesquisar novamente = dados errados)
    - Botão CSV só aparece depois da tabela renderizar
    """
    from urllib.parse import urlparse

    # ── 1. Navega para o relatório mensal ────────────────────────────────────
    parsed = urlparse(account["login_url"])
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    report_url = f"{base_url}/affiliates/Reports/MarketingSourceMonthlyFigures"

    # Define idioma EN via fetch silencioso (sem carregar página extra)
    lang_path = "/affiliates/Home/UpdateUserLanguage?languageID=1"
    try:
        page.evaluate(f"fetch('{lang_path}')")
        log.debug("Idioma definido para EN (fetch silencioso)")
    except Exception:
        pass

    page.goto(report_url, wait_until="domcontentloaded")
    log.info(f"A navegar para: {report_url}")

    # Detecta redirecionamento para login pela presença do formulário de login,
    # não pela URL (alguns domínios como login.dafabetaffiliates.com contêm "login" sempre)
    if page.locator("#txtUsername, #username, input[name='username']").count() > 0:
        log.warning("Sessão expirou — redirecionado para login, a tentar novo login...")
        if handler and username and password:
            status = handler.login(page, account["login_url"], username, password)
            if status != "SUCCESS":
                log.error(f"Re-login falhou: {status}")
                return None
            page.goto(report_url, wait_until="domcontentloaded")
            if page.locator("#txtUsername, #username, input[name='username']").count() > 0:
                log.error("Sessão expirou novamente após re-login")
                return None
            log.info("Re-login bem-sucedido — a continuar")
        else:
            log.error("Sessão expirou — sem dados para re-login")
            return None

    # ── 2. Selecciona o mês actual no dropdown ────────────────────────────────
    # O selector #selectedDateFrom é agora um <select> com options "Jun 2026", etc.
    # Seleccionamos sempre a primeira opção (mês actual)
    try:
        page.wait_for_selector("#selectedDateFrom", state="visible", timeout=8000)
        # Selecciona o primeiro option (mês mais recente)
        page.select_option("#selectedDateFrom", index=0)
        log.debug("Mês seleccionado: primeira opção do dropdown")
    except Exception as e:
        log.warning(f"Erro ao seleccionar mês: {e}")

    # ── 4. Clica em Pesquisar ─────────────────────────────────────────────────
    # Tenta vários selectores possíveis para o botão de pesquisa
    btn_candidates = [
        "#btnSearchMarketingMonthlyFigures",
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
                log.debug(f"Botão de pesquisa clicado: {btn_sel}")
                break
        except Exception:
            continue
    if not btn_clicked:
        # Log todos os botões visíveis para debug
        btns = page.evaluate(
            "() => [...document.querySelectorAll('button,input[type=submit]')].map(b => ({id:b.id,text:b.textContent.trim().slice(0,30)}))"
        )
        log.error(f"Botão de pesquisa não encontrado. Botões na página: {btns}")
        return None

    # ── 5. Aguarda resultado ──────────────────────────────────────────────────
    SELECTOR_DATA = "#marketingSourceMonthlyFiguresDataTable tbody tr"
    SELECTOR_NODATA = "#jsDivGenericValidation"

    # Aguarda linhas na tabela OU mensagem sem dados (único wait, sem spinner intermédio)
    try:
        page.locator(f"{SELECTOR_DATA}, {SELECTOR_NODATA}").first.wait_for(
            state="visible", timeout=35000
        )
    except Exception:
        if page.locator(SELECTOR_DATA).count() > 0:
            log.debug("Tabela já tinha dados — continuando")
        else:
            log.warning("Timeout a aguardar dados do relatório (35s)")
            return None

    # Sem dados — não é erro
    if (
        page.locator(SELECTOR_NODATA).count() > 0
        and page.locator(SELECTOR_NODATA).is_visible()
    ):
        log.info("Relatório sem dados para o período")
        return None

    row_count = page.locator(SELECTOR_DATA).count()
    log.info(f"Tabela carregada com {row_count} linhas")

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
        log.info(f"CSV guardado: {csv_path}")
        return csv_path
    except Exception as e:
        log.error(f"Erro no download do CSV: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Scraper de afiliados de apostas",
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
    parser.add_argument("--platform", help="Slug da plataforma (ex: netrefer)")
    parser.add_argument(
        "--accounts",
        nargs="+",
        type=int,
        metavar="ID",
        help="IDs de contas específicas a processar (ex: --accounts 25 31 42)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Não escreve no DB")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"Início — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        log.info("[DRY RUN] Nenhuma escrita no Supabase")

    # Inicializa captcha solver (só se a key estiver definida)
    captcha_solver = None
    if config.captcha_api_key:
        captcha_solver = CaptchaSolver(config.captcha_api_key)
        log.info("2captcha: solver iniciado")

    # Busca contas activas
    accounts = db.get_active_accounts(platform_slug=args.platform)

    # Filtra por IDs específicos se --accounts foi passado
    if args.accounts:
        accounts = [a for a in accounts if a["id"] in args.accounts]
        log.info(
            f"Filtro --accounts aplicado: {args.accounts} → {len(accounts)} conta(s)"
        )
    else:
        log.info(f"{len(accounts)} contas activas")

    if not accounts:
        log.warning(
            "Nenhuma conta encontrada com os critérios especificados — a terminar"
        )
        sys.exit(0)

    for i, account in enumerate(accounts, 1):
        log.info(f"[{i}/{len(accounts)}] A processar conta ID {account['id']}")
        process_account(account, captcha_solver, dry_run=args.dry_run)
        time.sleep(config.sleep_between_accounts)

    log.info("=" * 60)

    # ── Relatório de erros por email ──────────────────────────────
    if not args.dry_run:
        error_accounts = db.get_error_accounts()
        if error_accounts:
            log.info(f"{len(error_accounts)} conta(s) com erro — a enviar email...")
            send_error_report(error_accounts)
        else:
            log.info("Sem erros — email não enviado")

    log.info("Finalizado")


if __name__ == "__main__":
    main()
