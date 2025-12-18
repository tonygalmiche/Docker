#!/bin/bash
set -e

# Chargement des variables d'environnement
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

log() {
    echo "[$(date +%H:%M:%S)] $1"
}

log "🛑 Arrêt des conteneurs et suppression des volumes existants..."
docker compose down -v


log "🚀 Démarrage de la base de données uniquement..."
docker compose up -d db

log "⏳ Attente que la base de données soit prête..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if docker compose exec db pg_isready -U ${POSTGRES_USER} > /dev/null 2>&1; then
        log "✅ Base de données prête."
        break
    fi
    echo -n "."
    sleep 1
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    log "❌ La base de données n'a pas démarré dans les temps."
    exit 1
fi

log "🗄️ Création de la base 'odoo-13' (si elle n'existe pas)..."
docker compose exec db createdb -U ${POSTGRES_USER} odoo-13 2>&1 | grep -v "already exists" || true

log "📥 Importation du dump SQL..."
if [ -f "odoo.sql.gz" ]; then
    zcat odoo.sql.gz | docker compose exec -T db psql -U ${POSTGRES_USER} odoo-13 > /dev/null 2>&1 || true
    log "✅ Dump importé (erreurs de droits ignorées)."
    
    log "🔍 Vérification : Comptage des utilisateurs..."
    docker compose exec db psql -U ${POSTGRES_USER} -d odoo-13 -c "SELECT count(*) as nb_users FROM res_users;"
else
    log "❌ Fichier odoo.sql.gz non trouvé !"
    exit 1
fi

log "📂 Restauration du filestore..."
if [ -f "home.tgz" ]; then
    # Nettoyage temporaire
    rm -rf home_temp
    mkdir -p home_temp
    
    # Extraction
    tar -xzf home.tgz -C home_temp
    
    # Démarrage d'Odoo pour pouvoir copier dans son volume
    log "🚀 Démarrage d'Odoo pour copier le filestore..."
    docker compose up -d odoo
    sleep 3
    
    # Création du dossier cible
    docker compose exec odoo mkdir -p /var/lib/odoo/filestore
    
    # Copie du filestore - adapter le chemin selon la structure de l'archive
    if [ -d "home_temp/home/odoo/.local/share/Odoo/filestore" ]; then
        # Si le dossier filestore contient directement les bases
        docker compose cp home_temp/home/odoo/.local/share/Odoo/filestore/. odoo:/var/lib/odoo/filestore/
        
        # Correction des permissions
        docker compose exec -u root odoo chown -R odoo:odoo /var/lib/odoo/filestore
        
        # Renommer le dossier 'odoo' en 'odoo-13' si nécessaire
        log "🔄 Adaptation du nom du filestore à la base de données..."
        docker compose exec odoo bash -c "if [ -d /var/lib/odoo/filestore/odoo ] && [ ! -d /var/lib/odoo/filestore/odoo-13 ]; then mv /var/lib/odoo/filestore/odoo /var/lib/odoo/filestore/odoo-13; fi"
        docker compose exec odoo bash -c "if [ -d /var/lib/odoo/filestore/odoo ] && [ -d /var/lib/odoo/filestore/odoo-13 ]; then rm -rf /var/lib/odoo/filestore/odoo-13 && mv /var/lib/odoo/filestore/odoo /var/lib/odoo/filestore/odoo-13; fi"
        
        log "✅ Filestore restauré."
    elif [ -d "home_temp/filestore" ]; then
        # Alternative : si le dossier filestore est à la racine
        docker compose cp home_temp/filestore/. odoo:/var/lib/odoo/filestore/
        docker compose exec -u root odoo chown -R odoo:odoo /var/lib/odoo/filestore
        
        # Renommer si nécessaire
        docker compose exec odoo bash -c "if [ -d /var/lib/odoo/filestore/odoo ] && [ ! -d /var/lib/odoo/filestore/odoo-13 ]; then mv /var/lib/odoo/filestore/odoo /var/lib/odoo/filestore/odoo-13; fi"
        docker compose exec odoo bash -c "if [ -d /var/lib/odoo/filestore/odoo ] && [ -d /var/lib/odoo/filestore/odoo-13 ]; then rm -rf /var/lib/odoo/filestore/odoo-13 && mv /var/lib/odoo/filestore/odoo /var/lib/odoo/filestore/odoo-13; fi"
        
        log "✅ Filestore restauré."
    else
        log "⚠️ Dossier filestore non trouvé dans l'archive."
        log "Structure de l'archive :"
        find home_temp -type d | head -20
    fi
    
    # Nettoyage
    rm -rf home_temp
else
    log "⚠️ Fichier home.tgz non trouvé."
fi

log "🔄 Redémarrage d'Odoo et nginx..."
docker compose restart odoo
docker compose up -d nginx

log "⏳ Attente du démarrage d'Odoo..."
sleep 5

log "🎉 Restauration terminée ! Odoo 13 est accessible sur http://docker-odoo13:8080"
