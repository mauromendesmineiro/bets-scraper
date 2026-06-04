"""
Notificações por email via Resend.
Enviado no final de cada run com o resumo de erros da view v_error_accounts.
Só envia se houver contas com erro.
"""

from __future__ import annotations

from email import message

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.config import config
from src.utils.logger import get_logger

log = get_logger("notify")


def send_error_report(error_accounts: list[dict]) -> None:
    """
    Envia email com resumo de contas com erro.
    Não envia se a lista estiver vazia ou RESEND_API_KEY não estiver definida.
    """
    if not error_accounts:
        log.info("Sem erros para reportar — email não enviado")
        return

    # if not config.resend_api_key:
    #    log.warning("RESEND_API_KEY no definida — email no enviado")
    #    return

    if not config.smtp_user or not config.smtp_password:
        log.warning("SMTP_USER ou SMTP_PASSWORD não definidas — email não enviado")
        return

    if not config.notify_to:
        log.warning("NOTIFY_TO não definido — email não enviado")
        return

    # if not config.notify_to or not config.notify_from:
    #    log.warning("NOTIFY_TO o NOTIFY_FROM no definidos — email não enviado")
    #    return

    # resend.api_key = config.resend_api_key

    to_list = (
        [e.strip() for e in config.notify_to.split(",")] if config.notify_to else []
    )
    cc_list = (
        [e.strip() for e in config.notify_cc.split(",")] if config.notify_cc else []
    )
    bcc_list = (
        [e.strip() for e in config.notify_bcc.split(",")] if config.notify_bcc else []
    )

    all_recipients = to_list + cc_list + bcc_list

    msg = MIMEMultipart("alternative")
    msg["From"] = config.smtp_user
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    subject = (
        f"Extração de Afiliados — {len(error_accounts)} conta(s) com erro — "
        f"({datetime.now().strftime('%d/%m/%Y %H:%M')})"
    )
    msg["Subject"] = subject

    html = _build_html(error_accounts)
    msg.attach(MIMEText(html, "html"))

    try:

        log.info("Conectando ao servidor SMTP do Gmail...")
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Ativa a criptografia TLS de segurança
            server.login(config.smtp_user, config.smtp_password)
            server.send_message(
                msg, from_addr=config.smtp_user, to_addrs=all_recipients
            )

        log.info("Email enviado com sucesso via SMTP!")

    except Exception as e:
        log.error(f"Erro ao enviar email via SMTP: {e}")


def _build_html(accounts: list[dict]) -> str:
    rows = ""
    for a in accounts:
        status_color = "#e74c3c"  # vermelho para erro
        rows += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{a.get('id', '')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{a.get('name', '')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{a.get('operador', '')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{a.get('username', '')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">
                <span style="background:{status_color};color:white;padding:2px 8px;border-radius:4px;font-size:12px">
                    {a.get('status', '')}
                </span>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{a.get('last_error_at', '')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#666;font-size:13px">{a.get('last_error_msg', '')}</td>
        </tr>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px">
        <div style="max-width:800px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">

            <!-- Header -->
            <div style="background:#2c3e50;padding:24px 32px">
                <h1 style="color:white;margin:0;font-size:20px">Extração de Afiliados — Relatório de Erros</h1>
                <p style="color:#aab;margin:6px 0 0;font-size:14px">{datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>
            </div>

            <!-- Summary -->
            <div style="padding:20px 32px;background:#fff8f0;border-bottom:1px solid #ffe0b2">
                <p style="margin:0;font-size:15px;color:#e65100">
                    <strong>{len(accounts)} conta(s)</strong> com erro na última execução.
                </p>
            </div>

            <!-- Table -->
            <div style="padding:24px 32px">
                <table style="width:100%;border-collapse:collapse;font-size:14px">
                    <thead>
                        <tr style="background:#f8f9fa">
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">ID</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Plataforma</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Operador</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Username</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Status</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Data do Erro</th>
                            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #dee2e6;color:#495057">Mensagem</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="padding:16px 32px;background:#f8f9fa;border-top:1px solid #eee">
                <p style="margin:0;font-size:12px;color:#999">
                    Gerado automaticamente por Extração de Afiliados •
                    Para reprocessar as contas com erro:
                    <code style="background:#eee;padding:2px 6px;border-radius:3px">
                        python main.py --accounts {' '.join(str(a.get('id','')) for a in accounts)}
                    </code>
                </p>
            </div>
        </div>
    </body>
    </html>
    """
