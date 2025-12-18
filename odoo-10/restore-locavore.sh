#!/bin/bash
set -e

log() {
    echo "[15:05:42] $1"
}

log "🛑 Arrêt des conteneurs et suppression des volumes existants..."
docker compose down -v


log "🚀 Démarrage de la base de données..."
docker compose up -d db

log "⏳ Attente que la base de données soit prête (Healthcheck)..."
until [ "`docker inspect -f {{.State.Health.Status}} odoo-10-db-1`" == "healthy" ]; do
    sleep 2;
    echo -n "."
done
echo ""
log "✅ Base de données prête."

log "👤 Création du rôle 'odoo' (requis par le dump)..."
docker compose exec db createuser -U odoo_user odoo || true

log "🗄️ Création de la base 'locavore'..."
docker compose exec db createdb -U odoo_user locavore

log "📥 Importation du dump SQL..."
if [ -f "locavore-3.sql.gz" ]; then
    zcat locavore-3.sql.gz | docker compose exec -T db psql -U odoo_user locavore > /dev/null 2>&1 || true
    log "✅ Dump importé (erreurs de droits ignorées)."
    
    log "🔍 Vérification : Comptage des produits..."
    docker compose exec db psql -U odoo_user -d locavore -c "SELECT count(*) as nb_products FROM product_template;"
else
    log "❌ Fichier locavore-3.sql.gz non trouvé !"
    exit 1
fi

log "📂 Restauration du filestore..."
if [ -f "home-3.tgz" ]; then
    # Nettoyage temporaire
    rm -rf home_temp
    mkdir -p home_temp
    
    # Extraction
    tar -xzf home-3.tgz -C home_temp
    
    # Démarrage du conteneur Odoo (nécessaire pour copier les fichiers)
    docker compose up -d odoo
    
    # Création du dossier cible
    docker compose exec odoo mkdir -p /var/lib/odoo/filestore
    
    # Copie du filestore
    if [ -d "home_temp/home/odoo/.local/share/Odoo/filestore/locavore" ]; then
        docker compose cp home_temp/home/odoo/.local/share/Odoo/filestore/locavore odoo:/var/lib/odoo/filestore/
        
        # Correction des permissions
        docker compose exec -u root odoo chown -R odoo:odoo /var/lib/odoo/filestore/locavore
        log "✅ Filestore restauré."
    else
        log "⚠️ Dossier filestore non trouvé dans l'archive."
    fi
    
    # Nettoyage
    rm -rf home_temp
else
    log "⚠️ Fichier home-3.tgz non trouvé."
fi

log "🛑 Arrêt d'Odoo pour mise à jour..."
docker compose stop odoo

log "🔄 Mise à jour du module is_locavore..."
docker compose run --rm odoo odoo -u is_locavore -d locavore --stop-after-init

log "🚀 Démarrage final d'Odoo..."
docker compose up -d odoo

log "🎉 Restauration terminée ! Odoo est accessible sur http://localhost:8069"
