#!/bin/bash

# Script mis à jour le 2025-12-30 par tonygalmiche
# Objectif : Mise à jour images, audit Debian/Ubuntu et détection Odoo

# Récupère la liste des images locales
images=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep -v "<none>")

echo "$(date '+%Y-%m-%d %H:%M:%S') - === Début du traitement des images Docker ==="

for image in $images; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') - --------------------------------------------------------"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - IMAGE : $image"
    
    # 1. Mise à jour (Pull)
    echo "$(date '+%Y-%m-%d %H:%M:%S') - [1] Mise à jour..."
    docker pull "$image" > /dev/null 2>&1

    # 2. Vérification Debian/Ubuntu
    OS_INFO=$(docker run --rm "$image" cat /etc/os-release 2>/dev/null)
    ID=$(echo "$OS_INFO" | grep "^ID=" | cut -d'=' -f2 | tr -d '"')

    if [[ "$ID" == "debian" || "$ID" == "ubuntu" ]]; then
        PRETTY=$(echo "$OS_INFO" | grep "PRETTY_NAME" | cut -d'"' -f2)
        echo "$(date '+%Y-%m-%d %H:%M:%S') - [2] OS : $PRETTY"
        
        # Vérification des mises à jour système
        echo -n "$(date '+%Y-%m-%d %H:%M:%S') - [3] État des paquets : "
        UPDATES=$(docker run --rm "$image" sh -c "apt-get update -qq && apt-get upgrade -s" 2>/dev/null | grep -i "inst" | wc -l)
        if [ "$UPDATES" -gt 0 ]; then
            echo "⚠️  $UPDATES mises à jour disponibles."
        else
            echo "✅ À jour."
        fi

        # 4. Scan des vulnérabilités
        echo -n "$(date '+%Y-%m-%d %H:%M:%S') - [4] Vulnérabilités : "
        
        # Vérifier si docker scout est disponible
        if command -v docker scout &> /dev/null || docker scout version &> /dev/null 2>&1; then
            VULNS=$(docker scout cves "$image" 2>/dev/null | grep -E "^(C|H|M|L)" | wc -l)
            CRITICAL=$(docker scout cves "$image" 2>/dev/null | grep "^C " | wc -l)
            HIGH=$(docker scout cves "$image" 2>/dev/null | grep "^H " | wc -l)
            
            if [ "$CRITICAL" -gt 0 ] || [ "$HIGH" -gt 0 ]; then
                echo "🔴 $VULNS total (Critiques: $CRITICAL, Élevées: $HIGH)"
            elif [ "$VULNS" -gt 0 ]; then
                echo "🟡 $VULNS total"
            else
                echo "✅ Aucune vulnérabilité détectée"
            fi
        else
            # Fallback sur trivy si disponible
            if command -v trivy &> /dev/null; then
                CRITICAL=$(trivy image --severity CRITICAL --quiet "$image" 2>/dev/null | grep "Total:" | awk '{print $2}')
                HIGH=$(trivy image --severity HIGH --quiet "$image" 2>/dev/null | grep "Total:" | awk '{print $2}')
                TOTAL=$(trivy image --quiet "$image" 2>/dev/null | grep "Total:" | awk '{print $2}')
                
                if [ -n "$TOTAL" ]; then
                    if [ "${CRITICAL:-0}" -gt 0 ] || [ "${HIGH:-0}" -gt 0 ]; then
                        echo "🔴 $TOTAL total (Critiques: ${CRITICAL:-0}, Élevées: ${HIGH:-0})"
                    elif [ "$TOTAL" -gt 0 ]; then
                        echo "🟡 $TOTAL total"
                    else
                        echo "✅ Aucune vulnérabilité détectée"
                    fi
                else
                    echo "⚠️  Impossible d'analyser"
                fi
            else
                echo "⚠️  Docker Scout ou Trivy non disponible"
            fi
        fi

        # 5. Cas spécifique Odoo
        # On vérifie si la commande odoo existe ou si la variable d'env ODOO_VERSION est présente
        ODOO_VER_ENV=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$image" | grep "ODOO_VERSION=" | cut -d'=' -f2)
        
        if [ -n "$ODOO_VER_ENV" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - [5] 📦 DÉTECTION ODOO"
            echo "$(date '+%Y-%m-%d %H:%M:%S') -     Version Odoo  : $ODOO_VER_ENV"
            
            # Récupération de la date de création de l'image (date de la dernière release Docker)
            BUILD_DATE=$(docker inspect -f '{{.Created}}' "$image" | cut -d'T' -f1)
            echo "$(date '+%Y-%m-%d %H:%M:%S') -     Dernier Build : $BUILD_DATE"
            
            # Tentative de récupération de la date de modification du code source Odoo
            # Souvent dans /usr/lib/python3/dist-packages/odoo
            SOURCE_DATE=$(docker run --rm "$image" stat -c '%y' /usr/lib/python3/dist-packages/odoo 2>/dev/null | cut -d' ' -f1)
            if [ -n "$SOURCE_DATE" ]; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') -     Maj Code Odoo : $SOURCE_DATE"
            fi
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - [2] OS : Non Debian/Ubuntu (Ignoré pour l'audit)"
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') - --------------------------------------------------------"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Traitement terminé"
