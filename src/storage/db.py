"""
Camada de acesso ao Supabase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from supabase import create_client, Client

from src.config import config
from src.utils.logger import get_logger

log = get_logger("db")


class Database:
    def __init__(self):
        self._client: Client = create_client(config.supabase_url, config.supabase_key)
        log.info("Supabase: conexión establecida")

    # ── Plataformas ───────────────────────────────────────────────────────────

    def get_platform_by_slug(self, slug: str) -> dict | None:
        resp = (
            self._client.table("platforms")
            .select("*")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    # ── Contas ────────────────────────────────────────────────────────────────

    def get_active_accounts(self, platform_slug: str | None = None) -> list[dict]:
        """
        Devolve contas activas com dados da plataforma embutidos.
        Filtra por plataforma se platform_slug for fornecido.
        """
        # Resolve platform_id antes de filtrar (evita PGRST125)
        platform_id = None
        if platform_slug:
            plat = self.get_platform_by_slug(platform_slug)
            if not plat:
                raise ValueError(f"Plataforma no encontrada: '{platform_slug}'")
            platform_id = plat["id"]

        query = (
            self._client.table("accounts")
            .select("*, platforms(id, name, slug, login_path, has_captcha)")
            .eq("is_active", True)
        )
        if platform_id:
            query = query.eq("platform_id", platform_id)

        resp = query.execute()
        return resp.data or []

    def update_account_status(
        self,
        account_id: int,
        status: str,
        error_msg: str = "",
        increment_retry: bool = False,
    ) -> None:
        now = datetime.utcnow().isoformat()
        payload: dict[str, Any] = {"status": status, "updated_at": now}

        if status == "success":
            payload["last_success_at"] = now
            payload["retry_count"] = 0
            payload["last_error_msg"] = None
        elif status in ("error", "rate_limit"):
            payload["last_error_at"] = now
            payload["last_error_msg"] = error_msg
            if increment_retry:
                self._client.rpc(
                    "increment_retry", {"account_id": account_id}
                ).execute()
        elif status == "disabled":
            payload["is_active"] = False

        payload["last_login_at"] = now
        self._client.table("accounts").update(payload).eq("id", account_id).execute()

    # ── Execuções ─────────────────────────────────────────────────────────────

    def start_run(self, account_id: int) -> int:
        resp = (
            self._client.table("scrape_runs")
            .insert({"account_id": account_id, "status": "running"})
            .execute()
        )
        return resp.data[0]["id"]

    def finish_run(
        self, run_id: int, status: str, rows: int = 0, error: str = ""
    ) -> None:
        self._client.table("scrape_runs").update(
            {
                "status": status,
                "finished_at": datetime.utcnow().isoformat(),
                "rows_imported": rows,
                "error_msg": error or None,
            }
        ).eq("id", run_id).execute()

    # ── Dados de afiliados ────────────────────────────────────────────────────

    def upsert_stats(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        # Detecta se são registos mensais ou diários pela primeira linha
        is_monthly = rows[0].get("report_month") is not None
        conflict_key = (
            "account_id,report_month,marketing_source_id"
            if is_monthly
            else "account_id,report_date,marketing_source_id"
        )

        batch_size = 500
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            self._client.table("affiliate_stats").upsert(
                batch,
                on_conflict=conflict_key,
            ).execute()
            total += len(batch)
            log.debug(f"Upsert: lote {i//batch_size + 1} — {len(batch)} filas")

        return total

    # ── Views / relatórios ───────────────────────────────────────────────────

    def get_error_accounts(self) -> list[dict]:
        """Lê a view v_error_accounts — contas activas com status erro."""
        try:
            resp = self._client.table("v_error_accounts").select("*").execute()
            return resp.data or []
        except Exception as e:
            log.error(f"Error al leer v_error_accounts: {e}")
            return []


# Singleton
db = Database()
