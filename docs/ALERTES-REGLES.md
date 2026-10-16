# Spécification fonctionnelle — Alertes et règles

## 1. Objectif

Le système d'alertes doit détecter automatiquement les situations anormales observées par The Eye, les associer à une cible identifiable, les afficher aux opérateurs, permettre leur acquittement et conserver l'historique complet de leur cycle de vie.

Le système doit limiter les fausses alertes grâce à :

- un délai avant déclenchement ;
- un délai de retour à la normale ;
- une hystérésis ;
- la gestion des dépendances et des causes racines ;
- les fenêtres de maintenance.

## 2. Périmètre

Le système couvre :

- la création et la modification de règles ;
- l'activation et la désactivation de règles ;
- la surveillance des observations produites par les modules ;
- le déclenchement, l'aggravation et la résolution des alertes ;
- l'acquittement par un opérateur ;
- la maintenance planifiée ;
- la détection des alertes dépendantes ;
- l'historisation ;
- la persistance locale ou MySQL ;
- la reprise après indisponibilité de la base.

Le détail technique de l'envoi d'e-mails est décrit dans [NOTIFICATIONS-ALERTES-SMTP.md](NOTIFICATIONS-ALERTES-SMTP.md).

Le système ne couvre pas encore :

- les notifications Teams ou Slack ;
- l'escalade automatique vers une astreinte ;
- la création de tickets ITSM.

## 3. Définitions

### 3.1 Observation

Une observation est une mesure produite par un module de supervision.

Exemple :

```json
{
  "source": "machines",
  "target": "srv-001",
  "name": "SRV-PROD-01",
  "metric": "cpu_pct",
  "value": 94
}
```

Une observation peut également contenir :

- `item` : disque, service ou composant concerné ;
- `unit` : unité de mesure ;
- toute information complémentaire nécessaire à l'affichage.

### 3.2 Règle

Une règle décrit la condition qui doit déclencher une alerte.

Exemple :

```json
{
  "id": "cpu-high",
  "name": "CPU élevé",
  "metric": "cpu_pct",
  "operator": ">",
  "threshold": 90,
  "severity": "warning",
  "for_seconds": 300,
  "recover_seconds": 120,
  "hysteresis": 5,
  "targets": ["*"],
  "enabled": true
}
```

### 3.3 Alerte

Une alerte est l'instance active d'une règle appliquée à une cible donnée.

Une alerte doit conserver :

- la règle d'origine ;
- la cible ;
- la métrique ;
- la valeur déclenchante ;
- le seuil ;
- la gravité ;
- la date de début ;
- la date de résolution ;
- l'acquittement ;
- les commentaires ;
- les événements associés.

## 4. Modèle de règle

Chaque règle doit comporter les propriétés suivantes :

| Propriété | Obligatoire | Description |
|---|---:|---|
| `id` | Oui | Identifiant stable de la règle |
| `name` | Oui | Nom lisible par l'opérateur |
| `metric` | Oui | Métrique surveillée |
| `operator` | Oui | `>`, `>=`, `<`, `<=`, `==` ou `!=` |
| `threshold` | Oui | Seuil principal |
| `severity` | Oui | `info`, `warning` ou `critical` |
| `critical_threshold` | Non | Seuil d'aggravation critique |
| `for_seconds` | Oui | Durée avant déclenchement |
| `recover_seconds` | Oui | Durée avant résolution |
| `hysteresis` | Non | Marge nécessaire pour confirmer le retour normal |
| `source` | Non | Module producteur de la métrique |
| `targets` | Oui | Cibles concernées, `*` pour toutes |
| `exclude` | Non | Cibles exclues |
| `item` | Non | Filtre sur un disque, service ou composant |
| `enabled` | Oui | Active ou non la règle |
| `description` | Non | Explication fonctionnelle |

### 4.1 Opérateurs

Les opérateurs autorisés sont :

```text
>
>=
<
<=
==
!=
```

### 4.2 Gravités

| Gravité | Signification |
|---|---|
| `info` | Information à conserver, sans urgence |
| `warning` | Situation anormale nécessitant une vérification |
| `critical` | Incident nécessitant une intervention rapide |

### 4.3 Seuil critique

Une règle peut posséder un second seuil.

Exemple :

```text
Disque libre < 15 %  → warning
Disque libre < 5 %   → critical
```

Une aggravation de la sévérité doit retirer automatiquement l'acquittement existant.

## 5. Application des règles

Le moteur évalue périodiquement les observations disponibles.

Pour chaque observation, il vérifie :

1. que la règle est activée ;
2. que la métrique correspond ;
3. que la source correspond, si elle est définie ;
4. que la cible est incluse ;
5. que la cible n'est pas exclue ;
6. que l'élément correspond, s'il est défini ;
7. que la condition dépasse le seuil.

Une règle ne doit jamais produire une alerte pour une observation qui ne correspond pas à ses filtres.

## 6. Cibles des règles

### 6.1 Cible globale

La valeur suivante :

```text
targets: ["*"]
```

signifie que la règle s'applique à toutes les observations compatibles avec la métrique.

Exemple :

```text
cpu_pct > 90 sur *
```

La règle sera appliquée à toutes les machines qui publient `cpu_pct`.

### 6.2 Cibles explicites

Une règle peut être limitée à une ou plusieurs cibles :

```text
targets: ["srv-001", "srv-002"]
```

### 6.3 Exclusions

Une règle peut exclure certaines cibles :

```text
targets: ["*"],
exclude: ["srv-test"]
```

### 6.4 Élément supervisé

Le champ `item` permet d'identifier un sous-composant :

```text
target : srv-001
item   : C:
metric : disk_free_pct
```

ou :

```text
target : srv-001
item   : Spooler
metric : service_fault
```

## 7. Cibles fournies par les modules

| Module | Cibles | Exemples de mesures |
|---|---|---|
| Machines | Toutes les machines ajoutées dans l'onglet Machines | CPU, mémoire, disques, services, accessibilité |
| Docker | Le moteur Docker et chaque container | moteur disponible, moteur figé, container en défaut, CPU, mémoire |
| Réseau | Les équipements de la cartographie qui ont un nom personnalisé | équipement en ligne ou hors ligne |
| Coffre | Le coffre lui-même | secrets arrivés à expiration de rotation |

Pour les machines, une règle CPU s'applique à chaque machine configurée. Pour les disques et les services, la cible est la machine et l'élément précise le disque ou le service.

## 8. Anti-rebond

Lorsqu'une condition devient vraie, l'alerte ne doit pas être déclenchée immédiatement si `for_seconds` est supérieur à zéro.

### Exemple

```text
Condition     : CPU > 90 %
for_seconds   : 300
```

Le CPU doit rester supérieur à 90 % pendant 5 minutes.

Si la valeur repasse sous le seuil avant la fin des 5 minutes :

- l'état d'attente est annulé ;
- aucune alerte n'est créée.

L'état intermédiaire est appelé `pending`.

## 9. Hystérésis

L'hystérésis évite les oscillations autour du seuil.

Pour une règle :

```text
operator   : >
threshold  : 90
hysteresis : 5
```

Le déclenchement se fait au-dessus de 90 %, mais le retour à la normale exige une valeur inférieure ou égale à 85 %.

```text
Déclenchement : valeur > 90
Résolution    : valeur <= 85
```

Pour une règle utilisant `<` :

```text
threshold  : 15
hysteresis : 2
```

La condition se déclenche sous 15 %, mais ne se résout qu'à partir de 17 % ou plus.

## 10. Délai de retour à la normale

Le paramètre `recover_seconds` impose une durée minimale pendant laquelle la valeur doit rester normale avant de résoudre l'alerte.

Exemple :

```text
recover_seconds : 120
```

Une valeur qui repasse brièvement dans la zone normale ne suffit pas à résoudre l'alerte.

## 11. Cycle de vie d'une alerte

Une alerte suit le cycle suivant :

```text
inactive
   ↓ condition vraie
pending
   ↓ for_seconds atteint
firing
   ↓ acquittement
acked
   ↓ condition normale confirmée
resolved
```

Une alerte peut également être :

- silencée par une maintenance ;
- supprimée visuellement par une cause racine ;
- rouverte après une rechute rapide ;
- marquée comme instable en cas d'oscillation répétée.

### 11.1 Déclenchement

Lorsqu'une condition reste vraie assez longtemps :

- une alerte est créée ;
- une identité stable lui est attribuée ;
- un message lisible est généré ;
- un événement `fired` est historisé.

### 11.2 Aggravation

Si la valeur atteint le seuil critique :

- la gravité passe à `critical` ;
- un événement d'aggravation est créé ;
- l'acquittement est retiré.

### 11.3 Résolution

Une alerte est résolue lorsque :

1. la valeur est revenue au-delà du seuil de résolution ;
2. la condition reste normale pendant `recover_seconds`.

Un événement `resolved` est historisé avec :

- la raison ;
- la durée totale ;
- la valeur maximale ou minimale observée.

### 11.4 Réouverture

Si la même condition réapparaît rapidement après résolution :

- l'incident précédent peut être rouvert ;
- le compteur de réouverture est incrémenté ;
- un événement `reopened` est créé.

## 12. Causes racines et dépendances

Certaines alertes sont secondaires à une autre alerte.

Exemple :

```text
Machine injoignable
 ├── CPU non disponible
 ├── mémoire non disponible
 └── services non vérifiables
```

Lorsqu'une alerte racine est active :

- les alertes dépendantes restent enregistrées ;
- elles sont marquées comme supprimées par la cause racine ;
- elles ne sont pas affichées par défaut dans la liste « À traiter » ;
- elles restent accessibles avec l'option d'affichage des alertes dépendantes.

La résolution de la cause racine doit retirer cette suppression.

## 13. Acquittement

Un opérateur peut acquitter une alerte active.

L'acquittement doit demander :

- le nom de l'opérateur ;
- un commentaire ;
- une durée optionnelle.

Exemple :

```text
Opérateur : Hugo
Commentaire : Redémarrage planifié du service à 22 h
Durée     : 2 heures
```

L'acquittement :

- ne résout pas l'alerte ;
- retire l'alerte de la liste des éléments nécessitant une action immédiate ;
- reste visible dans l'alerte et l'historique ;
- expire automatiquement si une durée a été définie.

Une aggravation de la gravité annule automatiquement l'acquittement.

## 14. Maintenance

Une fenêtre de maintenance peut être :

- ponctuelle ;
- quotidienne ;
- hebdomadaire.

Pendant une maintenance :

- les observations continuent d'être collectées ;
- les règles continuent d'être évaluées ;
- les alertes peuvent être déclenchées ;
- les alertes sont silencées dans l'interface ;
- les événements restent historisés.

La maintenance ne doit donc pas supprimer les données ni empêcher la reconstitution de l'incident.

## 15. Interface utilisateur

Le module **Alertes** doit proposer les vues suivantes.

### 15.1 À traiter

Affiche les alertes nécessitant une intervention :

- gravité ;
- cible ;
- message ;
- date de début ;
- durée ;
- état ;
- action d'acquittement.

### 15.2 Historique

Permet de rechercher les alertes selon :

- période ;
- texte ;
- cible ;
- gravité ;
- état ;
- règle ;
- commentaire d'acquittement.

Un export CSV doit être disponible.

### 15.3 Règles

Permet de :

- consulter les règles ;
- créer une règle ;
- modifier une règle ;
- activer ou désactiver une règle ;
- supprimer une règle ;
- voir les cibles concernées ;
- voir le délai avant alerte ;
- voir les seuils et la gravité.

### 15.4 Maintenance

Permet de :

- créer une fenêtre ;
- modifier une fenêtre ;
- supprimer une fenêtre ;
- voir les maintenances actives ;
- limiter la maintenance à certaines cibles.

## 16. Historisation

Les événements suivants doivent être historisés :

- création d'une alerte ;
- réouverture ;
- aggravation ;
- diminution de gravité ;
- acquittement ;
- expiration de l'acquittement ;
- ajout de commentaire ;
- entrée en maintenance ;
- sortie de maintenance ;
- suppression par cause racine ;
- retour à la normale ;
- résolution pour absence de données ;
- suppression ou désactivation de la règle.

L'historique doit être immuable : une modification ultérieure ne doit pas effacer les événements passés.

## 17. Persistance et reprise

Le système doit fonctionner avec :

- SQLite par défaut ;
- MySQL en option.

L'évaluation des alertes ne doit pas dépendre de la disponibilité immédiate de la base.

En cas d'indisponibilité :

1. l'alerte continue d'être évaluée en mémoire ;
2. les opérations sont écrites dans un journal local ;
3. les données sont rejouées lorsque la base redevient accessible ;
4. aucune alerte ne doit être perdue à cause d'une panne temporaire de la base.

Fichiers locaux utilisés :

```text
data\alerts.db
data\alerts_state.json
data\alerts_outbox.jsonl
```

## 18. Règles par défaut

Les règles initiales doivent couvrir au minimum :

| Règle | Métrique |
|---|---|
| Machine injoignable | `reachable` |
| CPU élevé | `cpu_pct` |
| Mémoire élevée | `mem_pct` |
| Espace disque faible | `disk_free_pct` |
| Service en défaut | `service_fault` |
| Container en défaut | `container_fault` |
| Docker indisponible | `docker_available` |
| Équipement réseau hors ligne | `device_online` |
| Moteur Docker lent | `docker_engine_latency_s` |
| Moteur Docker figé | `docker_engine_hung` |

Les règles par défaut doivent être ajoutées une seule fois et ne doivent pas écraser les personnalisations existantes.

## 19. Critères d'acceptation

Le système est considéré conforme si :

1. une règle peut être créée depuis l'interface ;
2. une règle invalide est refusée avec un message explicite ;
3. une règle inactive ne produit aucune alerte ;
4. une règle avec `targets = "*"` s'applique à toutes les cibles compatibles ;
5. une règle avec des cibles explicites ignore les autres cibles ;
6. `for_seconds` empêche les déclenchements ponctuels ;
7. `recover_seconds` empêche les résolutions prématurées ;
8. l'hystérésis empêche les oscillations autour du seuil ;
9. une aggravation retire l'acquittement ;
10. une alerte active apparaît dans « À traiter » ;
11. une alerte résolue apparaît dans l'historique ;
12. les alertes dépendantes sont identifiées ;
13. les alertes de maintenance restent historisées ;
14. les événements sont conservés si la base est indisponible ;
15. une alerte réapparaissant rapidement est correctement rouverte ;
16. les règles par défaut ne sont pas dupliquées après redémarrage.
