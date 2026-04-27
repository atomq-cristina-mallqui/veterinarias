"""Aplica supabase/schema.sql + supabase/seed.sql contra tu proyecto Supabase.

Hay tres formas de inicializar la base:

1. **Local con psycopg** (este script). Requiere `SUPABASE_DB_URL` en el `.env`:
       SUPABASE_DB_URL=postgresql://postgres:<PASSWORD>@db.<REF>.supabase.co:5432/postgres
   Encuéntrala en: Supabase Dashboard > Project Settings > Database > Connection string.

2. **SQL Editor de Supabase**: pega el contenido de `supabase/schema.sql` y luego
   `supabase/seed.sql` en https://supabase.com/dashboard/project/_/sql/new

3. **MCP de Supabase** desde el agente IDE: pídele al asistente "aplica el schema y seed
   con el MCP de Supabase".

Uso:
    python scripts/init_db.py            # aplica schema + seed
    python scripts/init_db.py --schema   # solo schema
    python scripts/init_db.py --seed     # solo seed
    python scripts/init_db.py --verify   # imprime conteos de tablas
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SCHEMA_PATH = ROOT / "supabase" / "schema.sql"
SEED_PATH = ROOT / "supabase" / "seed.sql"


def _get_db_url() -> str:
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        sys.stderr.write(
            "ERROR: falta SUPABASE_DB_URL en el .env.\n"
            "  Cópiala desde: Supabase Dashboard > Project Settings > Database > "
            "Connection string (URI).\n"
        )
        sys.exit(1)
    return url


def _connect():
    try:
        import psycopg  # type: ignore
    except ImportError:
        sys.stderr.write(
            "ERROR: falta `psycopg`. Instala con:\n"
            '  pip install "psycopg[binary]>=3.2"\n'
        )
        sys.exit(1)

    return psycopg.connect(_get_db_url(), autocommit=True)


def apply_sql(label: str, path: Path) -> None:
    if not path.exists():
        sys.stderr.write(f"ERROR: no existe {path}\n")
        sys.exit(1)

    print(f"==> Aplicando {label}: {path.name}")
    sql = path.read_text(encoding="utf-8")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
    print(f"    OK ({label})")


def verify() -> None:
    print("==> Verificando tablas...")
    queries = [
        ("clients",            "select count(*) from clients"),
        ("pets",               "select count(*) from pets"),
        ("rooms",              "select count(*) from rooms"),
        ("services",           "select count(*) from services"),
        ("service_durations",  "select count(*) from service_durations"),
        ("appointments",       "select count(*) from appointments"),
        ("payments",           "select count(*) from payments"),
        ("user_summaries",     "select count(*) from user_summaries"),
        ("clinic_settings",    "select count(*) from clinic_settings"),
    ]
    with _connect() as conn, conn.cursor() as cur:
        for table, q in queries:
            cur.execute(q)
            (count,) = cur.fetchone()
            print(f"    {table:20s} {count:>4d} filas")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa la BD de Supabase.")
    parser.add_argument("--schema", action="store_true", help="Aplica solo schema.sql")
    parser.add_argument("--seed",   action="store_true", help="Aplica solo seed.sql")
    parser.add_argument("--verify", action="store_true", help="Imprime conteos de tablas")
    args = parser.parse_args()

    only_verify = args.verify and not (args.schema or args.seed)
    do_schema = args.schema or not (args.schema or args.seed or args.verify)
    do_seed   = args.seed   or not (args.schema or args.seed or args.verify)

    if not only_verify:
        if do_schema:
            apply_sql("schema", SCHEMA_PATH)
        if do_seed:
            apply_sql("seed", SEED_PATH)

    if args.verify or not only_verify:
        verify()

    print("==> Listo.")


if __name__ == "__main__":
    main()
