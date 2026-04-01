#!/usr/bin/env python3
"""
Anonymisation de la base SQL Server.
Chaque règle définit une table, un champ et la transformation à appliquer.

Usage: .venv/bin/python anonymize-db.py [--dry-run]

  --dry-run  Affiche ce qui serait modifié sans exécuter les UPDATE.
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

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
ANON_EMAIL  = "toto@tutu.fr"

# ── Règles d'anonymisation ────────────────────────────────────────────────────
# Chaque entrée : (schema, table, colonne, type)
# type :
#   "email"  → remplace si contient une adresse mail
#   (d'autres types pourront être ajoutés ici)
RULES: list[tuple[str, str, str, str]] = [
    ("dbo"   , "NONCONFO", "NCCTMAIL",   "email"),
    ("dbo"   , "PARAM"   , "PACTEXT140", "email"),
    ("dbo"   , "FOURNIS" , "CLCTEMAIL",  "email"),
    ("Common", "RtfDocumentLineDescription"  , "Comment",  "email"),
    ("Common", "RtfComment"  , "Comment",  "email"),
]
# ──────────────────────────────────────────────────────────────────────────────

def get_connection():
    return pymssql.connect(
        server=DB_HOST, user=DB_USER, password=DB_PASS,
        database=DB_NAME, port=1433, tds_version="7.4",
    )


def anonymize_email(conn, schema: str, table: str, col: str, dry_run: bool) -> int:
    """
    Remplace par ANON_EMAIL les champs contenant une adresse email.
    Laisse intacts les champs NULL, vides ou sans email.
    Retourne le nombre de lignes modifiées.
    """
    cur = conn.cursor(as_dict=True)
    cur.execute(
        f"SELECT [{col}] FROM [{schema}].[{table}] "
        f"WHERE [{col}] IS NOT NULL AND [{col}] LIKE '%@%'"
    )
    rows = cur.fetchall()

    count = 0
    for row in rows:
        val = str(row[col])
        if not EMAIL_REGEX.search(val):
            continue
        count += 1
        if not dry_run:
            upd = conn.cursor()
            upd.execute(
                f"UPDATE [{schema}].[{table}] SET [{col}] = %s WHERE [{col}] = %s",
                (ANON_EMAIL, val),
            )

    if not dry_run and count > 0:
        conn.commit()

    return count


HANDLERS = {
    "email": anonymize_email,
}


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("Mode DRY-RUN — aucune modification ne sera effectuée.\n")

    conn = get_connection()

    # Collecte des résultats
    results: list[tuple[str, str, str, str, int | str]] = []

    for schema, table, col, kind in RULES:
        handler = HANDLERS.get(kind)
        if not handler:
            results.append((schema, table, col, kind, "type inconnu"))
            continue
        print(f"Traitement [{schema}.{table}].{col} ...", end="\r", flush=True)
        n = handler(conn, schema, table, col, dry_run)
        results.append((schema, table, col, kind, n))

    conn.close()
    print(" " * 60, end="\r")  # efface la ligne de progression

    # Affichage tableau
    col_headers = ["Table", "Colonne", "Type", "Lignes modifiées"]
    rows_display = [
        (f"{s}.{t}", c, k, str(n) if isinstance(n, int) else n)
        for s, t, c, k, n in results
    ]

    widths = [len(h) for h in col_headers]
    for row in rows_display:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "| " + " | ".join(f"{cell:<{widths[i]}}" for i, cell in enumerate(cells)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"

    print(sep)
    print(fmt_row(col_headers))
    print(sep)
    for row in rows_display:
        print(fmt_row(row))
    print(sep)

    total = sum(n for *_, n in results if isinstance(n, int))
    status = "à modifier" if dry_run else "modifiée(s)"
    print(f"\nTotal : {total} ligne(s) {status}.")


if __name__ == "__main__":
    main()
