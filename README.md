# 👁️ The Eye – cartographie réseau

Découverte (ping sweep + ARP + DNS/NetBIOS + scan de ports) et carte interactive. Python 3.9+ sans dépendance, front vis-network embarqué (fonctionne hors-ligne).

## Lancer
```
python eye.py                 # http://localhost:8765, re-scan toutes les 15 min
python eye.py --port 9000 --auto 0
```
Le CIDR est détecté automatiquement (sous-réseaux locaux ≤ /22) ou saisi dans l'UI.

## Supervision Docker
Onglet **🐳 Docker** : tous les containers (actifs/arrêtés), santé, CPU, RAM, réseau, disque, ports, courbes temps réel (rafraîchi toutes les 2 s) et logs en direct. Utilise le CLI `docker` (Docker Desktop ou `DOCKER_HOST` pour un serveur distant).
Pour autoriser Start/Stop/Restart depuis l'UI : `python eye.py --docker-actions` (désactivé par défaut, car l'interface n'est pas authentifiée).

## Supervision de machines (onglet 🖥️ Machines)

Procédure pas à pas : [docs/SUPERVISION-MACHINES-WINDOWS.md](docs/SUPERVISION-MACHINES-WINDOWS.md).
Ajoutez une ou plusieurs machines par IP : CPU, mémoire, réseau, disques, **services** (avec détection des services auto arrêtés/en échec), top processus, ports en écoute, erreurs récentes des journaux, et historique des changements (service tombé, machine injoignable). Rafraîchi toutes les ~10 s, lecture seule.
- **Windows** : via WinRM. Sur la cible : `Enable-PSRemoting -Force`. Depuis The Eye (hors domaine) : `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "IP_CIBLE"`. Compte utilisateur membre de *Remote Management Users* (+ *Event Log Readers*). Le mot de passe est chiffré par DPAPI (lisible uniquement par le compte Windows qui lance The Eye) ; laissez vide pour utiliser ce compte (Kerberos/domaine). La machine locale est lue directement.
- **Linux** : via le client `ssh` (OpenSSH, présent sur Server 2022 en option) en **authentification par clé** (clé de l'utilisateur ou chemin indiqué). Nécessite `systemctl`, `ss`, `journalctl` côté cible pour les services/ports/erreurs.

## Windows Server 2022 (démarrage automatique)
```
New-NetFirewallRule -DisplayName "The Eye" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
schtasks /Create /TN "TheEye" /SC ONSTART /RU SYSTEM /TR "python C:\chemin\eye.py"
```
Les données persistent dans `data\state.json`. Les types d'équipement sont devinés (ports, constructeur MAC) et modifiables dans l'UI.

⚠️ Ne scannez que des réseaux qui vous appartiennent ; les scans de ports peuvent perturber certains automates anciens (PLC) – utilisez `ports:false` côté API si besoin.
