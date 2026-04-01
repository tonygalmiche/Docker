#!/usr/bin/env python3
"""
Affiche le contenu d'une table SQL Server avec colonnes alignées.
Seules les colonnes ayant au moins 2 valeurs distinctes sont affichées.

Usage: ./show-table.py NOM_TABLE [LIMITE]

Dépendance : pip install pymssql
"""

import sys
import re
from pathlib import Path

try:
    import pymssql
except ImportError:
    print("Erreur: pymssql n'est pas installé.", file=sys.stderr)
    print("  pip install pymssql", file=sys.stderr)
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

_cfg = _load_config()

DB_HOST     = _cfg.get("DB_HOST", "localhost")
DB_USER     = _cfg.get("DB_USER", "sa")
DB_PASSWORD = _cfg.get("DB_PASSWORD", "")
DB_NAME     = _cfg.get("DB_NAME", "")

DEFAULT_LIMIT = 100
MIN_DISTINCT  = 2
MAX_COL_WIDTH = 50
# ──────────────────────────────────────────────────────────────────────────────


def get_connection():
    return pymssql.connect(
        server=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=1433,
        tds_version="7.4",
    )


def resolve_table(conn, raw: str) -> tuple[str, str]:
    if "." in raw:
        schema, table = raw.split(".", 1)
        return schema, table
    cur = conn.cursor()
    cur.execute(
        "SELECT TOP 1 TABLE_SCHEMA FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = %s",
        (raw,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Table '{raw}' introuvable.", file=sys.stderr)
        sys.exit(1)
    return row[0], raw


def get_columns(conn, schema: str, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY ORDINAL_POSITION",
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def count_distinct(conn, schema: str, table: str, col: str) -> int:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(DISTINCT [{col}]) FROM [{schema}].[{table}]")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def fetch_data(conn, schema: str, table: str, cols: list[str], limit: int) -> list[dict]:
    col_list = ", ".join(f"[{c}]" for c in cols)
    cur = conn.cursor(as_dict=True)
    cur.execute(f"SELECT TOP {limit} {col_list} FROM [{schema}].[{table}]")
    return cur.fetchall()


def print_table(cols: list[str], rows: list[dict]) -> None:
    if not rows:
        print("(aucune donnée)")
        return

    widths = {c: min(len(c), MAX_COL_WIDTH) for c in cols}
    for row in rows:
        for c in cols:
            val = row.get(c)
            widths[c] = min(MAX_COL_WIDTH, max(widths[c], len(str(val).strip() if val is not None else "NULL")))

    sep    = "+" + "+".join("-" * (widths[c] + 2) for c in cols) + "+"
    header = "|" + "|".join(f" {c:<{widths[c]}} " for c in cols) + "|"

    print(sep)
    print(header)
    print(sep)
    for row in rows:
        line = "|"
        for c in cols:
            val = row.get(c)
            cell = str(val).strip() if val is not None else "NULL"
            if len(cell) > MAX_COL_WIDTH:
                cell = cell[:MAX_COL_WIDTH - 1] + "…"
            line += f" {cell:<{widths[c]}} |"
        print(line)
    print(sep)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} NOM_TABLE [LIMITE]")
        print(f"  LIMITE par défaut : {DEFAULT_LIMIT}")
        sys.exit(1)

    raw_table = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_LIMIT

    conn = get_connection()

    schema, table = resolve_table(conn, raw_table)
    print(f"Table  : [{schema}].[{table}]")
    print(f"Limite : {limit} lignes")
    print(f"Filtre : colonnes avec >= {MIN_DISTINCT} valeurs distinctes")
    print()

    all_cols = get_columns(conn, schema, table)
    if not all_cols:
        print("Aucune colonne trouvée.", file=sys.stderr)
        sys.exit(1)

    print("Analyse des colonnes...", flush=True)
    selected = []
    for col in all_cols:
        n = count_distinct(conn, schema, table, col)
        if n >= MIN_DISTINCT:
            selected.append(col)
            print(f"  ✓ {col:<40} {n} valeurs distinctes")
        else:
            print(f"  ✗ {col:<40} {n} valeur(s) distincte(s)  → ignorée")

    print()
    if not selected:
        print("Aucune colonne ne satisfait le critère.")
        sys.exit(0)

    print(f"{len(selected)} colonne(s) retenue(s) sur {len(all_cols)}")
    print()

    rows = fetch_data(conn, schema, table, selected, limit)
    conn.close()

    print(f"{len(rows)} ligne(s) affichée(s)\n")
    print_table(selected, rows)


if __name__ == "__main__":
    main()

