# Test de Stack IA : vLLM & Open WebUI sur Debian 12

Ce document résume la configuration d'un environnement de test pour l'IA locale sur un ordinateur portable ancien équipé d'un GPU NVIDIA Quadro P1000 (4 Go VRAM).

## 🛠 Matériel et OS
* **OS :** Debian 12 (Bookworm)
* **CPU :** Intel Core i7-8850H @ 2.60GHz
* **RAM :** 64 Go
* **GPU :** NVIDIA Quadro P1000 Mobile (4 Go VRAM - Architecture Pascal)
* **Utilisateur :** `tony` (membre du groupe `docker`)

---

## ⚠️ Point Critique : Pilote NVIDIA (GPU Legacy)

Les GPU d'architecture Pascal (comme la Quadro P1000) ne sont **plus supportés** par les derniers pilotes NVIDIA (versions 590+). Si un pilote trop récent est installé, `nvidia-smi` échouera avec une erreur "Driver Not Loaded" et `dmesg` indiquera que le GPU est ignoré.

**Solution : Utiliser le pilote version 535 (LTS) fourni par les dépôts Debian.**

```bash
# 1. Nettoyage complet des anciens pilotes conflictuels
apt-get purge "*nvidia*" "libcuda*" "libnvidia*"
apt-get autoremove

# 2. Installation de la version compatible (535.xx) et des firmwares
apt-get update
apt-get install nvidia-driver firmware-misc-nonfree

# 3. Redémarrage OBLIGATOIRE
reboot
```

---

## 🏗 Étape 1 : Préparation du Système (en Root)

Avant de lancer les conteneurs, le système doit pouvoir exposer le GPU à Docker via le **NVIDIA Container Toolkit**.

### Installation du Toolkit
```bash
# Ajout du dépôt NVIDIA
curl -fsSL [https://nvidia.github.io/libnvidia-container/gpgkey](https://nvidia.github.io/libnvidia-container/gpgkey) | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L [https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list](https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list) | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Installation
apt-get update && apt-get install -y nvidia-container-toolkit

# Configuration de Docker
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
```

---

## ❌ Incompatibilité vLLM / Quadro P1000

**vLLM ne fonctionne pas sur cette machine.** L'image Docker officielle `vllm/vllm-openai` embarque PyTorch compilé pour CUDA compute capability **>= 7.0** (Volta/Turing et plus récent). La Quadro P1000, basée sur l'architecture **Pascal** (compute capability **6.1**), n'est pas supportée.

### Erreurs constatées (logs du conteneur)

```
Quadro P1000 with CUDA capability sm_61 is not compatible with the current PyTorch installation.
The current PyTorch install supports CUDA capabilities sm_70 sm_75 sm_80 sm_86 sm_90 sm_100 sm_120.
```
```
CUDA error: no kernel image is available for execution on the device
```
```
RuntimeError: Engine core initialization failed.
```

### Pourquoi une ancienne version de vLLM ne résout pas le problème

- **Aucune** image Docker officielle de vLLM n'a jamais embarqué un PyTorch compilé pour sm_61 (Pascal).
- Il n'existe **pas** d'image Docker officielle vLLM pour le CPU (`vllm/vllm-openvino` n'existe pas sur Docker Hub).
- Compiler vLLM soi-même avec un PyTorch ciblant sm_61 est théoriquement possible mais très complexe, et les 4 Go de VRAM seraient de toute façon insuffisants pour des performances acceptables (vLLM a un overhead mémoire important pour la gestion du KV cache).

### Solution retenue : Ollama + Open WebUI

Ollama est installé nativement sur la machine (`systemctl status ollama`). Il supporte parfaitement les GPU Pascal et fonctionne très bien avec 4 Go de VRAM.

Le `docker-compose.yml` a été adapté : le service vLLM est commenté, et Open WebUI se connecte à l'Ollama local via `host.docker.internal:11434`.

Sur un serveur avec un GPU récent (>= Volta/Turing), il suffira de décommenter la configuration vLLM dans le `docker-compose.yml`.

---

## 🏗 Étape 2 : Configuration d'Ollama (en Root)

Ollama doit écouter sur toutes les interfaces pour être accessible depuis le conteneur Docker.

```bash
# Créer un override systemd pour Ollama
systemctl edit ollama.service
```

Ajouter le contenu suivant :

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Puis redémarrer le service :

```bash
systemctl daemon-reload
systemctl restart ollama
```

Vérifier qu'Ollama écoute bien sur `0.0.0.0` :

```bash
ss -tlnp | grep 11434
# Doit afficher : 0.0.0.0:11434
```

---

## 🏗 Étape 3 : Déploiement de la Stack (en tant que Tony)

### Lancement

```bash
cd ~/Documents/Développement/Docker/vllm-open-webui
docker compose up -d
```

L'interface Open WebUI est accessible sur **http://localhost:3000**.

### Commandes Utiles

| Action | Commande |
|---|---|
| Démarrer la stack | `docker compose up -d` |
| Arrêter la stack | `docker compose down` |
| Voir l'état des conteneurs | `docker compose ps` |
| Suivre les logs en temps réel | `docker compose logs -f open-webui` |
| Voir les derniers logs | `docker compose logs open-webui --tail 30` |
| Lister les modèles Ollama | `ollama list` |
| Surveiller la VRAM | `watch -n 1 nvidia-smi` |
| Accès Interface Web | http://localhost:3000 |

### Modèles installés — Compatibilité Quadro P1000 (4 Go VRAM)

| | Modèle | Taille | Statut |
|---|---|---|---|
| ✅ | `qwen3:0.6b` | 522 Mo | OK — Ultra-léger |
| ✅ | `gemma3:1b` | 815 Mo | OK — Ultra-léger |
| ✅ | `deepseek-r1:1.5b` | 1.1 Go | OK — Raisonnement |
| ✅ | `llama3.2:1b` | 1.3 Go | OK |
| ✅ | `qwen3:1.7b` | 1.4 Go | OK — Polyvalent, rapide |
| ✅ | `moondream:latest` | 1.7 Go | OK — Vision |
| ✅ | `llama3.2:3b` | 2.0 Go | OK — Bon équilibre |
| ✅ | `granite3.2-vision:latest` | 2.4 Go | OK — Vision |
| ✅ | `qwen3:4b` | 2.6 Go | OK |
| ✅ | `gemma3:4b` | 3.3 Go | OK |
| ⚠️ | `olmo2:latest` | 4.5 Go | Limite — Risque de débordement CPU |
| ⚠️ | `qwen2.5:7b` | 4.7 Go | Limite — Lent |
| ⚠️ | `deepseek-r1:latest` | 4.7 Go | Limite — Lent |
| ❌ | `minicpm-v:latest` | 5.5 Go | Trop gros |
| ❌ | `llama3.2-vision:11b` | 7.9 Go | Trop gros |
| ❌ | `mistral-small3.1:latest` | 15 Go | Beaucoup trop gros |
| ❌ | `qwen3:32b` | 20 Go | Beaucoup trop gros |

> **Règle :** les modèles > 4 Go débordent de la VRAM et s'exécutent partiellement sur le CPU, ce qui les rend très lents.

```bash
# Supprimer les modèles trop gros
ollama rm qwen3:32b mistral-small3.1:latest llama3.2-vision:11b llama3.2-vision:latest minicpm-v:latest

# Télécharger un modèle (exemple)
ollama pull qwen3:1.7b
```

---

## 📝 Notes d'optimisation vLLM (pour le serveur cible)

Ces paramètres sont destinés au déploiement sur un serveur avec un GPU compatible (>= sm_70) :

- `--enforce-eager` : Désactive CUDA graphs pour économiser la mémoire.
- `--dtype half` : Charge le modèle en FP16 pour diviser son empreinte mémoire par deux.
- `--gpu-memory-utilization 0.80` : Limite l'utilisation de la VRAM à 80%.
- `--max-model-len 2048` : Limite la longueur de contexte pour économiser la mémoire.