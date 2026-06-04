"""
Parser de CSVs Netrefer — multi-moeda, suporte diário e mensal.

Relatório diário  (MarketingSourceDailyFigures):
  - Tem coluna "Date" por linha
  - Chave única: account_id + report_date + marketing_source_id

Relatório mensal (MarketingSourceMonthlyFigures):
  - Sem coluna "Date" — o mês é passado externamente
  - Nova coluna "CPA Triggered"
  - Chave única: account_id + report_month + marketing_source_id
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

log = get_logger("csv_parser")

# Prefixos de moeda — ordem importa (mais longos primeiro)
CURRENCY_PREFIXES: list[tuple[str, str]] = [
    ("R$", "BRL"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("COP", "COP"),
    ("MXN", "MXN"),
    ("PEN", "PEN"),
    ("ARS", "ARS"),
    ("CLP", "CLP"),
    ("USD", "USD"),
    ("$", "USD"),
]

# Aliases multi-idioma (EN/PT principal, ES fallback)
COLUMN_ALIASES: dict[str, list[str]] = {
    "date": ["Date", "Fecha"],
    "marketing_source_id": ["Marketing Source ID", "ID de fuentes de marketing"],
    "marketing_source_name": [
        "Marketing Source Name",
        "Nombre de la fuente de marketing",
    ],
    "views": ["Views", "Consultas"],
    "unique_views": ["Unique Views", "Consultas únicas"],
    "clicks": ["Clicks", "Clics"],
    "unique_clicks": ["Unique Clicks", "Clics únicos"],
    "ctr": ["CTR"],
    "signups": ["Signups", "Inscripciones"],
    "depositing_customers": ["Depositing Customers", "Clientes que depositan"],
    "active_customers": ["Active Customers", "Clientes activos"],
    "new_depositing_customers": [
        "New Depositing Customers",
        "Nuevos clientes que depositan",
    ],
    "new_active_customers": ["New Active Customers", "Nuevos clientes activos"],
    "first_time_depositing_customers": [
        "First Time Depositing Customers",
        "Primeros clientes que depositan",
    ],
    "first_time_active_customers": [
        "First Time Active Customers",
        "Primeros clientes activos",
    ],
    "cpa_triggered": ["CPA Triggered"],  # só no relatório mensal
    "deposits": ["Deposits", "Depósitos"],
    "turnover": ["Turnover", "Facturación"],
    "net_revenue": ["Net Revenue", "Ingresos netos"],
}


class NetreferCsvParser:

    def __init__(
        self,
        account_id: int,
        platform_id: int,
        operador: str = "",
        username: str = "",
        platform_name: str = "",
    ):
        self.account_id = account_id
        self.platform_id = platform_id
        self.operador = operador
        self.username = username
        self.platform_name = platform_name

    def parse_daily(
        self, csv_path: str | Path, scrape_run_id: int | None = None
    ) -> list[dict]:
        """
        Relatório diário — tem coluna Date por linha.
        Chave única: account_id + report_date + marketing_source_id
        """
        df, col_map = self._load(csv_path)
        if "date" not in col_map:
            raise ValueError(
                f"Coluna 'Date' não encontrada no CSV diário. Colunas: {list(df.columns)}"
            )
        rows = []
        for _, row in df.iterrows():
            record = self._map_row(row, col_map, scrape_run_id)
            if record is None:
                continue
            report_date = _parse_date(row.get(col_map["date"], ""))
            if not report_date:
                continue
            record["report_date"] = report_date
            record["report_month"] = None
            rows.append(record)
        log.info(f"Diário: {len(rows)} registos parseados de {Path(csv_path).name}")
        return rows

    def parse_monthly(
        self, csv_path: str | Path, report_month: str, scrape_run_id: int | None = None
    ) -> list[dict]:
        """
        Relatório mensal — sem coluna Date.
        report_month: string ISO do primeiro dia do mês (ex: "2026-06-01")
        Chave única: account_id + report_month + marketing_source_id
        """
        from datetime import date as _date
        today = _date.today().isoformat()

        df, col_map = self._load(csv_path)
        rows = []
        for _, row in df.iterrows():
            record = self._map_row(row, col_map, scrape_run_id)
            if record is None:
                continue
            record["report_date"] = today
            record["report_month"] = report_month
            rows.append(record)
        log.info(f"Mensal: {len(rows)} registos parseados de {Path(csv_path).name}")
        return rows

    def _load(self, csv_path: str | Path) -> tuple[pd.DataFrame, dict[str, str]]:
        """Carrega CSV e constrói mapa de colunas. Filtra linha de totais."""
        path = Path(csv_path)
        log.info(f"A parsear {path.name}")
        df = pd.read_csv(path, dtype=str)
        log.debug(f"CSV carregado: {len(df)} linhas, colunas: {list(df.columns)}")

        # Remove linha de totais (Marketing Source ID == "Totals:" ou similar)
        id_col = next(
            (
                c
                for c in df.columns
                if "Marketing Source ID" in c or "ID de fuentes" in c
            ),
            None,
        )
        if id_col:
            df = df[
                ~df[id_col].str.strip().str.lower().str.startswith("total")
            ].reset_index(drop=True)
        # Também filtra por coluna Date se existir
        date_col = next((c for c in df.columns if c in ("Date", "Fecha")), None)
        if date_col:
            df = df[
                ~df[date_col].str.strip().str.lower().str.startswith("total")
            ].reset_index(drop=True)

        log.debug(f"Após filtro totais: {len(df)} linhas")
        col_map = self._build_column_map(df.columns.tolist())
        return df, col_map

    def _build_column_map(self, csv_columns: list[str]) -> dict[str, str]:
        result = {}
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in csv_columns:
                    result[canonical] = alias
                    break
        return result

    def _map_row(
        self, row: pd.Series, col_map: dict[str, str], run_id: int | None
    ) -> dict | None:
        def get(canonical: str) -> Any:
            col = col_map.get(canonical)
            return row[col] if col else None

        source_id = _to_int(get("marketing_source_id"))
        if source_id is None:
            return None

        currency = _detect_currency_from_row(
            [get("deposits"), get("turnover"), get("net_revenue")]
        )

        return {
            "account_id": self.account_id,
            "platform_id": self.platform_id,
            "scrape_run_id": run_id,
            "platform_name": self.platform_name,
            "operador": self.operador,
            "account_username": self.username,
            "marketing_source_id": source_id,
            "marketing_source_name": _to_str(get("marketing_source_name")),
            "views": _to_int(get("views")),
            "unique_views": _to_int(get("unique_views")),
            "clicks": _to_int(get("clicks")),
            "unique_clicks": _to_int(get("unique_clicks")),
            "ctr": _parse_pct(get("ctr")),
            "signups": _to_int(get("signups")),
            "depositing_customers": _to_int(get("depositing_customers")),
            "active_customers": _to_int(get("active_customers")),
            "new_depositing_customers": _to_int(get("new_depositing_customers")),
            "new_active_customers": _to_int(get("new_active_customers")),
            "first_time_depositing_customers": _to_int(
                get("first_time_depositing_customers")
            ),
            "first_time_active_customers": _to_int(get("first_time_active_customers")),
            "cpa_triggered": _to_int(get("cpa_triggered")),
            "deposits": _parse_money(get("deposits")),
            "turnover": _parse_money(get("turnover")),
            "net_revenue": _parse_money(get("net_revenue")),
            "currency": currency,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_currency_from_row(values: list[Any]) -> str:
    for val in values:
        if val is None:
            continue
        code = _detect_currency_from_string(str(val).strip())
        if code:
            return code
    return "USD"


def _detect_currency_from_string(val: str) -> str | None:
    val = val.lstrip()
    for prefix, code in CURRENCY_PREFIXES:
        if val.startswith(prefix):
            return code
    return None


def _parse_money(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    is_negative = "-" in s
    digits_only = re.sub(r"[^\d.,]", "", s).replace(",", "")
    parts = digits_only.split(".")
    if len(parts) > 2:
        digits_only = parts[0] + "." + "".join(parts[1:])
    if not digits_only:
        return None
    try:
        value = float(digits_only)
        return round(-value if is_negative else value, 2)
    except ValueError:
        return None


def _parse_date(val: Any) -> str | None:
    if not val or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(str(val).strip(), dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_pct(val: Any) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return round(float(str(val).strip().replace("%", "")) / 100, 6)
    except ValueError:
        return None


def _to_int(val: Any) -> int | None:
    if val is None or str(val).strip() in ("", "nan"):
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _to_str(val: Any) -> str | None:
    if val is None or str(val).strip() in ("", "nan", "None"):
        return None
    return str(val).strip()
