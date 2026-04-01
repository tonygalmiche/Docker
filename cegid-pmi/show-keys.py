#!/usr/bin/env python3
"""
Affiche les clés primaires et uniques d'une table SQL Server.

Usage: .venv/bin/python show-keys.py NOM_TABLE
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

_cfg        = _load_config()
DB_HOST     = _cfg.get("DB_HOST", "localhost")
DB_USER     = _cfg.get("DB_USER", "sa")
DB_PASSWORD = _cfg.get("DB_PASSWORD", "")
DB_NAME     = _cfg.get("DB_NAME", "")
# ──────────────────────────────────────────────────────────────────────────────


def get_connection():
    return pymssql.connect(
        server=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, port=1433, tds_version="7.4",
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


def get_keys(conn, schema: str, table: str) -> list[dict]:
    """
    Retourne les index PRIMARY KEY, UNIQUE (contraintes et index simples).
    """
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT
            i.name                   AS constraint_name,
            CASE
                WHEN i.is_primary_key = 1 THEN 'PRIMARY KEY'
                WHEN i.is_unique_constraint = 1 THEN 'UNIQUE CONSTRAINT'
                WHEN i.is_unique = 1 THEN 'UNIQUE INDEX'
                ELSE i.type_desc
            END                      AS constraint_type,
            c.name                   AS column_name,
            ic.key_ordinal           AS key_order,
            CASE ic.is_descending_key WHEN 1 THEN 'DESC' ELSE 'ASC' END AS sort
        FROM sys.indexes i
        JOIN sys.index_columns ic
            ON ic.object_id = i.object_id
           AND ic.index_id  = i.index_id
        JOIN sys.columns c
            ON c.object_id  = ic.object_id
           AND c.column_id  = ic.column_id
        JOIN sys.tables t
            ON t.object_id  = i.object_id
        JOIN sys.schemas s
            ON s.schema_id  = t.schema_id
        WHERE s.name = %s AND t.name = %s
          AND (i.is_primary_key = 1 OR i.is_unique = 1)
          AND ic.is_included_column = 0
        ORDER BY i.is_primary_key DESC, i.name, ic.key_ordinal
        """,
        (schema, table),
    )
    return cur.fetchall()


def print_keys(rows: list[dict]) -> None:
    if not rows:
        print("Aucune clé primaire ou unique trouvée.")
        return

    # Regrouper par contrainte
    constraints: dict[str, dict] = {}
    for r in rows:
        name = r["constraint_name"]
        if name not in constraints:
            constraints[name] = {
                "type": r["constraint_type"].replace("_", " "),
                "columns": [],
            }
        constraints[name]["columns"].append(
            f"{r['column_name']} ({r['sort']})"
        )

    # Affichage
    col_headers = ["Contrainte", "Type", "Colonnes"]
    display_rows = [
        (name, info["type"], ", ".join(info["columns"]))
        for name, info in constraints.items()
    ]

    widths = [len(h) for h in col_headers]
    for row in display_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells):
        return "| " + " | ".join(f"{cell:<{widths[i]}}" for i, cell in enumerate(cells)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print(sep)
    print(fmt(col_headers))
    print(sep)
    for row in display_rows:
        print(fmt(row))
    print(sep)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} NOM_TABLE")
        sys.exit(1)

    conn = get_connection()
    schema, table = resolve_table(conn, sys.argv[1])

    print(f"\nClés de [{schema}].[{table}]\n")
    rows = get_keys(conn, schema, table)
    conn.close()

    print_keys(rows)
    print()


if __name__ == "__main__":
    main()
