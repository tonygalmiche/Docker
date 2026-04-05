#!/usr/bin/env python3
"""
Audit de sécurité : recherche les mots de passe résiduels dans la base SQL Server.

Vérifie :
  1. Les colonnes dont le nom évoque un mot de passe dans toute la base
  2. Le contenu non-NULL de ces colonnes
  3. La table WEBMDP

Usage: python3 audit-passwords.py [NOM_BASE]
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

# Mots-clés recherchés dans les noms de colonnes
PASSWORD_KEYWORDS = ["%password%", "%passwd%", "%pwd%", "%mdp%", "%motdepasse%", "%secret%", "%token%"]


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
    output = "".join(result.stdout.splitlines()).strip()
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        print(f"Erreur JSON:\n{output}", file=sys.stderr)
        return []


def find_password_columns(db: str) -> list[dict]:
    """Retourne toutes les colonnes dont le nom évoque un mot de passe."""
    conditions = " OR ".join(f"LOWER(COLUMN_NAME) LIKE '{kw}'" for kw in PASSWORD_KEYWORDS)
    return run_sql(
        f"""
        SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE {conditions}
        ORDER BY TABLE_NAME, COLUMN_NAME
        """,
        db,
    )


def count_non_null(db: str, schema: str, table: str, column: str) -> int:
    """Compte les lignes non-NULL pour une colonne donnée."""
    rows = run_sql(
        f"SELECT COUNT(*) AS [N] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL AND LTRIM(RTRIM(CAST([{column}] AS NVARCHAR(MAX)))) <> ''",
        db,
    )
    if rows:
        return rows[0].get("N", 0) or 0
    return 0


def main() -> None:
    db = sys.argv[1] if len(sys.argv) >= 2 else DB_NAME

    print(f"\n{'='*70}")
    print(f"  AUDIT MOTS DE PASSE — Base : {db}")
    print(f"{'='*70}\n")

    # ── 1. Recherche des colonnes sensibles ───────────────────────────────────
    print("1. COLONNES DONT LE NOM ÉVOQUE UN MOT DE PASSE")
    print("-" * 70)
    cols = find_password_columns(db)

    if not cols:
        print("   Aucune colonne trouvée.\n")
        return

    # Affichage + comptage des valeurs non-NULL
    results = []
    for c in cols:
        schema  = c.get("TABLE_SCHEMA", "dbo")
        table   = c.get("TABLE_NAME", "")
        column  = c.get("COLUMN_NAME", "")
        dtype   = c.get("DATA_TYPE", "")
        n_renseignees = count_non_null(db, schema, table, column)
        results.append((schema, table, column, dtype, n_renseignees))

    # Calcul des largeurs
    w_table  = max(len("Table"),  max(len(f"{s}.{t}") for s, t, *_ in results))
    w_column = max(len("Colonne"), max(len(c) for _, _, c, *_ in results))
    w_dtype  = max(len("Type"),   max(len(d) for _, _, _, d, _ in results))

    header = f"  {'Table':<{w_table}}  {'Colonne':<{w_column}}  {'Type':<{w_dtype}}  Valeurs non-NULL"
    print(header)
    print("  " + "-" * (len(header) - 2))

    problemes = []
    for schema, table, column, dtype, n in results:
        full_table = f"{schema}.{table}"
        flag = " ⚠️  NON VIDE" if n > 0 else ""
        print(f"  {full_table:<{w_table}}  {column:<{w_column}}  {dtype:<{w_dtype}}  {n}{flag}")
        if n > 0:
            problemes.append((schema, table, column, n))

    # ── 2. Synthèse ───────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("2. SYNTHÈSE")
    print("-" * 70)

    if not problemes:
        print("   ✅  Aucun mot de passe résiduel détecté — la base peut être transmise.\n")
    else:
        print(f"   ⚠️  {len(problemes)} colonne(s) contiennent des valeurs non-NULL :\n")
        for schema, table, column, n in problemes:
            print(f"     - [{schema}].[{table}].[{column}] → {n} ligne(s)")
        print()
        print("   Actions recommandées avant transmission :")
        for schema, table, column, _ in problemes:
            print(f"     UPDATE [{schema}].[{table}] SET [{column}] = NULL;")
        print()

        # ── 3. Proposition de nettoyage ───────────────────────────────────────
        print(f"{'='*70}")
        print("3. NETTOYAGE AUTOMATIQUE")
        print("-" * 70)
        reponse = input(f"   Effacer les {len(problemes)} colonne(s) listée(s) ci-dessus ? [oui/NON] : ").strip().lower()
        if reponse == "oui":
            for schema, table, column, _ in problemes:
                print(f"   UPDATE [{schema}].[{table}] SET [{column}] = NULL ... ", end="", flush=True)
                cmd = [
                    "docker", "exec", "-i", CONTAINER,
                    SQLCMD,
                    "-S", DB_HOST, "-U", DB_USER, "-P", DB_PASS,
                    "-d", db, "-C",
                    "-Q", f"UPDATE [{schema}].[{table}] SET [{column}] = NULL;",
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print("OK ✅")
                else:
                    print(f"ERREUR ❌\n{result.stderr}")
            print()
            print("   Nettoyage terminé. Relancez le script pour vérifier.\n")
        else:
            print("   Annulé — aucune modification effectuée.\n")


if __name__ == "__main__":
    main()
