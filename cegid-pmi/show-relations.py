#!/usr/bin/env python3
"""
Affiche les relations d'une table SQL Server :
  1. Clés étrangères formelles (FK déclarées)
  2. Relations implicites par nom de colonne commun avec d'autres tables

Usage: .venv/bin/python show-relations.py NOM_TABLE
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


def get_fk(conn, schema: str, table: str) -> list[dict]:
    """Clés étrangères formelles depuis et vers la table."""
    cur = conn.cursor(as_dict=True)
    cur.execute(
        """
        SELECT
            fk.name                                                        AS fk_name,
            SCHEMA_NAME(tp.schema_id) + '.' + tp.name                     AS table_source,
            COL_NAME(fkc.parent_object_id, fkc.parent_column_id)          AS col_source,
            SCHEMA_NAME(tr.schema_id) + '.' + tr.name                     AS table_cible,
            COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id)  AS col_cible,
            'SORTANTE'                                                     AS direction
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables tp ON tp.object_id = fk.parent_object_id
        JOIN sys.tables tr ON tr.object_id = fk.referenced_object_id
        JOIN sys.schemas sp ON sp.schema_id = tp.schema_id
        WHERE sp.name = %s AND tp.name = %s

        UNION ALL

        SELECT
            fk.name,
            SCHEMA_NAME(tp.schema_id) + '.' + tp.name,
            COL_NAME(fkc.parent_object_id, fkc.parent_column_id),
            SCHEMA_NAME(tr.schema_id) + '.' + tr.name,
            COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id),
            'ENTRANTE'
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables tp ON tp.object_id = fk.parent_object_id
        JOIN sys.tables tr ON tr.object_id = fk.referenced_object_id
        JOIN sys.schemas sr ON sr.schema_id = tr.schema_id
        WHERE sr.name = %s AND tr.name = %s

        ORDER BY direction, fk_name
        """,
        (schema, table, schema, table),
    )
    return cur.fetchall()


def get_implicit_relations(conn, schema: str, table: str) -> list[dict]:
    """
    Détecte les relations implicites selon la convention Cegid PMI :
      - Correspondance exacte de nom de colonne (même nom dans d'autres tables)
      - Correspondance par suffixe métier : strip les 2 premiers chars (préfixe table)
        et compare le reste — ex: ECCTCODE ↔ CLKTCODE (suffixe commun "TCODE")
    """
    cur = conn.cursor(as_dict=True)
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (schema, table),
    )
    source_cols = cur.fetchall()

    if not source_cols:
        return []

    # Construit un dict suffixe → colonne source (suffixe = colonne[2:])
    suffix_map: dict[str, dict] = {}
    for c in source_cols:
        suffix = c["COLUMN_NAME"][2:]  # retire le préfixe 2 lettres
        if len(suffix) >= 4:           # ignore les suffixes trop courts
            suffix_map[suffix] = c

    # Cherche dans toutes les autres tables les colonnes avec le même suffixe
    cur.execute(
        """
        SELECT
            c.COLUMN_NAME,
            c.TABLE_SCHEMA,
            c.TABLE_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE NOT (c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s)
        """,
        (schema, table),
    )
    all_other_cols = cur.fetchall()

    results = []
    seen = set()

    for c in all_other_cols:
        other_suffix = c["COLUMN_NAME"][2:]
        if other_suffix not in suffix_map:
            continue
        src = suffix_map[other_suffix]
        key = (src["COLUMN_NAME"], c["TABLE_SCHEMA"], c["TABLE_NAME"], c["COLUMN_NAME"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "col_source":   src["COLUMN_NAME"],
            "col_cible":    c["COLUMN_NAME"],
            "schema_lie":   c["TABLE_SCHEMA"],
            "table_liee":   c["TABLE_NAME"],
            "type_src":     src["DATA_TYPE"],
            "type_dst":     c["DATA_TYPE"],
            "match":        "suffixe" if src["COLUMN_NAME"] != c["COLUMN_NAME"] else "exact",
        })

    results.sort(key=lambda r: (r["table_liee"], r["col_source"]))
    return results


def fmt_table(headers: list[str], rows: list[tuple], right_align: set[int] = set()) -> None:
    if not rows:
        print("  (aucun résultat)")
        return

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


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} NOM_TABLE")
        sys.exit(1)

    conn = get_connection()
    schema, table = resolve_table(conn, sys.argv[1])

    print(f"\n{'═' * 60}")
    print(f"  Relations de [{schema}].[{table}]")
    print(f"{'═' * 60}")

    # ── 1. FK formelles ───────────────────────────────────────────
    print("\n── 1. Clés étrangères formelles ──\n")
    fk_rows = get_fk(conn, schema, table)
    if not fk_rows:
        print("  (aucune clé étrangère déclarée)")
    else:
        fmt_table(
            ["Direction", "FK", "Table source", "Colonne source", "Table cible", "Colonne cible"],
            [(r["direction"], r["fk_name"], r["table_source"],
              r["col_source"], r["table_cible"], r["col_cible"])
             for r in fk_rows],
        )

    # ── 2. Relations implicites ───────────────────────────────────
    print("\n── 2. Relations implicites (convention Cegid PMI — suffixe commun) ──\n")
    impl = get_implicit_relations(conn, schema, table)
    conn.close()

    if not impl:
        print("  (aucune relation implicite trouvée)")
    else:
        fmt_table(
            ["Colonne source", "Colonne cible", "Table liée", "Match"],
            [(r["col_source"], r["col_cible"],
              f"{r['schema_lie']}.{r['table_liee']}", r["match"])
             for r in impl],
        )

    print()


if __name__ == "__main__":
    main()
