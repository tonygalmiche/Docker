#!/usr/bin/env python3
"""
Recherche toutes les tables liées à une table donnée (par défaut CLIENT)
en détectant les relations par :
  1. Clés étrangères formelles (FK)
  2. Colonnes avec le même nom (jointure exacte)
  3. Colonnes avec le même suffixe (convention Cegid PMI : préfixe 2 lettres)

Affiche pour chaque table liée les champs de jointure.

Usage:
  python3 show-linked-tables.py              → relations de CLIENT
  python3 show-linked-tables.py dbo.FOURNIS  → relations de FOURNIS
"""

import sys
import subprocess
import json
import re
from pathlib import Path

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

CONTAINER = _cfg.get("CONTAINER_NAME", "cegid-pmi-sqlserver")
DB_HOST   = _cfg.get("DB_HOST", "localhost")
DB_USER   = _cfg.get("DB_USER", "sa")
DB_PASS   = _cfg.get("DB_PASSWORD", "")
DB_NAME   = _cfg.get("DB_NAME", "")
SQLCMD    = _cfg.get("SQLCMD_PATH", "/opt/mssql-tools18/bin/sqlcmd")
# ──────────────────────────────────────────────────────────────────────────────


def run_sql(query: str, db: str = DB_NAME) -> list[dict]:
    full_query = f"SET NOCOUNT ON; {query} FOR JSON PATH, INCLUDE_NULL_VALUES;"
    cmd = [
        "docker", "exec", "-i", CONTAINER,
        SQLCMD,
        "-S", DB_HOST, "-U", DB_USER, "-P", DB_PASS,
        "-d", db, "-C", "-h", "-1", "-y", "8000",
        "-Q", full_query,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = "".join(line.rstrip() for line in result.stdout.splitlines()).strip()
    if not output:
        return []
    try:
        rows = json.loads(output)
        for row in rows:
            for k, v in row.items():
                if isinstance(v, str):
                    row[k] = v.strip()
        return rows
    except json.JSONDecodeError:
        return []


def resolve_table(raw: str) -> tuple[str, str]:
    """Résout schema.table depuis un nom brut."""
    if "." in raw:
        parts = raw.split(".", 1)
        return parts[0], parts[1]
    rows = run_sql(
        f"SELECT TOP 1 s.name AS S, t.name AS T "
        f"FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id "
        f"WHERE t.name = '{raw}'"
    )
    if rows:
        return rows[0]["S"], rows[0]["T"]
    print(f"Table '{raw}' introuvable.", file=sys.stderr)
    sys.exit(1)


def get_table_columns(schema: str, table: str) -> list[dict]:
    """Retourne les colonnes d'une table."""
    return run_sql(f"""
        SELECT col.name AS COL, ty.name AS DTYPE, col.max_length AS MAXLEN
        FROM sys.columns col
        JOIN sys.tables  t  ON col.object_id = t.object_id
        JOIN sys.schemas s  ON t.schema_id   = s.schema_id
        JOIN sys.types   ty ON col.user_type_id = ty.user_type_id
        WHERE s.name = '{schema}' AND t.name = '{table}'
        ORDER BY col.column_id
    """)


def get_row_count(schema: str, table: str) -> int:
    """Retourne le nombre de lignes d'une table."""
    rows = run_sql(f"""
        SELECT SUM(p.rows) AS N
        FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0,1)
        WHERE s.name = '{schema}' AND t.name = '{table}'
    """)
    if rows:
        return rows[0].get("N", 0) or 0
    return 0


def get_fk_relations(schema: str, table: str) -> list[dict]:
    """FK formelles depuis et vers la table."""
    return run_sql(f"""
        SELECT
            fk.name AS FK,
            SCHEMA_NAME(tp.schema_id) + '.' + tp.name AS SRC_TABLE,
            COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS SRC_COL,
            SCHEMA_NAME(tr.schema_id) + '.' + tr.name AS DST_TABLE,
            COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS DST_COL,
            'SORTANTE' AS DIR
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables tp ON tp.object_id = fk.parent_object_id
        JOIN sys.tables tr ON tr.object_id = fk.referenced_object_id
        WHERE SCHEMA_NAME(tp.schema_id) = '{schema}' AND tp.name = '{table}'

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
        WHERE SCHEMA_NAME(tr.schema_id) = '{schema}' AND tr.name = '{table}'

        ORDER BY DIR, FK
    """)


def get_all_columns() -> list[dict]:
    """Retourne toutes les colonnes de toutes les tables (hors système)."""
    return run_sql("""
        SELECT s.name AS S, t.name AS T, col.name AS COL,
               ty.name AS DTYPE, col.max_length AS MAXLEN
        FROM sys.columns col
        JOIN sys.tables  t  ON col.object_id = t.object_id
        JOIN sys.schemas s  ON t.schema_id   = s.schema_id
        JOIN sys.types   ty ON col.user_type_id = ty.user_type_id
        WHERE s.name NOT IN ('OData', 'Cache')
        ORDER BY s.name, t.name, col.column_id
    """)


def find_linked_tables(schema: str, table: str):
    """Trouve toutes les tables liées par FK, nom exact ou suffixe commun."""

    print(f"\n  Chargement des colonnes de [{schema}].[{table}]...")
    src_cols = get_table_columns(schema, table)
    if not src_cols:
        print("  Aucune colonne trouvée.")
        return

    src_col_names = {c["COL"] for c in src_cols}
    # Suffixes : retire le préfixe 2 lettres (convention Cegid PMI)
    # Uniquement les colonnes clé (contenant KT, CODE, ID)
    src_suffixes = {}
    for c in src_cols:
        col = c["COL"]
        suffix = col[2:]
        if len(suffix) >= 4 and ("KT" in col.upper() or "CODE" in col.upper() or "ID" in col.upper()):
            src_suffixes[suffix] = col

    # Partie fonctionnelle : à partir du 4e caractère (2 préfixe + 2 type)
    # Ex: CLKTCODE → CODE, permet de matcher avec ECCTCODE → CODE
    # Uniquement les colonnes KT (clé technique)
    src_funcparts = {}
    for c in src_cols:
        col = c["COL"]
        if len(col) >= 7 and "KT" in col[2:4].upper():
            funcpart = col[4:]
            src_funcparts[funcpart] = col

    # ── 1. FK formelles ──────────────────────────────────────────
    print("  Recherche des clés étrangères...")
    fk_rows = get_fk_relations(schema, table)

    # ── 2. Toutes les colonnes de la base ────────────────────────
    print("  Chargement de toutes les colonnes de la base...")
    all_cols = get_all_columns()

    # Grouper par table
    tables_cols: dict[str, list[dict]] = {}
    for c in all_cols:
        key = f"{c['S']}.{c['T']}"
        if key == f"{schema}.{table}":
            continue
        tables_cols.setdefault(key, []).append(c)

    # ── Recherche des correspondances ────────────────────────────
    print("  Analyse des correspondances...")

    # Compter combien de tables ont chaque suffixe → exclure les trop fréquents
    suffix_table_count: dict[str, int] = {}
    for tbl_key, cols in tables_cols.items():
        seen_suffixes = set()
        for c in cols:
            s = c["COL"][2:]
            if s not in seen_suffixes:
                seen_suffixes.add(s)
                suffix_table_count[s] = suffix_table_count.get(s, 0) + 1

    linked: dict[str, dict] = {}  # clé = schema.table → {jointures: [...], type: ...}

    # FK formelles
    for fk in fk_rows:
        if fk["DIR"] == "SORTANTE":
            other = fk["DST_TABLE"]
            join_info = f"{fk['SRC_COL']} → {other}.{fk['DST_COL']}"
        else:
            other = fk["SRC_TABLE"]
            join_info = f"{other}.{fk['SRC_COL']} → {fk['DST_COL']}"

        if other not in linked:
            linked[other] = {"jointures": [], "type": "FK"}
        linked[other]["jointures"].append(f"FK: {join_info}")

    # Correspondances par nom exact et suffixe
    # Pour le nom exact, on ne garde que les colonnes "clé" (KT, CODE, ID, KEY)
    src_key_cols = {c for c in src_col_names
                    if "KT" in c.upper() or "CODE" in c.upper()
                    or "ID" in c.upper() or "KEY" in c.upper()}
    
    # Abréviations possibles de la table source pour la recherche par référence
    # CLIENT → CLI, FOURNIS → FOU, ARTICLE → ART, etc.
    table_abbrevs = set()
    for length in (3, 4, 5):
        if len(table) >= length:
            table_abbrevs.add(table[:length].upper())

    for tbl_key, cols in tables_cols.items():
        for c in cols:
            col_name = c["COL"]
            col_upper = col_name.upper()

            # Match exact (uniquement colonnes clé)
            if col_name in src_key_cols:
                if tbl_key not in linked:
                    linked[tbl_key] = {"jointures": [], "type": "NOM"}
                join_str = f"NOM EXACT: {table}.{col_name} = {c['T']}.{col_name}"
                if join_str not in linked[tbl_key]["jointures"]:
                    linked[tbl_key]["jointures"].append(join_str)

            # Match suffixe (ignorer si le suffixe est dans + de 10 tables → trop générique)
            suffix = col_name[2:]
            if len(suffix) >= 4 and suffix in src_suffixes and suffix_table_count.get(suffix, 0) <= 10:
                src_col = src_suffixes[suffix]
                if src_col == col_name:
                    continue  # déjà traité par le match exact
                if tbl_key not in linked:
                    linked[tbl_key] = {"jointures": [], "type": "SUFFIXE"}
                join_str = f"SUFFIXE: {table}.{src_col} ↔ {c['T']}.{col_name}  (suffixe: {suffix})"
                if join_str not in linked[tbl_key]["jointures"]:
                    linked[tbl_key]["jointures"].append(join_str)

            # Match fonctionnel : compare la partie après le 4e caractère
            # Ex: CLKTCODE[4:] = CODE = ECCTCODE[4:] (KT→CT, même donnée)
            if len(col_name) >= 7:
                funcpart = col_name[4:]
                if funcpart in src_funcparts:
                    src_col = src_funcparts[funcpart]
                    if src_col == col_name:
                        continue  # même colonne, déjà traité
                    # Vérifier que ce n'est pas déjà un match suffixe
                    suffix = col_name[2:]
                    if suffix in src_suffixes:
                        continue  # déjà traité par le match suffixe
                    if tbl_key not in linked:
                        linked[tbl_key] = {"jointures": [], "type": "FONCT"}
                    join_str = f"FONCTIONNEL: {table}.{src_col} ↔ {c['T']}.{col_name}  (partie: {funcpart})"
                    if join_str not in linked[tbl_key]["jointures"]:
                        linked[tbl_key]["jointures"].append(join_str)

            # Match par référence : colonne clé contenant l'abréviation de la table
            # Ex: ECKTCLI dans ECOMCLI référence CLIENT (abrév CLI), jointure sur CLKTCODE
            if "KT" in col_upper:
                for abbrev in table_abbrevs:
                    if abbrev in col_upper and col_name not in src_col_names:
                        if tbl_key not in linked:
                            linked[tbl_key] = {"jointures": [], "type": "REF"}
                        join_str = f"RÉFÉRENCE: {c['T']}.{col_name} → {table}.CLKTCODE  (réf: {abbrev})"
                        if join_str not in linked[tbl_key]["jointures"]:
                            linked[tbl_key]["jointures"].append(join_str)
                        break

    return linked


def find_links_between(schema1: str, table1: str, schema2: str, table2: str):
    """Trouve les liens entre deux tables spécifiques."""

    print(f"\n  Chargement des colonnes...")
    cols1 = get_table_columns(schema1, table1)
    cols2 = get_table_columns(schema2, table2)

    if not cols1 or not cols2:
        print("  Colonnes introuvables.")
        return []

    links = []

    # FK formelles entre les deux tables
    fk_rows = get_fk_relations(schema1, table1)
    target = f"{schema2}.{table2}"
    for fk in fk_rows:
        if fk["DIR"] == "SORTANTE" and fk["DST_TABLE"] == target:
            links.append(f"FK: {table1}.{fk['SRC_COL']} → {table2}.{fk['DST_COL']}")
        elif fk["DIR"] == "ENTRANTE" and fk["SRC_TABLE"] == target:
            links.append(f"FK: {table2}.{fk['SRC_COL']} → {table1}.{fk['DST_COL']}")

    # Nom exact (colonnes clé)
    cols1_keys = {c["COL"] for c in cols1
                  if "KT" in c["COL"].upper() or "CODE" in c["COL"].upper()
                  or "ID" in c["COL"].upper() or "KEY" in c["COL"].upper()}
    cols2_names = {c["COL"] for c in cols2}
    for col in cols1_keys:
        if col in cols2_names:
            links.append(f"NOM EXACT: {table1}.{col} = {table2}.{col}")

    # Suffixe commun (uniquement colonnes clé : contenant KT, CODE, ID)
    suffixes1 = {}
    for c in cols1:
        col = c["COL"]
        s = col[2:]
        if len(s) >= 4 and ("KT" in col.upper() or "CODE" in col.upper() or "ID" in col.upper()):
            suffixes1[s] = col

    for c in cols2:
        col = c["COL"]
        s = col[2:]
        if len(s) >= 4 and s in suffixes1:
            src_col = suffixes1[s]
            if src_col == col:
                continue  # déjà traité par nom exact
            links.append(f"SUFFIXE: {table1}.{src_col} ↔ {table2}.{col}  (suffixe: {s})")

    # Match fonctionnel : partie après le 4e caractère (2 préfixe + 2 type)
    # Ex: CLKTCODE[4:] = CODE = ECCTCODE[4:] → jointure malgré KT≠CT
    funcparts1 = {}
    for c in cols1:
        col = c["COL"]
        if len(col) >= 7 and "KT" in col[2:4].upper():
            funcparts1[col[4:]] = col
    funcparts2 = {}
    for c in cols2:
        col = c["COL"]
        if len(col) >= 7 and "KT" in col[2:4].upper():
            funcparts2[col[4:]] = col

    for c in cols2:
        col = c["COL"]
        if len(col) >= 7:
            fp = col[4:]
            if fp in funcparts1:
                src_col = funcparts1[fp]
                if src_col == col:
                    continue
                if col[2:] in suffixes1:
                    continue  # déjà traité par suffixe
                link = f"FONCTIONNEL: {table1}.{src_col} ↔ {table2}.{col}  (partie: {fp})"
                if link not in links:
                    links.append(link)
    for c in cols1:
        col = c["COL"]
        if len(col) >= 7:
            fp = col[4:]
            if fp in funcparts2:
                src_col = funcparts2[fp]
                if src_col == col:
                    continue
                if col[2:] in suffixes1:
                    continue  # déjà traité par suffixe
                link = f"FONCTIONNEL: {table2}.{src_col} ↔ {table1}.{col}  (partie: {fp})"
                if link not in links:
                    links.append(link)

    # Référence par abréviation du nom de table
    # Ex: ECKTCLI dans ECOMCLI → référence CLIENT (abrév CLI)
    for src_table, src_cols_list, dst_table, dst_cols_list in [
        (table1, cols1, table2, cols2),
        (table2, cols2, table1, cols1),
    ]:
        abbrevs = set()
        for length in (3, 4, 5):
            if len(src_table) >= length:
                abbrevs.add(src_table[:length].upper())

        src_names = {c["COL"] for c in src_cols_list}
        for c in dst_cols_list:
            col = c["COL"]
            if "KT" in col.upper():
                for abbrev in abbrevs:
                    if abbrev in col.upper() and col not in src_names:
                        link = f"RÉFÉRENCE: {dst_table}.{col} → {src_table}  (réf: {abbrev})"
                        if link not in links:
                            links.append(link)
                        break

    return links


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage:")
        print(f"  {sys.argv[0]} TABLE              → toutes les tables liées")
        print(f"  {sys.argv[0]} TABLE1 TABLE2       → liens entre 2 tables")
        print(f"Exemples:")
        print(f"  {sys.argv[0]} CLIENT")
        print(f"  {sys.argv[0]} CLIENT ECOMCLI")
        sys.exit(1)

    schema1, table1 = resolve_table(sys.argv[1])
    n1 = get_row_count(schema1, table1)

    if len(sys.argv) >= 3:
        # ── Mode 2 tables ────────────────────────────────────────
        schema2, table2 = resolve_table(sys.argv[2])
        n2 = get_row_count(schema2, table2)

        print(f"\n{'='*80}")
        print(f"  LIENS ENTRE [{schema1}].[{table1}] ({n1:,} lignes)")
        print(f"          ET  [{schema2}].[{table2}] ({n2:,} lignes)")
        print(f"{'='*80}")

        links = find_links_between(schema1, table1, schema2, table2)

        if not links:
            print("\n  Aucun lien trouvé entre ces deux tables.\n")
        else:
            print(f"\n  {len(links)} lien(s) trouvé(s) :\n")
            for l in links:
                print(f"     └─ {l}")
            print()

    else:
        # ── Mode toutes les tables ───────────────────────────────
        print(f"\n{'='*80}")
        print(f"  TABLES LIÉES À [{schema1}].[{table1}]")
        print(f"  ({n1:,} lignes)")
        print(f"{'='*80}")

        linked = find_linked_tables(schema1, table1)

        if not linked:
            print("\n  Aucune table liée trouvée.\n")
            return

        # Trier : FK d'abord, puis nom exact, puis suffixe
        priority = {"FK": 0, "NOM": 1, "SUFFIXE": 2}
        sorted_tables = sorted(linked.items(), key=lambda x: (priority.get(x[1]["type"], 9), x[0]))

        print(f"\n  {len(sorted_tables)} table(s) liée(s) trouvée(s) :\n")
        print(f"  {'─'*76}")

        for tbl, info in sorted_tables:
            n = get_row_count(*tbl.split(".", 1))
            print(f"\n  📋 {tbl}  ({n:,} lignes)")
            for j in info["jointures"]:
                print(f"     └─ {j}")

        print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
