#!/usr/bin/env python3
"""
Audit RGPD : recherche les données personnelles résiduelles dans la base
SQL Server : adresses e-mail ou numéros de téléphone.

Usage:
  python3 audit-emails.py email           → recherche les e-mails
  python3 audit-emails.py tel             → recherche les téléphones
  python3 audit-emails.py email CEGID_PMI → sur une base spécifique
  python3 audit-emails.py tel CEGID_PMI   → sur une base spécifique
"""

import sys
import subprocess
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Bases système à ignorer
SYSTEM_DATABASES = {"master", "tempdb", "model", "msdb"}

# ── Configuration par mode ────────────────────────────────────────────────────
MODES = {
    "email": {
        "label": "E-MAILS",
        "label_sing": "e-mail",
        # Mots-clés dans les noms de colonnes
        "column_keywords": ["%email%", "%mail%", "%courriel%", "%smtp%", "%pop%"],
        # Pattern SQL pour détecter les données (LIKE)
        "data_sql_where": "CAST([{column}] AS NVARCHAR(MAX)) LIKE '%@%.%'",
        # Exclusion pour la recherche par contenu (ne pas re-scanner les colonnes nommées)
        "exclude_column_keywords": ["%email%", "%mail%", "%courriel%", "%smtp%", "%pop%"],
    },
    "tel": {
        "label": "TÉLÉPHONES",
        "label_sing": "téléphone",
        # Mots-clés dans les noms de colonnes
        "column_keywords": ["%tel%", "%phone%", "%fax%", "%gsm%", "%mobile%", "%portable%"],
        # Pattern SQL : 10 chiffres consécutifs, ou séparés par : ou espace (XX:XX:XX:XX:XX ou XX XX XX XX XX)
        "data_sql_where": (
            "CAST([{column}] AS NVARCHAR(MAX)) LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'"
            " OR CAST([{column}] AS NVARCHAR(MAX)) LIKE '[0-9][0-9]:[0-9][0-9]:[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"
            " OR CAST([{column}] AS NVARCHAR(MAX)) LIKE '[0-9][0-9] [0-9][0-9] [0-9][0-9] [0-9][0-9] [0-9][0-9]'"
        ),
        # Exclusion pour la recherche par contenu
        "exclude_column_keywords": ["%tel%", "%phone%", "%fax%", "%gsm%", "%mobile%", "%portable%"],
    },
}
# ──────────────────────────────────────────────────────────────────────────────


def run_sql(query: str, db: str) -> list[dict]:
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
        # Nettoyer le padding nchar sur toutes les valeurs string
        for row in rows:
            for k, v in row.items():
                if isinstance(v, str):
                    row[k] = v.strip()
        return rows
    except json.JSONDecodeError:
        print(f"Erreur JSON:\n{output}", file=sys.stderr)
        return []


def run_update(db: str, schema: str, table: str, column: str) -> bool:
    cmd = [
        "docker", "exec", "-i", CONTAINER,
        SQLCMD,
        "-S", DB_HOST, "-U", DB_USER, "-P", DB_PASS,
        "-d", db, "-C",
        "-Q", f"UPDATE [{schema}].[{table}] SET [{column}] = NULL;",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def list_databases() -> list[str]:
    rows = run_sql(
        "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE'",
        "master",
    )
    return [r["name"] for r in rows if r.get("name") not in SYSTEM_DATABASES]


def find_named_columns(db: str, mode: dict) -> list[dict]:
    """Retourne les colonnes dont le nom évoque le type de données recherché."""
    conditions = " OR ".join(f"LOWER(col.name) LIKE '{kw}'" for kw in mode["column_keywords"])
    return run_sql(
        f"""
        SELECT s.name  AS TABLE_SCHEMA,
               t.name  AS TABLE_NAME,
               col.name AS COLUMN_NAME,
               ty.name AS DATA_TYPE
        FROM sys.columns col
        JOIN sys.tables  t  ON col.object_id = t.object_id
        JOIN sys.schemas s  ON t.schema_id   = s.schema_id
        JOIN sys.types   ty ON col.user_type_id = ty.user_type_id
        WHERE ({conditions})
          AND s.name NOT IN ('OData', 'Cache', 'Common')
        ORDER BY t.name, col.name
        """,
        db,
    )


def find_text_columns(db: str, mode: dict) -> list[dict]:
    """Retourne les colonnes texte candidates pour la recherche par contenu."""
    exclude = " AND ".join(
        f"LOWER(col.name) NOT LIKE '{kw}'" for kw in mode["exclude_column_keywords"]
    )
    return run_sql(
        f"""
        SELECT s.name  AS TABLE_SCHEMA,
               t.name  AS TABLE_NAME,
               col.name AS COLUMN_NAME,
               ty.name AS DATA_TYPE
        FROM sys.columns col
        JOIN sys.tables  t  ON col.object_id = t.object_id
        JOIN sys.schemas s  ON t.schema_id   = s.schema_id
        JOIN sys.types   ty ON col.user_type_id = ty.user_type_id
        WHERE ty.name IN ('varchar', 'nvarchar', 'char', 'nchar')
          AND col.max_length BETWEEN 10 AND 510
          AND s.name NOT IN ('OData', 'Cache', 'Common')
          AND {exclude}
        ORDER BY t.name, col.name
        """,
        db,
    )


def count_matching_values(db: str, schema: str, table: str, column: str, mode: dict) -> int:
    """Compte les lignes qui correspondent au pattern du mode."""
    schema, table, column = schema.strip(), table.strip(), column.strip()
    where = mode["data_sql_where"].format(column=column)
    rows = run_sql(
        f"""
        SELECT COUNT(*) AS [N]
        FROM [{schema}].[{table}]
        WHERE {where}
        """,
        db,
    )
    if rows:
        return rows[0].get("N", 0) or 0
    return 0


def count_non_null(db: str, schema: str, table: str, column: str) -> int:
    schema, table, column = schema.strip(), table.strip(), column.strip()
    rows = run_sql(
        f"SELECT COUNT(*) AS [N] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL AND LTRIM(RTRIM(CAST([{column}] AS NVARCHAR(MAX)))) <> ''",
        db,
    )
    if rows:
        return rows[0].get("N", 0) or 0
    return 0


def audit_database(db: str, mode: dict) -> list[tuple]:
    """Retourne la liste des (schema, table, colonne, n) avec des données non-NULL."""
    label = mode["label_sing"]
    print(f"\n  Base : {db}")
    print(f"  {'─'*60}")

    problemes = []

    # -- Colonnes nommées d'après le type recherché ----------------------------
    named_cols = find_named_columns(db, mode)
    if named_cols:
        print(f"  {len(named_cols)} colonne(s) dont le nom évoque un {label} :")
        for c in named_cols:
            schema = c["TABLE_SCHEMA"].strip()
            table  = c["TABLE_NAME"].strip()
            column = c["COLUMN_NAME"].strip()
            dtype  = c["DATA_TYPE"].strip()
            try:
                n = count_non_null(db, schema, table, column)
            except Exception:
                print(f"    [{schema}].[{table}].[{column}] ({dtype}) → erreur (ignorée)")
                continue
            flag = "  ⚠️  NON VIDE" if n > 0 else ""
            print(f"    [{schema}].[{table}].[{column}] ({dtype}) → {n} ligne(s){flag}")
            if n > 0:
                problemes.append((schema, table, column, n))
    else:
        print(f"  Aucune colonne nommée {label}.")

    # -- Colonnes texte contenant des données correspondantes ------------------
    text_cols = find_text_columns(db, mode)
    total = len(text_cols)
    print(f"  Recherche de {label}s dans {total} colonnes texte (6 threads)... ")
    found_data = []
    done = 0

    def _check_column(c):
        schema = c.get("TABLE_SCHEMA", "dbo").strip()
        table  = c.get("TABLE_NAME", "").strip()
        column = c.get("COLUMN_NAME", "").strip()
        dtype  = c.get("DATA_TYPE", "").strip()
        if not table or not column:
            return None
        try:
            n = count_matching_values(db, schema, table, column, mode)
        except Exception:
            return None
        if n > 0:
            return (schema, table, column, dtype, n)
        return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_check_column, c): c for c in text_cols}
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                schema, table, column, dtype, n = result
                found_data.append(result)
                print(f"    [{done}/{total}] [{schema}].[{table}].[{column}] → {n} {label}(s) ⚠️")
            elif done % 100 == 0:
                print(f"    [{done}/{total}] ...", flush=True)
    print(f"  → {len(found_data)} colonne(s) avec des {label}s.")

    if found_data:
        print(f"  Colonnes sans nom '{label}' mais contenant des données :")
        for schema, table, column, dtype, n in found_data:
            print(f"    [{schema}].[{table}].[{column}] ({dtype}) → {n} ligne(s)  ⚠️")
            if (schema, table, column, n) not in problemes:
                problemes.append((schema, table, column, n))

    return problemes


def main() -> None:
    # Parsing des arguments
    args = sys.argv[1:]
    if not args or args[0] not in MODES:
        print("Usage: ./audit-emails.py <email|tel> [NOM_BASE]")
        print("  email  → recherche les adresses e-mail")
        print("  tel    → recherche les numéros de téléphone")
        sys.exit(1)

    mode = MODES[args[0]]
    databases = [args[1]] if len(args) >= 2 else [DB_NAME]

    print(f"\n{'='*70}")
    print(f"  AUDIT RGPD — {mode['label']}")
    print(f"  Bases analysées : {', '.join(databases)}")
    print(f"{'='*70}")

    tous_problemes: dict[str, list[tuple]] = {}

    for db in databases:
        problemes = audit_database(db, mode)
        if problemes:
            tous_problemes[db] = problemes

    # ── Synthèse ──────────────────────────────────────────────────────────────
    label = mode["label_sing"]
    print(f"\n{'='*70}")
    print("SYNTHÈSE")
    print("-" * 70)

    if not tous_problemes:
        print(f"  ✅  Aucun {label} résiduel détecté.\n")
        return

    total = sum(len(v) for v in tous_problemes.values())
    print(f"  ⚠️  {total} colonne(s) avec des {label}s dans {len(tous_problemes)} base(s) :\n")
    for db, problemes in tous_problemes.items():
        for schema, table, column, n in problemes:
            print(f"    {db} → [{schema}].[{table}].[{column}] → {n} ligne(s)")

    # ── Nettoyage ─────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("NETTOYAGE AUTOMATIQUE")
    print("-" * 70)
    reponse = input(f"  Mettre à NULL toutes les colonnes listées ci-dessus ? [oui/NON] : ").strip().lower()

    if reponse != "oui":
        print("  Annulé — aucune modification effectuée.\n")
        return

    for db, problemes in tous_problemes.items():
        for schema, table, column, _ in problemes:
            print(f"  UPDATE [{db}].[{schema}].[{table}].[{column}] ... ", end="", flush=True)
            ok = run_update(db, schema, table, column)
            print("OK ✅" if ok else "ERREUR ❌")

    print("\n  Nettoyage terminé. Relancez le script pour vérifier.\n")


if __name__ == "__main__":
    main()
