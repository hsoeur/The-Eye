# Alertes : historique, acquittement, maintenance

Le module **Alertes** évalue des règles (seuils) sur les mesures des modules Réseau, Docker et Machines, puis historise
tout dans une base : déclenchement, aggravation, acquittement (auteur, IP, commentaire), commentaires, maintenance,
résolution.

## Fonctionnement

- Évaluation toutes les 15 s (`interval_s`). Une alerte naît après le **délai avant alerte** (`for_seconds`, anti-rebond),
  se résout après le **délai de retour** (`recover_seconds`) et la **hystérésis**. Réapparition < 5 min = alerte réouverte ;
  ≥ 3 oscillations en 1 h = « instable ».
- **Cause racine** : si une machine est injoignable, ses autres alertes sont masquées (« dépendantes »).
- **Acquittement** : nom + commentaire obligatoires, durée optionnelle. Une aggravation (avertissement → critique) retire l'acquittement.
- **Maintenance** : fenêtres ponctuelles, quotidiennes ou hebdomadaires ; les alertes sont mises en silence mais historisées.
- Les alertes dont la mesure disparaît depuis plus de 10 min sont résolues (« plus de données »).
- Règles par défaut : machine injoignable, CPU, RAM, disque, service en défaut, container en défaut, équipement réseau hors ligne.
- L'évaluation ne dépend jamais de la base : les écritures passent par un journal local (`data/alerts_outbox.jsonl`) rejoué
  automatiquement quand MySQL revient, même après un redémarrage. Un instantané (`data/alerts_state.json`) permet de repartir si la base est absente au démarrage.

## Base de données

Sans configuration, SQLite (`data/alerts.db`) est utilisé. Pour MySQL (8.x) installé sur la VM de supervision :

```sql
CREATE DATABASE theeye CHARACTER SET utf8mb4;
CREATE USER 'theeye'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'MOT_DE_PASSE';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON theeye.* TO 'theeye'@'127.0.0.1';
```

Les tables sont créées et migrées automatiquement (`schema_version`). Dans `data/config.json` :

```json
{ "modules": { "alerts": { "interval_s": 15, "retention_days": 365,
  "db": { "type": "mysql", "host": "127.0.0.1", "port": 3306, "database": "theeye", "user": "theeye", "password_enc": "…" } } } }
```

- Chiffrer le mot de passe (DPAPI, compte qui lance The Eye) : `python -m theeye.modules.alerts.protect`.
- Le pilote **PyMySQL** (pur Python) est fourni hors-ligne dans `vendor/` — aucune installation, réseau fermé compris.
- MySQL 8 : `caching_sha2_password` exige soit `"tls": true`, soit le paquet `cryptography` ; l'utilisateur ci-dessus
  utilise `mysql_native_password` (désactivé par défaut en 8.4 : activez-le ou passez en TLS).
- Sauvegarde : `mysqldump --single-transaction theeye > theeye.sql` (tâche planifiée). L'historique est purgé au-delà de `retention_days`.
- phpMyAdmin n'est pas nécessaire ; MySQL Workbench ou HeidiSQL suffisent.

## API

`GET /api/alerts` (actives), `/status`, `/history`, `/export.csv`, `/stats`, `/catalog`, `/rules`, `/maintenance`,
`GET /api/alerts/{id}` (chronologie), `POST /api/alerts/{id}/ack|unack|comment` (`author`, `comment`, `until`).
L'interface n'a pas d'authentification : le nom saisi est tracé avec l'adresse IP du poste.
