# 👁️ The Eye – cartographie réseau

Découverte (ping sweep + ARP + DNS/NetBIOS + scan de ports), carte interactive, supervision Docker et machines. Backend Python 3.9+ sans dépendance ; interface React + TypeScript (build commité dans `theeye/web`, aucun Node requis pour lancer).

## Lancer
```
python eye.py                       # http://localhost:8765
python eye.py --port 9000 --auto 15 # re-scan réseau toutes les 15 min
python eye.py --disable docker      # désactive un module
python -m unittest discover -s tests
cd frontend; npm install; npm run dev   # UI en développement (http://localhost:5173) ; npm run build régénère theeye/web
```
Options : `--host --port --data-dir --log-level --auto --docker-actions --disable`. Config optionnelle : `data/config.json`.
Santé : `GET /api/health` · modules : `GET /api/modules` · API des modules sous `/api/<module>/...`.

**Architecture modulaire** (ajouter un module = un dossier dans `theeye/modules/`) : voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Le CIDR est détecté automatiquement (sous-réseaux locaux ≤ /22) ou saisi dans l'UI.

## Supervision Docker
Onglet **🐳 Docker** : tous les containers (actifs/arrêtés), santé, CPU, RAM, réseau, disque, ports, courbes temps réel (rafraîchi toutes les 2 s) et logs en direct. Utilise le CLI `docker` (Docker Desktop ou `DOCKER_HOST` pour un serveur distant).
Pour autoriser Start/Stop/Restart depuis l'UI : `python eye.py --docker-actions` (désactivé par défaut, car l'interface n'est pas authentifiée).

## Supervision de machines (onglet 🖥️ Machines)

Procédure pas à pas : [docs/SUPERVISION-MACHINES-WINDOWS.md](docs/SUPERVISION-MACHINES-WINDOWS.md).
Ajoutez une ou plusieurs machines par IP : CPU, mémoire, réseau, disques, **services** (avec détection des services auto arrêtés/en échec), top processus, ports en écoute, erreurs récentes des journaux, et historique des changements (service tombé, machine injoignable). Rafraîchi toutes les ~10 s, lecture seule.
- **Windows** : via WinRM. Sur la cible : `Enable-PSRemoting -Force`. Depuis The Eye (hors domaine) : `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "IP_CIBLE"`. Compte utilisateur membre de *Remote Management Users* (+ *Event Log Readers*). Le mot de passe est chiffré par DPAPI (lisible uniquement par le compte Windows qui lance The Eye) ; laissez vide pour utiliser ce compte (Kerberos/domaine). La machine locale est lue directement.
- **Linux** : via le client `ssh` (OpenSSH, présent sur Server 2022 en option) en **authentification par clé** (clé de l'utilisateur ou chemin indiqué). Nécessite `systemctl`, `ss`, `journalctl` côté cible pour les services/ports/erreurs.

## Alertes (onglet 🔔 Alertes)
Moteur de seuils avec anti-rebond, gravités, acquittement avec commentaire, maintenance planifiée et historique complet (MySQL ou SQLite). Détails, création de la base MySQL et API : [docs/ALERTES-MYSQL.md](docs/ALERTES-MYSQL.md). Seule dépendance : le pilote PyMySQL, fourni hors-ligne dans `vendor/` et utilisé uniquement si MySQL est configuré.

## Windows Server 2022 (démarrage automatique)
```
New-NetFirewallRule -DisplayName "The Eye" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
schtasks /Create /TN "TheEye" /SC ONSTART /RU SYSTEM /TR "python C:\chemin\eye.py"
```
Les données persistent dans `data\state.json`. Les types d'équipement sont devinés (ports, constructeur MAC) et modifiables dans l'UI.

⚠️ Ne scannez que des réseaux qui vous appartiennent ; les scans de ports peuvent perturber certains automates anciens (PLC) – utilisez `ports:false` côté API si besoin.
