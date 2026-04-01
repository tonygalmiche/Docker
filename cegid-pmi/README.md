# Restauration Base de Données Cegid PMI avec Docker

Configuration Docker pour SQL Server permettant de restaurer une base de données Cegid PMI à partir d'un fichier `.bak`.

## 📋 Prérequis

- Docker et Docker Compose installés
- Un fichier de sauvegarde `.bak` de votre base Cegid PMI
- Au moins 2 GB de RAM disponible pour le conteneur SQL Server

## 🚀 Installation et Démarrage

### 1. Configuration initiale

Créez les dossiers nécessaires :

```bash
mkdir -p backup scripts
```

### 2. Placer votre fichier de sauvegarde

Copiez votre fichier `.bak` dans le dossier `backup/` :

```bash
cp /chemin/vers/votre/sauvegarde.bak ./backup/
```

### 3. Modifier le mot de passe (IMPORTANT)

**⚠️ SÉCURITÉ**: Changez le mot de passe par défaut dans les fichiers suivants :
- `docker-compose.yml` : ligne `SA_PASSWORD`
- `restore-db.sh` : ligne `SA_PASSWORD`

Le mot de passe doit respecter les critères SQL Server :
- Au moins 8 caractères
- Contenir des majuscules, minuscules, chiffres et symboles

### 4. Démarrer SQL Server

```bash
docker-compose up -d
```

Attendez que le conteneur soit prêt (environ 30 secondes) :

```bash
docker-compose logs -f sqlserver
```

### 5. Restaurer la base de données

Rendez le script exécutable et lancez la restauration :

```bash
chmod +x restore-db.sh
./restore-db.sh votre_fichier.bak NOM_BASE
```

Exemple :
```bash
./restore-db.sh cegid_pmi_backup.bak CEGID_PMI
```

## 🔌 Connexion à la base

Une fois restaurée, vous pouvez vous connecter à la base avec :

- **Serveur** : `localhost,1433` ou `127.0.0.1,1433`
- **Utilisateur** : `sa`
- **Mot de passe** : celui défini dans `docker-compose.yml`
- **Base de données** : le nom spécifié lors de la restauration

### Exemples de connexion

**Depuis l'hôte avec sqlcmd :**
```bash
docker exec -it cegid-pmi-sqlserver /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U sa -P 'VotreMotDePasseF0rt!'
```

**Connection string pour applications :**
```
Server=localhost,1433;Database=CEGID_PMI;User Id=sa;Password=VotreMotDePasseF0rt!;TrustServerCertificate=True;
```

## 🛠️ Commandes utiles

### Lister les bases de données
```bash
docker exec -it cegid-pmi-sqlserver /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U sa -P 'VotreMotDePasseF0rt!' \
  -Q "SELECT name FROM sys.databases"
```

### Voir les tables d'une base
```bash
docker exec -it cegid-pmi-sqlserver /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U sa -P 'VotreMotDePasseF0rt!' -d CEGID_PMI \
  -Q "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'"
```

### Créer une sauvegarde
```bash
docker exec -it cegid-pmi-sqlserver /opt/mssql-tools/bin/sqlcmd \
  -S localhost -U sa -P 'VotreMotDePasseF0rt!' \
  -Q "BACKUP DATABASE [CEGID_PMI] TO DISK='/backup/cegid_pmi_$(date +%Y%m%d).bak'"
```

### Arrêter le conteneur
```bash
docker-compose down
```

### Supprimer complètement (données incluses)
```bash
docker-compose down -v
```

## 📂 Structure des dossiers

```
cegid-pmi/
├── docker-compose.yml      # Configuration Docker
├── restore-db.sh           # Script de restauration
├── README.md              # Ce fichier
├── backup/                # Placez vos fichiers .bak ici
└── scripts/               # Scripts SQL personnalisés (optionnel)
```

## 🐛 Dépannage

### Le conteneur ne démarre pas
- Vérifiez que le port 1433 n'est pas déjà utilisé : `sudo netstat -tlnp | grep 1433`
- Consultez les logs : `docker-compose logs sqlserver`

### Erreur de mot de passe
- Le mot de passe doit respecter les exigences de complexité SQL Server
- Utilisez des guillemets simples si le mot de passe contient des caractères spéciaux

### La restauration échoue
- Vérifiez que le fichier .bak est bien dans le dossier `backup/`
- Consultez les erreurs détaillées dans la sortie du script
- Assurez-vous d'avoir assez d'espace disque

### Problèmes de permissions
```bash
chmod +x restore-db.sh
sudo chown -R $USER:$USER backup/
```

## 📝 Notes

- SQL Server Express est utilisé (gratuit, limité à 10 GB par base)
- Les données sont persistées dans un volume Docker nommé `sqlserver_data`
- Le healthcheck vérifie automatiquement que SQL Server est opérationnel
- Sauvegardez régulièrement vos données !

## 🔗 Ressources

- [Documentation SQL Server Docker](https://hub.docker.com/_/microsoft-mssql-server)
- [Documentation Cegid PMI](https://www.cegid.com/)
