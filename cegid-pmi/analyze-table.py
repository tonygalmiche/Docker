#!/usr/bin/env python3
"""
Analyse une ou plusieurs tables SQL Server :
  - Nombre de valeurs distinctes par colonne (triées décroissant)
  - Index et clés (PRIMARY KEY, UNIQUE)

Usage:
  .venv/bin/python analyze-table.py NOM_TABLE   → analyse une table
  .venv/bin/python analyze-table.py             → analyse toutes les tables
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


def get_column_info(conn, schema: str, table: str) -> list[dict]:
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT
            COLUMN_NAME,
            DATA_TYPE +
            CASE
                WHEN DATA_TYPE IN ('varchar','char','nvarchar','nchar')
                THEN '(' + CAST(CHARACTER_MAXIMUM_LENGTH AS VARCHAR) + ')'
                WHEN DATA_TYPE IN ('decimal','numeric')
                THEN '(' + CAST(NUMERIC_PRECISION AS VARCHAR) + ',' + CAST(NUMERIC_SCALE AS VARCHAR) + ')'
                ELSE ''
            END AS full_type,
            IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (schema, table),
    )
    return cur.fetchall()


def count_total(conn, schema: str, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
    return cur.fetchone()[0]


def count_distinct(conn, schema: str, table: str, col: str) -> int | None:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(DISTINCT [{col}]) FROM [{schema}].[{table}]")
        return cur.fetchone()[0]
    except Exception:
        return None


def get_indexes(conn, schema: str, table: str) -> list[dict]:
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT
            i.name AS constraint_name,
            CASE
                WHEN i.is_primary_key       = 1 THEN 'PRIMARY KEY'
                WHEN i.is_unique_constraint = 1 THEN 'UNIQUE CONSTRAINT'
                WHEN i.is_unique            = 1 THEN 'UNIQUE INDEX'
                ELSE i.type_desc
            END AS constraint_type,
            c.name AS column_name,
            ic.key_ordinal AS key_order,
            CASE ic.is_descending_key WHEN 1 THEN 'DESC' ELSE 'ASC' END AS sort
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c        ON c.object_id  = ic.object_id AND c.column_id = ic.column_id
        JOIN sys.tables t         ON t.object_id  = i.object_id
        JOIN sys.schemas s        ON s.schema_id  = t.schema_id
        WHERE s.name = %s AND t.name = %s
          AND (i.is_primary_key = 1 OR i.is_unique = 1)
          AND ic.is_included_column = 0
        ORDER BY i.is_primary_key DESC, i.name, ic.key_ordinal
        """,
        (schema, table),
    )
    return cur.fetchall()


def fmt_table(headers: list[str], rows: list[tuple], right_align: set[int] = set()) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"

    def fmt(cells):
        parts = []
        for i, cell in enumerate(cells):
            s = str(cell)
            parts.append(f"{s:>{widths[i]}}" if i in right_align else f"{s:<{widths[i]}}")
        return "| " + " | ".join(parts) + " |"

    print(sep)
    print(fmt(headers))
    print(sep)
    for row in rows:
        print(fmt(row))
    print(sep)


def get_all_tables(conn) -> list[tuple[str, str]]:
    cur = conn.cursor()
    cur.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    return cur.fetchall()


def analyze_table(conn, schema: str, table: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  Table : [{schema}].[{table}]  —  {DB_NAME}")
    print(f"{'═' * 60}\n")

    total = count_total(conn, schema, table)
    print(f"Nombre total de lignes : {total:,}\n")

    print("── Colonnes (triées par valeurs distinctes décroissantes) ──\n")
    col_info = get_column_info(conn, schema, table)

    stats = []
    for c in col_info:
        n = count_distinct(conn, schema, table, c["COLUMN_NAME"])
        pct = f"{(n / total * 100):.2f}%" if (n is not None and total > 0) else "—"
        stats.append((
            c["COLUMN_NAME"],
            c["full_type"],
            c["IS_NULLABLE"],
            n if n is not None else -1,
            n if n is not None else "erreur",
            pct,
        ))

    stats.sort(key=lambda x: x[3], reverse=True)

    fmt_table(
        ["Colonne", "Type", "Nullable", "Valeurs distinctes", "% unique"],
        [(col, typ, nul, str(nd) if nd != "erreur" else "erreur", pct)
         for col, typ, nul, _, nd, pct in stats],
        right_align={3, 4},
    )

    print("\n── Index et clés ──\n")
    idx_rows = get_indexes(conn, schema, table)

    if not idx_rows:
        print("  (aucun index / clé trouvé)")
    else:
        constraints: dict[str, dict] = {}
        for r in idx_rows:
            name = r["constraint_name"]
            if name not in constraints:
                constraints[name] = {"type": r["constraint_type"], "columns": []}
            constraints[name]["columns"].append(f"{r['column_name']} ({r['sort']})")

        fmt_table(
            ["Contrainte", "Type", "Colonnes"],
            [(name, info["type"], ", ".join(info["columns"]))
             for name, info in constraints.items()],
        )

    print()


def main() -> None:
    conn = get_connection()

    if len(sys.argv) >= 2:
        schema, table = resolve_table(conn, sys.argv[1])
        analyze_table(conn, schema, table)
    else:
        tables = get_all_tables(conn)
        print(f"{len(tables)} tables trouvées dans {DB_NAME}\n")
        for i, (schema, table) in enumerate(tables, 1):
            print(f"[{i}/{len(tables)}] {schema}.{table}")
            try:
                analyze_table(conn, schema, table)
            except Exception as e:
                print(f"  ⚠ Erreur : {e}\n")

    conn.close()


if __name__ == "__main__":
    main()
