#!/bin/bash
# Script pour accéder à la console interactive SQL Server
# Usage: ./sqlserver-console.sh

# Charger la configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

docker exec -it $CONTAINER_NAME $SQLCMD_PATH \
  -S $DB_HOST -U $DB_USER -P "$DB_PASSWORD" -C
