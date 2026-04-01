#!/usr/bin/env python3
"""
Dump complet de toutes les tables SQL Server.
Chaque ligne est préfixée par le nom de la table pour permettre un grep.

Usage: .venv/bin/python dump-db.py [> dump.txt]
       .venv/bin/python dump-db.py | grep "motclé"

Format de sortie:
  [schema.TABLE] col1=val1 | col2=val2 | col3=val3
"""

import sys
import re
from pathlib import Path

try:
    import pymssql
except ImportError:
    print("Erreur: pip install pymssql", file=sys.stderr)
    sys.exit(1)

# ── Chargement de config.sh ───────────────────────────────────────────────────
def _load_config() -> dict[str, str]:
    config_path = Path(__file__).parent / "config.sh"
    cfg: dict[str, str] = {}
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([A-Z_][A-Z0-9_]*)=["\']?(.*?)["\']?\s*$', line)
            if m:
                cfg[m.group(1)] = m.group(2)
    return cfg

_cfg     = _load_config()
DB_HOST  = _cfg.get("DB_HOST", "localhost")
DB_USER  = _cfg.get("DB_USER", "sa")
DB_PASS  = _cfg.get("DB_PASSWORD", "")
DB_NAME  = _cfg.get("DB_NAME", "")
# ──────────────────────────────────────────────────────────────────────────────

BATCH_SIZE = 1000  # lignes lues par batch pour ne pas saturer la mémoire


def get_connection():
    return pymssql.connect(
        server=DB_HOST, user=DB_USER, password=DB_PASS,
        database=DB_NAME, port=1433, tds_version="7.4",
    )


def get_tables(conn) -> list[tuple[str, str]]:
    """Retourne la liste (schema, table) triée par nom."""
    cur = conn.cursor()
    cur.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME "
        "FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
    )
    return cur.fetchall()


def dump_table(conn, schema: str, table: str) -> None:
    """Affiche toutes les lignes préfixées par [schema.TABLE]."""
    prefix = f"[{schema}.{table}]"
    cur = conn.cursor(as_dict=True)
    try:
        cur.execute(f"SELECT * FROM [{schema}].[{table}]")
    except Exception as e:
        print(f"{prefix} ERREUR: {e}", file=sys.stderr)
        return

    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            parts = " | ".join(
                f"{k}={str(v).strip().replace(chr(10), ' ').replace(chr(13), '') if v is not None else 'NULL'}"
                for k, v in row.items()
            )
            print(f"{prefix} {parts}")


def main() -> None:
    conn = get_connection()
    tables = get_tables(conn)

    print(f"# Dump de {DB_NAME} — {len(tables)} tables", file=sys.stderr)

    for i, (schema, table) in enumerate(tables, 1):
        print(f"# [{i}/{len(tables)}] {schema}.{table}", file=sys.stderr, flush=True)
        dump_table(conn, schema, table)

    conn.close()
    print(f"# Terminé.", file=sys.stderr)


if __name__ == "__main__":
    main()
