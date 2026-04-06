#!/usr/bin/env python3
"""
Détection automatique des colonnes susceptibles de contenir des noms de
personnes ou de sociétés dans toute la base SQL Server.

L'analyse combine deux critères :
  1. Le nom de la colonne contient un mot-clé caractéristique (NOM, PRENOM,
     RAISON, SOCIETE, CONTACT, etc.)
  2. Un échantillon de valeurs réelles est inspecté pour confirmer et
     déterminer le type ("personne" ou "entreprise").

À la fin, le script affiche un dictionnaire prêt à être copié dans
CHAMPS_A_ANONYMISER du fichier anonymize-names.py.

Usage:
  ./discover-names-fields.py                      → analyse toute la base
  ./discover-names-fields.py --verbose             → affiche aussi les échantillons
  ./discover-names-fields.py --type ville          → filtre sur le type 'ville'
  ./discover-names-fields.py --type personne       → filtre sur le type 'personne'

Types reconnus : prenom, personne, entreprise, ville, telephone, ambigu
"""

import sys
import re
from pathlib import Path
from collections import defaultdict

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

_cfg        = _load_config()
DB_HOST     = _cfg.get("DB_HOST", "localhost")
DB_USER     = _cfg.get("DB_USER", "sa")
DB_PASSWORD = _cfg.get("DB_PASSWORD", "")
DB_NAME     = _cfg.get("DB_NAME", "")
# ──────────────────────────────────────────────────────────────────────────────

VERBOSE = "--verbose" in sys.argv
DEBUG   = "--debug"   in sys.argv

# Filtre optionnel sur le type de champ (--type <type>)
_type_idx = sys.argv.index("--type") if "--type" in sys.argv else -1
TYPE_FILTER: str | None = sys.argv[_type_idx + 1].lower() if _type_idx != -1 and _type_idx + 1 < len(sys.argv) else None

# ── Mots-clés dans les noms de colonnes ───────────────────────────────────────
# Chaque entrée : (regex_sur_nom_colonne, type_par_defaut)
# Le type sera affiné par analyse des valeurs.
KEYWORDS_ENTREPRISE = re.compile(
    r'(SOCIE?T|RAISON|ENSEIGNE|ETABLIS|ENTREPRI|ORGANIS|CLIENT|FOURNI|'
    r'COMPAGN|CABINET|ASSOCIA|GROUPE)',
    re.IGNORECASE,
)
KEYWORDS_PRENOM     = re.compile(r'(PRENOM|FIRSTNAME)', re.IGNORECASE)
KEYWORDS_VILLE      = re.compile(r'(VILLE|LOCALITE|LOCALITÉ|CITY)', re.IGNORECASE)
KEYWORDS_TELEPHONE  = re.compile(
    r'(TEL|MOBILE|GSM|FAX|PORTABLE|CELLULAIRE)',
    re.IGNORECASE,
)
KEYWORDS_PERSONNE = re.compile(
    r'(LASTNAME|SALARI|EMPLOYE|CONTACT|INTERLO)',
    re.IGNORECASE,
)
# Colonnes dont le nom contient "NOM" (y compris en suffixe : UTCTNOM) → ambigu
KEYWORDS_NOM_SEUL = re.compile(r'NOM', re.IGNORECASE)

# ── Indicateurs dans les valeurs ─────────────────────────────────────────────
# Présence d'une forme juridique → entreprise
FORMES_JURIDIQUES = re.compile(
    r'\b(SARL|SAS|SASU|EURL|SCI|SNC|SA|GIE|SCOP|SCA|SCS|EI|SELARL|'
    r'S\.A\.R\.L|S\.A\.S|S\.A|E\.U\.R\.L|ASSOCIATION|SYNDICAT|MAIRIE|'
    r'COMMUNE|CONSEIL|DEPARTEMENT|PREFECTURE|COMMUNAUTE|METROPOLE|'
    r'UNIVERSITE|LYCEE|COLLEGE|ECOLE|HOPITAL|CHU|CHR|CLINIQUE)\b',
    re.IGNORECASE,
)
# Valeur ressemble à "PRENOM NOM" ou "NOM PRENOM" (2 mots, premier en maj) ?
RE_PERSONNE = re.compile(r'^[A-ZÀ-Ÿ][a-zà-ÿ\-]+ [A-ZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖÙÚÛÜÝ]{2,}$')


def get_connection():
    return pymssql.connect(
        server=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, port=1433, tds_version="7.4",
    )


def get_text_columns(conn) -> list[tuple[str, str, str]]:
    """Retourne (schema, table, colonne) pour toutes les colonnes textuelles."""
    cur = conn.cursor()
    cur.execute("""
        SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        INNER JOIN INFORMATION_SCHEMA.TABLES t
            ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
           AND t.TABLE_NAME   = c.TABLE_NAME
           AND t.TABLE_TYPE   = 'BASE TABLE'
        WHERE c.DATA_TYPE IN ('char','nchar','varchar','nvarchar','text','ntext')
          AND c.CHARACTER_MAXIMUM_LENGTH > 2
        ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
    """)
    return cur.fetchall()


def candidate_type(col_name: str) -> str | None:
    """Retourne le type probable d'après le nom de colonne, ou None si non pertinent."""
    if KEYWORDS_PRENOM.search(col_name):
        return "prenom"
    if KEYWORDS_VILLE.search(col_name):
        return "ville"
    if KEYWORDS_TELEPHONE.search(col_name):
        return "telephone"
    if KEYWORDS_PERSONNE.search(col_name):
        return "personne"
    if KEYWORDS_ENTREPRISE.search(col_name):
        return "entreprise"
    if KEYWORDS_NOM_SEUL.search(col_name):
        return "ambigu"   # affiné plus tard par les valeurs
    return None


def sample_values(conn, schema: str, table: str, col: str, n: int = 10) -> list[str]:
    """Retourne jusqu'à n valeurs non nulles et non vides de la colonne."""
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT TOP {n} RTRIM(CAST([{col}] AS nvarchar(500)))
            FROM [{schema}].[{table}]
            WHERE [{col}] IS NOT NULL
              AND RTRIM(CAST([{col}] AS nvarchar(500))) <> ''
        """)
        return [row[0] for row in cur.fetchall() if row[0]]
    except Exception:
        return []


def refine_type(col_name: str, values: list[str], hint: str) -> str:
    """Affine le type entre 'personne' et 'entreprise' grâce aux valeurs."""
    score_entreprise = 0
    score_personne   = 0

    for v in values:
        if FORMES_JURIDIQUES.search(v):
            score_entreprise += 2
        if RE_PERSONNE.match(v):
            score_personne += 1

    if score_entreprise > score_personne:
        return "entreprise"
    if score_personne > score_entreprise:
        return "personne"
    # En cas d'égalité, on garde le hint ou on met entreprise par défaut
    return hint if hint != "ambigu" else "entreprise"


def table_has_rows(conn, schema: str, table: str) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT TOP 1 1 FROM [{schema}].[{table}]")
        return cur.fetchone() is not None
    except Exception:
        return False


def fetch_col_preview(conn, schema: str, table: str, col: str, n: int = 10) -> list[str]:
    """Retourne jusqu'à n valeurs distinctes et non vides pour une colonne."""
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT DISTINCT TOP {n} RTRIM(CAST([{col}] AS nvarchar(500)))
            FROM [{schema}].[{table}]
            WHERE [{col}] IS NOT NULL
              AND RTRIM(CAST([{col}] AS nvarchar(500))) <> ''
        """)
        return [row[0] for row in cur.fetchall() if row[0]]
    except Exception:
        return []


def print_col_table(table_full: str, col: str, typ: str, values: list[str]) -> None:
    """Affiche un tableau ASCII pour une seule colonne."""
    header    = f"{col} [{typ}]"
    width     = max(len(header), max((len(v) for v in values), default=4), 4)
    sep       = f"+-{'-' * width}-+"
    dict_line = f'    ("{table_full}", "{col}", "{typ}"),'
    print(f"\n{dict_line}")
    print(sep)
    print(f"| {header:<{width}} |")
    print(sep)
    for v in values:
        print(f"| {v:<{width}} |")
    print(sep)


def main():
    conn = get_connection()

    print("Récupération des colonnes textuelles…")
    all_cols = get_text_columns(conn)
    print(f"  {len(all_cols)} colonnes textuelles trouvées\n")

    # ── Mode direct pour --type telephone ────────────────────────────────────
    if TYPE_FILTER == "telephone":
        tel_cols = [
            (schema, table, col)
            for schema, table, col in all_cols
            if candidate_type(col) == "telephone"
        ]
        print(f"  {len(tel_cols)} colonne(s) téléphone détectée(s)\n")
        print("=" * 70)
        print("  COLONNES TÉLÉPHONE")
        print("=" * 70)
        for schema, table, col in tel_cols:
            table_full = f"{schema}.{table}"
            values = fetch_col_preview(conn, schema, table, col, n=10)
            print_col_table(table_full, col, "telephone", values)
        conn.close()
        return

    results: dict[str, list[tuple[str, str]]] = defaultdict(list)
    # Mémoriser (schema, table) pour la prévisualisation
    table_coords: dict[str, tuple[str, str]] = {}
    skipped_empty = 0

    prev_table = None
    for schema, table, col in all_cols:
        table_full = f"{schema}.{table}"

        # Filtrage par nom de colonne
        hint = candidate_type(col)
        if hint is None:
            continue
        if DEBUG:
            print(f"[DEBUG] candidat : {table_full}.{col}  hint={hint}")

        # Ignorer les tables vides (vérification une seule fois par table)
        if table_full != prev_table:
            if not table_has_rows(conn, schema, table):
                if DEBUG:
                    print(f"[DEBUG]   → table vide, ignorée")
                skipped_empty += 1
                prev_table = table_full
                continue
            prev_table = table_full

        # Échantillonnage
        values = sample_values(conn, schema, table, col)
        if not values:
            if DEBUG:
                print(f"[DEBUG]   → aucune valeur, ignoré")
            continue

        # Ignorer les colonnes dont les valeurs ressemblent à des codes courts
        # (sauf pour le type telephone où des formats courts sont normaux)
        looks_like_codes = hint != "telephone" and all(
            len(v) < 6 and ' ' not in v
            for v in values
        )
        if looks_like_codes:
            if DEBUG:
                print(f"[DEBUG]   → ressemble à des codes courts, ignoré: {values[:3]}")
            continue

        final_type = refine_type(col, values, hint)
        if DEBUG:
            print(f"[DEBUG]   → final_type={final_type}  valeurs={values[:3]}")

        if VERBOSE:
            print(f"  {table_full}.{col}  →  {final_type}")
            for v in values[:3]:
                print(f"      {v!r}")

        if TYPE_FILTER and final_type != TYPE_FILTER:
            continue

        results[table_full].append((col, final_type))
        table_coords[table_full] = (schema, table)

    # ── Tableaux de vérification ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PRÉVISUALISATION DES CHAMPS DÉTECTÉS")
    print("=" * 70)

    for table_full in sorted(results):
        schema, table = table_coords[table_full]
        for col, typ in results[table_full]:
            values = fetch_col_preview(conn, schema, table, col)
            print_col_table(table_full, col, typ, values)

    conn.close()

    # ── Affichage de la liste ─────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  LISTE CHAMPS_A_ANONYMISER")
    print("=" * 70)
    print()
    print("CHAMPS_A_ANONYMISER = [")

    if not results:
        print("    # Aucun champ détecté")
    else:
        all_entries = [
            (table_full, col, typ)
            for table_full in sorted(results)
            for col, typ in results[table_full]
        ]
        for table_full, col, typ in all_entries:
            print(f'    ("{table_full}", "{col}", "{typ}"),')

    print("]")
    print()
    print(f"  {sum(len(v) for v in results.values())} champ(s) détecté(s) "
          f"dans {len(results)} table(s)")
    if skipped_empty:
        print(f"  ({skipped_empty} table(s) vide(s) ignorée(s))")
    print()


if __name__ == "__main__":
    main()
