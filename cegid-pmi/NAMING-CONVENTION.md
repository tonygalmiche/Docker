# Convention de nommage Cegid PMI

## Structure des noms de colonnes

Chaque colonne suit la convention :

```
[PP][T][S][SUFFIXE]
```

| Position | Longueur | Description |
|----------|----------|-------------|
| `PP` | 2 lettres | Préfixe de la table (ex: `CL` pour `CLIENT`, `EC` pour `ECOMCLI`) |
| `T` | 1 lettre | Indicateur de type de données |
| `S` | 1 lettre | Indicateur de sous-type |
| `SUFFIXE` | variable | Nom métier de la colonne |

## Indicateurs de type (`T`)

| Lettre | Type SQL | Description |
|--------|----------|-------------|
| `K` | clé | Colonne de clé (primaire ou lien) |
| `C` | char / nchar | Texte court |
| `N` | decimal / int | Numérique |
| `J` | nchar(8) | Date au format `YYYYMMDD` |

## Indicateurs de sous-type (`S`)

| Lettre | Description |
|--------|-------------|
| `T` | Texte |
| `N` | Numérique |
| `K` | Code clé |

## Exemples

| Colonne | Table | Décodage |
|---------|-------|----------|
| `CLKTCODE` | `CLIENT` | `CL` + `K` (clé) + `T` + `CODE` → code client |
| `CLKTSOC` | `CLIENT` | `CL` + `K` + `T` + `SOC` → code société |
| `ECCTCODE` | `ECOMCLI` | `EC` + `C` + `T` + `CODE` → référence au code client |
| `ECKTNUMERO` | `ECOMCLI` | `EC` + `K` + `T` + `NUMERO` → numéro de commande (clé) |
| `CLCTNOM` | `CLIENT` | `CL` + `C` + `T` + `NOM` → nom du client |
| `ECCJCRE` | `ECOMCLI` | `EC` + `C` + `J` + `CRE` → date de création |
| `CLCTEMAIL` | `CLIENT` | `CL` + `C` + `T` + `EMAIL` → email du client |

## Déduction des relations entre tables

Deux colonnes de tables différentes pointent vers le même objet si elles partagent
le même **suffixe** (à partir du 3ème caractère).

### Exemple : lien ECOMCLI → CLIENT

```
ECOMCLI.ECCTCODE  ─────────→  CLIENT.CLKTCODE
         ^^                            ^^
         EC = table ECOMCLI            CL = table CLIENT
           C = char                      K = clé
           TCODE = suffixe commun      TCODE = suffixe commun
```

### Exemple : lien multi-tables sur la société

```
ECOMCLI.ECKTSOC  ←──── même suffixe KTSOC ────→  CLIENT.CLKTSOC
                                                →  FOURNIS.CLKTSOC
                                                →  UTILISAT.UTKTCODE (suffixe différent)
```

## Préfixes de tables connus

| Préfixe | Table(s) | Description |
|---------|----------|-------------|
| `CL` | `CLIENT` | Clients |
| `EC` | `ECOMCLI` | Commandes clients |
| `CL` | `FOURNIS` (colonnes `CLKT...`) | Fournisseurs (partage le préfixe `CL`) |
| `UT` | `UTILISAT` | Utilisateurs |
| `EX` | `EXERCICE` | Exercices comptables |
| `PR` | `PRODUCT` | Productions / lignes de commande |

> **Note** : certaines tables partagent le même préfixe (ex: `CLIENT` et `FOURNIS` utilisent
> tous les deux `CL`). Le contexte et le suffixe permettent de lever l'ambiguïté.

## Scripts d'analyse disponibles

| Script | Rôle |
|--------|------|
| `analyze-table.py NOM` | Statistiques des colonnes + index |
| `show-table.py NOM [N]` | Affiche N lignes (colonnes distinctes uniquement) |
| `show-relations.py NOM` | FK formelles + relations implicites par suffixe |
| `show-keys.py NOM` | Index et clés d'une table |
| `analyze-db.py` | Liste toutes les tables avec nombre de lignes |
| `dump-db.py` | Dump complet greppable (`[schema.TABLE] col=val`) |
| `anonymize-db.py` | Anonymisation des champs sensibles |
