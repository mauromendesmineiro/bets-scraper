"""
tools/migrate_from_excel.py

Migração única do Excel (logins.xlsx) para:
  1. SQL de INSERT na tabela accounts (para correr no Supabase)
  2. Ficheiro .env.passwords com as variáveis PASS_*

Uso:
    python tools/migrate_from_excel.py --excel config/logins.xlsx

O platform_id=1 é assumido como Netrefer (único por agora).
Ajusta se adicionares mais plataformas.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def sanitize_env_key(val: str) -> str:
    """Remove caracteres inválidos para nome de variável de ambiente."""
    return re.sub(r"[^A-Z0-9]", "_", val.upper())


def clean_url(url: str) -> str:
    """Remove fragmento # e espaços da URL."""
    return str(url).strip().rstrip("#").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", default="config/logins.xlsx")
    parser.add_argument(
        "--platform-id",
        type=int,
        default=1,
        help="ID da plataforma no Supabase (default: 1 = Netrefer)",
    )
    parser.add_argument("--env-output", default=".env.passwords")
    parser.add_argument("--sql-output", default="tools/migrate_accounts.sql")
    args = parser.parse_args()

    df = pd.read_excel(args.excel)
    print(f"✓ Excel carregado: {len(df)} linhas")
    print(f"  Colunas: {list(df.columns)}")

    # Só contas activas
    if "Active" in df.columns:
        df = df[df["Active"] == 1].reset_index(drop=True)
    print(f"✓ {len(df)} contas activas")

    env_lines = ["# Passwords geradas por migrate_from_excel.py — NÃO commitar!", ""]
    sql_lines = [
        "-- Migração de contas — gerado por migrate_from_excel.py",
        "-- Corre no Supabase SQL Editor após verificação",
        "",
    ]
    warnings = []

    for _, row in df.iterrows():
        username = str(row.get("Username", "")).strip()
        password = str(row.get("Password", "")).strip()
        operador = str(row.get("Operador", "")).strip()
        empresa = str(row.get("Empresa", "")).strip()
        login_url = clean_url(row.get("URL", ""))
        file_name = str(row.get("FileName", "")).strip()
        has_captcha = bool(row.get("captcha", 0) == 1)

        if not username:
            warnings.append("Linha sem username ignorada")
            continue

        if not login_url or login_url == "nan":
            warnings.append(f"  ⚠ {username}: sem URL — ignorado")
            continue

        if not password or password == "nan":
            warnings.append(f"  ⚠ {username}: sem password no Excel")

        # Variável de ambiente para a password
        # Convenção: PASS_{SLUG_PLATAFORMA}_{USERNAME_SANITIZADO}
        slug = "NETREFER"  # hardcoded por agora — ajustar se necessário
        env_key = (
            f"PASS_{slug}_{sanitize_env_key(operador)}_{sanitize_env_key(username)}"
        )
        env_lines.append(f"{env_key}={password}")

        # Escapa aspas simples para SQL
        def esc(s):
            return str(s).replace("'", "''")

        sql_lines.append(
            f"INSERT INTO accounts "
            f"(platform_id, operador, empresa, username, login_url, file_name, has_captcha) VALUES\n"
            f"  ({args.platform_id}, '{esc(operador)}', '{esc(empresa)}', "
            f"'{esc(username)}', '{esc(login_url)}', '{esc(file_name)}', {str(has_captcha).lower()})\n"
            f"ON CONFLICT (platform_id, operador, username) DO UPDATE SET\n"
            f"  operador=EXCLUDED.operador, empresa=EXCLUDED.empresa,\n"
            f"  login_url=EXCLUDED.login_url, file_name=EXCLUDED.file_name,\n"
            f"  has_captcha=EXCLUDED.has_captcha;\n"
        )

    # Escreve ficheiros
    Path(args.env_output).write_text("\n".join(env_lines), encoding="utf-8")
    print(f"\n✓ Passwords → {args.env_output}")

    Path(args.sql_output).write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"✓ SQL de migração → {args.sql_output}")

    if warnings:
        print(f"\n⚠ {len(warnings)} avisos:")
        for w in warnings:
            print(f"  {w}")

    print(f"\nTotal: {len(sql_lines) - 3} contas processadas")
    print("\nPróximos passos:")
    print("  1. Revisa tools/migrate_accounts.sql")
    print("  2. Corre no Supabase SQL Editor")
    print(f"  3. Adiciona o conteúdo de {args.env_output} ao teu .env")
    print(f"  4. Nunca commitas {args.env_output}!")


if __name__ == "__main__":
    main()
