#!/bin/bash

# Script de restauration de base de données SQL Server
# Usage: ./restore-db.sh nom_fichier.bak nom_base_restauree

set -e

# Charger la configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

BAK_FILE=${1:-""}
DB_NAME=${2:-$DB_NAME}

if [ -z "$BAK_FILE" ]; then
    echo "❌ Erreur: Veuillez spécifier le fichier .bak à restaurer"
    echo "Usage: $0 <fichier.bak> [nom_base_donnees]"
    echo "Exemple: $0 cegid_backup.bak CEGID_PMI"
    exit 1
fi

if [ ! -f "./backup/$BAK_FILE" ]; then
    echo "❌ Erreur: Le fichier ./backup/$BAK_FILE n'existe pas"
    echo "Placez votre fichier .bak dans le dossier ./backup/"
    exit 1
fi

echo "🔍 Vérification du conteneur SQL Server..."
if ! docker ps | grep -q $CONTAINER_NAME; then
    echo "❌ Le conteneur $CONTAINER_NAME n'est pas démarré"
    echo "Démarrez-le avec: docker-compose up -d"
    exit 1
fi

echo "📋 Lecture des informations du fichier de sauvegarde..."
docker exec -i $CONTAINER_NAME /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$DB_PASSWORD" -C -Q \
    "RESTORE FILELISTONLY FROM DISK='/backup/$BAK_FILE'" -y 30

echo ""
echo "🔄 Restauration de la base de données $DB_NAME..."
echo "   Fichier source: $BAK_FILE"

# Récupération des noms logiques des fichiers
LOGICAL_DATA=$(docker exec -i $CONTAINER_NAME /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$DB_PASSWORD" -C -Q \
    "RESTORE FILELISTONLY FROM DISK='/backup/$BAK_FILE'" -h -1 -W | grep -v "rows affected" | awk 'NR==1 {print $1}')

LOGICAL_LOG=$(docker exec -i $CONTAINER_NAME /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$DB_PASSWORD" -C -Q \
    "RESTORE FILELISTONLY FROM DISK='/backup/$BAK_FILE'" -h -1 -W | grep -v "rows affected" | awk 'NR==2 {print $1}')

echo "   Fichier de données logique: $LOGICAL_DATA"
echo "   Fichier de log logique: $LOGICAL_LOG"

# Restauration avec REPLACE
docker exec -i $CONTAINER_NAME /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$DB_PASSWORD" -C -Q \
    "RESTORE DATABASE [$DB_NAME] FROM DISK='/backup/$BAK_FILE' 
    WITH REPLACE,
    MOVE '$LOGICAL_DATA' TO '/var/opt/mssql/data/${DB_NAME}.mdf',
    MOVE '$LOGICAL_LOG' TO '/var/opt/mssql/data/${DB_NAME}_log.ldf',
    STATS = 10"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Base de données restaurée avec succès!"
    echo "   Nom de la base: $DB_NAME"
    echo "   Serveur: localhost,1433"
    echo "   Utilisateur: sa"
    echo "   Mot de passe: $SA_PASSWORD"
else
    echo "❌ Erreur lors de la restauration"
    exit 1
fi
