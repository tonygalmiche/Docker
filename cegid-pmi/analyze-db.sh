#!/bin/bash

# Script d'analyse de la base de données SQL Server
# Affiche toutes les tables avec leur nombre de lignes

# Charger la configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

DB_NAME="${1:-$DB_NAME}"

echo "📊 Analyse de la base de données: $DB_NAME"
echo "================================================"
echo ""

# Vérifier que le conteneur est en cours d'exécution
if ! docker ps | grep -q $CONTAINER_NAME; then
    echo "❌ Le conteneur SQL Server n'est pas en cours d'exécution!"
    echo "   Démarrez-le avec: docker-compose up -d"
    exit 1
fi

# Requête SQL pour obtenir toutes les tables avec leur nombre de lignes
SQL_QUERY="
SET NOCOUNT ON;

SELECT 
    SCHEMA_NAME(t.schema_id) + '.' + t.name AS TableName,
    SUM(p.rows) AS [RowCount],
    CAST(ep.value AS NVARCHAR(256)) AS Description
FROM 
    sys.tables t
INNER JOIN 
    sys.partitions p ON t.object_id = p.object_id
LEFT JOIN
    sys.extended_properties ep 
        ON ep.major_id   = t.object_id
        AND ep.minor_id  = 0
        AND ep.class     = 1
        AND ep.name      = 'MS_Description'
WHERE 
    p.index_id IN (0, 1)  -- Heap ou clustered index
    AND t.is_ms_shipped = 0  -- Exclure les tables système
GROUP BY 
    t.schema_id, t.name, ep.value
HAVING 
    SUM(p.rows) > 0  -- Seulement les tables avec des données
ORDER BY 
    SUM(p.rows) DESC;
"

# Exécuter la requête
docker exec -i $CONTAINER_NAME $SQLCMD_PATH \
    -S $DB_HOST -U $DB_USER -P "$DB_PASSWORD" \
    -d "$DB_NAME" \
    -C -h -1 -W -s "|" \
    -Q "$SQL_QUERY"

echo ""
echo "================================================"
echo "✅ Analyse terminée!"
