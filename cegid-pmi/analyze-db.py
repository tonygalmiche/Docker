#!/usr/bin/env python3
"""
Affiche toutes les tables de la base SQL Server avec leur nombre de lignes.

Usage: python3 analyze-db.py [NOM_BASE]
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
        sys.exit(1)


def main() -> None:
    db = sys.argv[1] if len(sys.argv) >= 2 else DB_NAME

    rows = run_sql(
        """
        SELECT
            SCHEMA_NAME(t.schema_id) + '.' + t.name  AS [Table],
            SUM(p.rows)                               AS [Lignes],
            CAST(ep.value AS NVARCHAR(256))           AS [Description]
        FROM sys.tables t
        INNER JOIN sys.partitions p
            ON t.object_id = p.object_id AND p.index_id IN (0, 1)
        LEFT JOIN sys.extended_properties ep
            ON ep.major_id = t.object_id
           AND ep.minor_id = 0
           AND ep.class    = 1
           AND ep.name     = 'MS_Description'
        WHERE t.is_ms_shipped = 0
        GROUP BY t.schema_id, t.name, ep.value
        HAVING SUM(p.rows) > 0
        ORDER BY SUM(p.rows) DESC
        """,
        db,
    )

    if not rows:
        print("Aucune table trouvée.")
        return

    has_desc = any(r.get("Description") for r in rows)
    cols = ["Table", "Lignes", "Description"] if has_desc else ["Table", "Lignes"]

    # Largeurs
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            val = r.get(c)
            widths[c] = max(widths[c], len(str(val) if val is not None else ""))

    sep    = "+" + "+".join("-" * (widths[c] + 2) for c in cols) + "+"
    header = "|" + "|".join(f" {c:<{widths[c]}} " for c in cols) + "|"

    total_rows = sum(r.get("Lignes", 0) or 0 for r in rows)

    print(f"\nBase de données : {db}")
    print(f"Tables          : {len(rows)}")
    print(f"Total lignes    : {total_rows:,}\n")
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        line = "|"
        for c in cols:
            val = r.get(c)
            if c == "Lignes":
                cell = f"{val:,}" if val is not None else ""
                line += f" {cell:>{widths[c]}} |"
            else:
                cell = str(val) if val is not None else ""
                line += f" {cell:<{widths[c]}} |"
        print(line)
    print(sep)
    print()


if __name__ == "__main__":
    main()
