#!/usr/bin/env python3
"""
Anonymisation des noms de personnes et d'entreprises dans la base SQL Server.

Pour chaque champ configuré dans CHAMPS_A_ANONYMISER, remplace les valeurs
existantes par des noms aléatoires cohérents (même valeur originale → même
valeur de remplacement, pour préserver la cohérence entre tables).

Usage:
  ./anonymize-names.py          → affiche les remplacements prévus
  ./anonymize-names.py --apply  → applique les modifications en base
"""

import sys
import subprocess
import json
import re
import random
import concurrent.futures
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

# ── Tables et champs à anonymiser ─────────────────────────────────────────────
# Format: [ ("schema.TABLE", "COLONNE", "type"), ... ]
# type = "entreprise" | "personne" | "prenom" | "ville"
CHAMPS_A_ANONYMISER = [
    ("dbo.CLIENT",    "CLCTNOM",    "entreprise"),
    ("dbo.CLIENT",    "CLCTNOMLIV", "entreprise"),
    ("dbo.CLIENT",    "CLCTNOMBAN", "entreprise"),
    ("dbo.CONTACT",   "CTCTNOM",    "entreprise"),
    ("dbo.CONTACT",   "CTCTPRENOM", "prenom"),
    ("dbo.COOBAN",    "CBCTNOMBAN", "entreprise"),
    ("dbo.COOLCR",    "CRCTNOMBAN", "entreprise"),
    ("dbo.ECHEMULT",  "EMCTNOM",    "entreprise"),
    ("dbo.ECOMCLI",   "ECCTNOM",    "entreprise"),
    #("dbo.ECOMCLI",   "ECCTNOMLIV", "entreprise"),
    ("dbo.ECOMFOU",   "ECCTNOM",    "entreprise"),
    #("dbo.ECOMFOU",   "ECCTNOMLIV", "entreprise"),
    ("dbo.ECOMOUV",   "ECCTNOM",    "entreprise"),
    ("dbo.ECOMOUV",   "ECCTNOMLIV", "entreprise"),
    ("dbo.EDDEFOU",   "ECCTNOM",    "entreprise"),
    ("dbo.EDDEFOU",   "ECCTNOMLIV", "entreprise"),
    ("dbo.EEXPCLI",   "ECCTNOM",    "entreprise"),
    #("dbo.EEXPCLI",   "ECCTNOMLIV", "entreprise"),
    ("dbo.EOFFCLI",   "ECCTNOM",    "entreprise"),
    ("dbo.EOFFCLI",   "ECCTNOMLIV", "entreprise"),
    ("dbo.ERECFOU",   "ECCTNOM",    "entreprise"),
    ("dbo.ERECFOU",   "ECCTNOMLIV", "entreprise"),
    ("dbo.FOURNIS",   "CLCTNOM",    "entreprise"),
    ("dbo.FOURNIS",   "CLCTNOMLIV", "entreprise"),
    ("dbo.FOURNIS",   "CLCTNOMBAN", "entreprise"),
    ("dbo.MVTSTO",    "MVCTNOMUTI", "personne"),
    ("dbo.NONCONFO",  "NCCTNOM",    "entreprise"),
    ("dbo.NONCONFO",  "NCCTNOMSA",  "entreprise"),
    ("dbo.NONCONFO",  "NCCTNOMRES", "personne"),
    ("dbo.PROSPOLD",  "CLCTNOM",    "entreprise"),
    ("dbo.PROSPOLD",  "CLCTNOMLIV", "entreprise"),
    ("dbo.REPRESEN",  "RECTNOM",    "entreprise"),
    ("dbo.SALARIES",  "MACTNOM",    "personne"),
    ("dbo.UTILISAT",  "UTCTNOM",    "personne"),


    ("dbo.CLIENT", "CLCTVILLE", "ville"),
    ("dbo.ECOMCLI", "ECCTVILLE", "ville"),
    ("dbo.ECOMFOU", "ECCTVILLE", "ville"),
    ("dbo.EDDEFOU", "ECCTVILLE", "ville"),
    ("dbo.EEXPCLI", "ECCTVILLE", "ville"),
    ("dbo.EOFFCLI", "ECCTVILLE", "ville"),
    ("dbo.ERECFOU", "ECCTVILLE", "ville"),
    ("dbo.FOURNIS", "CLCTVILLE", "ville"),
    ("dbo.NONCONFO", "NCCTVILLE", "ville"),
    ("dbo.SALARIES", "MACTVILLE", "ville"),
    ("dbo.TRANSPOR", "TOCTNOMLOC", "ville"),



]



# ── Types juridiques d'entreprise ─────────────────────────────────────────────
TYPES_ENTREPRISE = [
    "SARL", "SAS", "SA", "EURL", "SNC", "SCI", "SASU",
    "EI", "SELARL", "GIE", "SCOP", "SCA", "SCS",
]

# ── Prénoms (50) ──────────────────────────────────────────────────────────────
PRENOMS = [
    "Alice", "Baptiste", "Camille", "David", "Emma",
    "François", "Gabrielle", "Hugo", "Inès", "Julien",
    "Karine", "Lucas", "Marie", "Nicolas", "Océane",
    "Pierre", "Quentin", "Rose", "Sébastien", "Théo",
    "Ugo", "Valentine", "William", "Xavier", "Yasmine",
    "Zacharie", "Adrien", "Béatrice", "Charles", "Diane",
    "Étienne", "Florence", "Guillaume", "Hélène", "Isabelle",
    "Jean", "Laure", "Marc", "Nathalie", "Olivier",
    "Patricia", "Raphaël", "Sophie", "Thomas", "Ursula",
    "Vincent", "Wendy", "Alexis", "Brigitte", "Cédric",
]

# ── Noms de famille (50) ──────────────────────────────────────────────────────
NOMS_FAMILLE = [
    "MARTIN", "BERNARD", "DUBOIS", "THOMAS", "ROBERT",
    "RICHARD", "PETIT", "DURAND", "LEROY", "MOREAU",
    "SIMON", "LAURENT", "LEFEBVRE", "MICHEL", "GARCIA",
    "DAVID", "BERTRAND", "ROUX", "VINCENT", "FOURNIER",
    "MOREL", "GIRARD", "ANDRÉ", "LEFEVRE", "MERCIER",
    "DUPONT", "LAMBERT", "BONNET", "FRANÇOIS", "MARTINEZ",
    "LEGRAND", "GARNIER", "FAURE", "ROUSSEAU", "BLANC",
    "GUÉRIN", "MULLER", "HENRY", "ROUSSEL", "NICOLAS",
    "PERRIN", "MORIN", "MATHIEU", "CLÉMENT", "GAUTHIER",
    "FONTAINE", "CHABERT", "DENIS", "CHEVALIER", "MASSON",
]

# ── Villes (50) ───────────────────────────────────────────────────────────────
VILLES = [
    "PARIS", "LYON", "MARSEILLE", "TOULOUSE", "BORDEAUX",
    "NANTES", "STRASBOURG", "LILLE", "RENNES", "REIMS",
    "TOULON", "GRENOBLE", "DIJON", "ANGERS", "NÎMES",
    "VILLEURBANNE", "LE MANS", "AIX-EN-PROVENCE", "CLERMONT-FERRAND", "BREST",
    "TOURS", "AMIENS", "LIMOGES", "ANNECY", "PERPIGNAN",
    "METZ", "BESANÇON", "ORLÉANS", "MULHOUSE", "ROUEN",
    "CAEN", "NANCY", "AVIGNON", "POITIERS", "ARGENTEUIL",
    "SAINT-ÉTIENNE", "MONTREUIL", "ROUBAIX", "TOURCOING", "NANTERRE",
    "VITRY-SUR-SEINE", "CRÉTEIL", "PAU", "LA ROCHELLE", "CALAIS",
    "BOURGES", "MÉRIGNAC", "SAINT-NAZAIRE", "COLMAR", "TROYES",
]

# ─────────────────────────────────────────────────────────────────────────────


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


def run_sql_update(query: str, db: str = DB_NAME) -> int:
    """Exécute un UPDATE et retourne le nombre de lignes affectées."""
    cmd = [
        "docker", "exec", "-i", CONTAINER,
        SQLCMD,
        "-S", DB_HOST, "-U", DB_USER, "-P", DB_PASS,
        "-d", db, "-C", "-h", "-1",
        "-Q", f"SET NOCOUNT OFF; {query}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        line = line.strip()
        m = re.search(r'\((\d+) rows? affected\)', line, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return 0


def run_sql_update_par_ligne(table_full: str, colonne: str, noms: list[str],
                              db: str = DB_NAME) -> int:
    """
    Récupère le physloc de chaque ligne, envoie les UPDATE par petits lots via stdin.
    """
    rows = run_sql(f"""
        SELECT CONVERT(varchar(20), %%physloc%%, 1) AS LOC
        FROM {table_full}
        WHERE {colonne} IS NOT NULL AND RTRIM(CAST({colonne} AS nvarchar(500))) <> ''
    """)
    locs = [r["LOC"] for r in rows if r.get("LOC")]

    if not locs:
        return 0

    lines = []
    for loc, nom in zip(locs, noms):
        nom_esc = nom.replace("'", "''")
        lines.append(
            f"UPDATE {table_full} SET {colonne} = N'{nom_esc}' WHERE %%physloc%% = {loc}"
        )

    # Découper en lots pour éviter RESOURCE_SEMAPHORE_QUERY_COMPILE
    BATCH_SIZE = 500
    total = 0
    for i in range(0, len(lines), BATCH_SIZE):
        batch = lines[i:i + BATCH_SIZE]
        script = "\n".join(batch)
        cmd = [
            "docker", "exec", "-i", CONTAINER,
            SQLCMD,
            "-S", DB_HOST, "-U", DB_USER, "-P", DB_PASS,
            "-d", db, "-C", "-h", "-1",
        ]
        result = subprocess.run(cmd, input=script, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            m = re.search(r'\((\d+) rows? affected\)', line.strip(), re.IGNORECASE)
            if m:
                total += int(m.group(1))
    return total


def generer_nom_entreprise(rng: random.Random) -> str:
    type_jur = rng.choice(TYPES_ENTREPRISE)
    nom = rng.choice(NOMS_FAMILLE)
    return f"{type_jur} {nom}"


def generer_nom_personne(rng: random.Random) -> str:
    prenom = rng.choice(PRENOMS)
    nom = rng.choice(NOMS_FAMILLE)
    return f"{prenom} {nom}"


def generer_prenom(rng: random.Random) -> str:
    return rng.choice(PRENOMS)


def generer_ville(rng: random.Random) -> str:
    return rng.choice(VILLES)


def generer_noms(n: int, type_champ: str, seed: int) -> list[str]:
    """Génère n noms aléatoires uniques (déterministe via seed)."""
    rng = random.Random(seed)
    noms = []
    for _ in range(n):
        if type_champ == "entreprise":
            noms.append(generer_nom_entreprise(rng))
        elif type_champ == "prenom":
            noms.append(generer_prenom(rng))
        elif type_champ == "ville":
            noms.append(generer_ville(rng))
        else:
            noms.append(generer_nom_personne(rng))
    return noms


def traiter_champ(table_full: str, colonne: str, type_champ: str, apply: bool) -> tuple[str, int]:
    """Traite un champ : compte, génère, applique. Retourne (texte_sortie, nb_updates)."""
    lignes = []
    lignes.append(f"\n{'='*70}")
    lignes.append(f"  {table_full}  |  {colonne}  |  {type_champ}")
    lignes.append(f"{'='*70}")

    rows = run_sql(f"""
        SELECT COUNT(*) AS N
        FROM {table_full}
        WHERE {colonne} IS NOT NULL AND RTRIM(CAST({colonne} AS nvarchar(500))) <> ''
    """)
    nb_lignes = rows[0]["N"] if rows else 0

    if not nb_lignes:
        lignes.append("    Aucune valeur trouvée.")
        return "\n".join(lignes), 0

    lignes.append(f"    {nb_lignes} ligne(s) à anonymiser")

    seed = random.randint(0, 2**31)
    noms = generer_noms(nb_lignes, type_champ, seed)

    lignes.append(f"    Exemples de noms générés :")
    for nom in noms[:5]:
        lignes.append(f"      {nom!r}")
    if nb_lignes > 5:
        lignes.append(f"      ... ({nb_lignes - 5} autres)")

    nb_updates = 0
    if apply:
        lignes.append(f"    Application des mises à jour...")
        nb_updates = run_sql_update_par_ligne(table_full, colonne, noms)
        lignes.append(f"    ✓ {nb_updates} ligne(s) mise(s) à jour")

    return "\n".join(lignes), nb_updates


def traiter_table(table_full: str, champs: list[tuple[str, str]], apply: bool) -> tuple[str, int]:
    """Traite tous les champs d'une table séquentiellement (évite les verrous)."""
    lignes = []
    total = 0
    for colonne, type_champ in champs:
        output, nb = traiter_champ(table_full, colonne, type_champ, apply)
        lignes.append(output)
        total += nb
    return "\n".join(lignes), total


def main():
    apply = "--apply" in sys.argv

    if not apply:
        print("\n  Mode simulation (--apply pour appliquer)\n")

    total_updates = 0

    # Regrouper les champs par table pour éviter les verrous entre threads
    from collections import defaultdict
    par_table: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for table_full, colonne, type_champ in CHAMPS_A_ANONYMISER:
        par_table[table_full].append((colonne, type_champ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(traiter_table, table_full, champs, apply): table_full
            for table_full, champs in par_table.items()
        }
        for future in concurrent.futures.as_completed(futures):
            output, nb = future.result()
            print(output)
            total_updates += nb

    print(f"\n{'='*70}")
    if apply:
        print(f"  TOTAL : {total_updates} ligne(s) mise(s) à jour")
    else:
        print(f"  Simulation terminée. Lancez avec --apply pour appliquer.")
    print()


if __name__ == "__main__":
    main()
