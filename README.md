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
Onglet **🐳 Docker** : tous les containers (actifs/arrêtés), santé, CPU, RAM, réseau, disque, ports, courbes (inventaire rafraîchi toutes les 15 s, configurable) et logs en direct. Utilise le CLI `docker` (Docker Desktop ou `DOCKER_HOST` pour un serveur distant).
Les actions Start/Stop/Restart depuis l'UI sont autorisées par défaut. L'option historique `--docker-actions` reste acceptée mais n'est plus nécessaire. Pour les désactiver explicitement, définir `"actions": false` dans `modules.docker` (l'interface n'est pas authentifiée).

### Watchdog du moteur Docker (sous-onglet « Moteur »)
Une sonde légère (`docker version --format "{{.Server.Version}}"`, puis `docker ps -q` si la première répond, toutes les 30 s, délai 15 s chacune) détecte un moteur lent ou figé, y compris un daemon qui répond à `version` mais pas aux opérations sur les containers. Elle est indépendante du poll lourd (`docker ps -a` + `docker stats`), suspendu tant que le moteur est figé.
- **États** : `healthy` → `degraded` (2 sondes lentes ou en échec de suite, seuil de lenteur 5 s) → `hung` (3 échecs consécutifs : délai dépassé, code ≠ 0, CLI absent, réponse invalide) → `recovering` (1ʳᵉ réponse correcte) → `healthy` (3 réponses correctes). Un événement par transition : `docker_engine_degraded`, `docker_engine_hung`, `docker_engine_recovered`.
- **Preuves** : à l'entrée en `hung` (une fois par incident, avant toute relance), un dossier `data/incidents/docker-AAAAMMJJ-HHMMSS/` reçoit : `summary.json` (raison, résultat de chaque étape, versions), `probe-history.json`, `events.csv` (événements Windows des 3 dernières heures), `system.txt` (mémoire, processus Docker/WSL, disque, distributions WSL), `docker.txt` (`docker info/ps/system df`) et `logs/docker-desktop/{host,vm}/` (queues des journaux Docker Desktop et de la VM WSL : dockerd, containerd, backend…). Chaque étape est isolée (une erreur n'empêche pas les autres) ; seuls les `max_incidents` derniers dossiers sont conservés. Événement `docker_incident_captured`. Capture manuelle : bouton de l'onglet (avec `--docker-actions`) ou `POST /api/docker/watchdog/capture`.
- **Alertes** : métriques `docker_engine_latency_s`, `docker_engine_state` (0 sain, 1 dégradé, 2 figé, 3 rétablissement) et `docker_engine_hung` sur la cible `docker-host` ; règles par défaut « Moteur Docker lent » (> 5 s pendant 1 min, warning) et « Moteur Docker figé » (critique), ajoutées une seule fois aux installations existantes. `GET /api/docker/watchdog` expose l'état, l'historique, les incidents et la configuration effective.
- **Relance automatique** (`auto_recover`, **désactivée par défaut**, activable/désactivable depuis le bouton de l'onglet Moteur avec `--docker-actions`, ou via `POST /api/docker/watchdog/auto-recover {"enabled": true}` ; le choix est mémorisé dans `data/docker_watchdog.json` et prime sur `config.json`) : après `recover_after_s` en `hung` et une fois la capture terminée, arrêt de Docker Desktop, `wsl --shutdown`, relance. Garde-fous : délai minimal entre relances, plafond par 24 h, une seule relance à la fois, suspendue en fenêtre de maintenance, **Windows et Docker local uniquement** (pas de relance si `DOCKER_HOST` pointe vers un hôte distant ; un `DOCKER_CONTEXT` distant n'est pas détecté). Après la relance, les containers `Exited (255)` sans politique restart sont listés (événement `info`) mais jamais redémarrés. Risques : tous les containers sont coupés ; un lancement depuis un service Windows (session 0) peut ne pas afficher/démarrer Docker Desktop correctement.

```json
{ "modules": { "docker": { "actions": true, "interval_s": 15, "probe_interval_s": 30, "probe_timeout_s": 15, "slow_threshold_s": 5,
  "degraded_after": 2, "hung_after": 3, "healthy_after": 3, "capture_on_hung": true, "max_incidents": 10,
  "auto_recover": false, "recover_after_s": 120, "recover_cooldown_min": 30, "max_recoveries_per_day": 3 } } }
```
Les valeurs hors bornes sont ignorées (défaut conservé) avec un avertissement dans les logs. L'ancien `interval_s: 2` est désormais invalide (minimum 5 s).

## Supervision de machines (onglet 🖥️ Machines)

Procédure pas à pas : [docs/SUPERVISION-MACHINES-WINDOWS.md](docs/SUPERVISION-MACHINES-WINDOWS.md).
Ajoutez une ou plusieurs machines par IP : CPU, mémoire, réseau, disques, **services** (avec détection des services auto arrêtés/en échec), top processus, ports en écoute, erreurs récentes des journaux, et historique des changements (service tombé, machine injoignable). Rafraîchi toutes les ~10 s, lecture seule.
- **Windows** : via WinRM. Sur la cible : `Enable-PSRemoting -Force`. Depuis The Eye (hors domaine) : `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "IP_CIBLE"`. Compte utilisateur membre de *Remote Management Users* (+ *Event Log Readers*). Le mot de passe est chiffré par DPAPI (lisible uniquement par le compte Windows qui lance The Eye) ; laissez vide pour utiliser ce compte (Kerberos/domaine). La machine locale est lue directement.
- **Linux** : via le client `ssh` (OpenSSH, présent sur Server 2022 en option) en **authentification par clé** (clé de l'utilisateur ou chemin indiqué). Nécessite `systemctl`, `ss`, `journalctl` côté cible pour les services/ports/erreurs.

## Alertes (onglet 🔔 Alertes)
Moteur de seuils avec anti-rebond, gravités, acquittement avec commentaire, maintenance planifiée et historique complet (MySQL ou SQLite). Détails, création de la base MySQL et API : [docs/ALERTES-MYSQL.md](docs/ALERTES-MYSQL.md). Seule dépendance : le pilote PyMySQL, fourni hors-ligne dans `vendor/` et utilisé uniquement si MySQL est configuré.

## Coffre (onglet 🔑 Coffre)
Mots de passe des comptes de production, avec les machines / postes / usages où ils servent. Dépendance : `cryptography`, fournie hors-ligne dans `vendor/` (roues Python 3.12 / Windows x64) et installée dans `lib/` au déploiement ; en local : `pip install --no-index --find-links vendor --target lib -r requirements.txt` (sans elle le module signale l'erreur, le reste fonctionne).
- Secrets chiffrés au repos (AES-256-GCM) dans `data/vault.json` ; clé dérivée (scrypt) d'une **phrase secrète jamais stockée** — perdue, les secrets sont irrécupérables. Sauvegarder `data/vault.json`.
- Verrouillé au démarrage et après inactivité (`modules.vault.auto_lock_min`, défaut 10). Afficher un secret exige de re-saisir la phrase ; chaque accès est audité (onglet Audit, jamais le secret). Anti-force brute : délai croissant après échec.
- Alerte possible via la mesure `vault_stale_secrets` (comptes non changés depuis `modules.vault.rotation_days`, défaut 90).
- ⚠️ L'application n'a pas d'authentification utilisateur : le déverrouillage vaut pour tous les clients connectés. Servir en HTTPS (reverse proxy) et restreindre l'accès réseau.

## Windows Server 2022 (démarrage automatique)
```
New-NetFirewallRule -DisplayName "The Eye" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
schtasks /Create /TN "TheEye" /SC ONSTART /RU SYSTEM /TR "python C:\chemin\eye.py"
```
Les données persistent dans `data\state.json`. Les types d'équipement sont devinés (ports, constructeur MAC) et modifiables dans l'UI.

⚠️ Ne scannez que des réseaux qui vous appartiennent ; les scans de ports peuvent perturber certains automates anciens (PLC) – utilisez `ports:false` côté API si besoin.
