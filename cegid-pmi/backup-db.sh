#!/bin/bash

# Sauvegarde de la base SQL Server dans un fichier .bak
# Usage: ./backup-db.sh <fichier.bak>
# Exemple: ./backup-db.sh mon_backup.bak

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

BAK_FILE="${1:-}"

if [ -z "$BAK_FILE" ]; then
    echo "❌ Erreur: Veuillez spécifier le fichier de destination"
    echo "Usage: $0 <fichier.bak>"
    echo "Exemple: $0 backup_$(date +%Y%m%d_%H%M%S).bak"
    exit 1
fi

# S'assurer que le nom se termine bien par .bak
[[ "$BAK_FILE" != *.bak ]] && BAK_FILE="${BAK_FILE}.bak"

# Créer le dossier backup si nécessaire
mkdir -p "$SCRIPT_DIR/backup"

echo "🔍 Vérification du conteneur SQL Server..."
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Le conteneur $CONTAINER_NAME n'est pas démarré"
    echo "Démarrez-le avec: docker-compose up -d"
    exit 1
fi

echo "💾 Sauvegarde de la base $DB_NAME..."
echo "   Destination : ./backup/$BAK_FILE"

docker exec -i "$CONTAINER_NAME" "$SQLCMD_PATH" \
    -S localhost -U sa -P "$DB_PASSWORD" -C \
    -Q "BACKUP DATABASE [$DB_NAME] TO DISK = '/backup/$BAK_FILE' WITH FORMAT, INIT, STATS = 10"

echo ""
echo "✅ Sauvegarde terminée : ./backup/$BAK_FILE"
