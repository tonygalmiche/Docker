#!/bin/bash
set -e

# Initialiser la base avec le module base
odoo -i base -d odoo_prod --stop-after-init

# Changer le mot de passe admin
python3 << EOF
import xmlrpc.client
import os

url = "http://localhost:8069"
db = "odoo_prod"
username = "admin"
old_password = "admin"
new_password = os.environ.get('ODOO_ADMIN_PASSWORD', 'admin123')

try:
    common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
    uid = common.authenticate(db, username, old_password, {})
    if uid:
        models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))
        models.execute_kw(db, uid, old_password, 'res.users', 'write', [[uid], {'password': new_password}])
        print(f"Mot de passe changé avec succès pour l'utilisateur {username}")
except Exception as e:
    print(f"Erreur lors du changement de mot de passe: {e}")
EOF

# Démarrer Odoo normalement
exec odoo
