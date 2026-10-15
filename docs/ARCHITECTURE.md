# Architecture de The Eye

## Principes

- **Noyau minimal, modules autonomes** : le noyau (`theeye/core`) ne connaît aucun module ; chaque module backend (`theeye/modules/<id>`) a son pendant frontend (`frontend/src/modules/<id>`), tous deux découverts automatiquement.
- **Backend sans dépendance externe** (Python ≥ 3.9 stdlib). **Frontend** : React 18 + TypeScript + Vite, Tailwind CSS v4, Radix, TanStack Query, React Router, Recharts, React Flow, cmdk, sonner. Le build (`theeye/web`) est commité : aucun Node n'est requis pour exécuter ou déployer.
- **Isolation des pannes** : un module qui plante au chargement/démarrage est désactivé, les autres continuent ; chaque job planifié est protégé.
- **Contrats explicites** plutôt que couplage : routes, événements, santé, `FrontModule`.

```
eye.py                      point d'entrée
theeye/
  app.py                    assemblage (config, bus, scheduler, modules, serveur)
  core/                     config, storage, events, scheduler, process, http, module
  modules/<id>/             backend du module (classe Module, services)
  web/                      build du frontend (généré, servi avec repli SPA)
frontend/                   sources React/TypeScript
  src/app/                  shell : layout, palette Ctrl+K, vue d'ensemble, registre de modules
  src/components/ui/        kit UI (boutons, tables, dialogues, graphiques…)
  src/modules/<id>/         interface du module (index.tsx + Page.tsx)
tests/                      tests unittest
```

## Services du noyau

| Service | Rôle |
|---|---|
| `Settings` | défauts < `data/config.json` < arguments CLI ; config par module via `settings.module(id)` |
| `JsonStore` | persistance JSON atomique, sauvegarde `.corrupt` si fichier illisible |
| `EventBus` | événements `info/ok/warning/critical`, persistés (500 max), `/api/events` |
| `Scheduler` | jobs périodiques sans chevauchement + pool de threads |
| `Runner` | exécution de commandes (PowerShell/ssh) sans jamais lever d'exception |
| `Router`/`Server` | routes `{param}`, JSON, fichiers statiques sécurisés, en-têtes de sécurité |

## Ajouter un module (ex. `printers`)

1. Créer `theeye/modules/printers/__init__.py` :

```python
from ...core.module import Module, Health

class PrintersModule(Module):
    id = "printers"
    label = "Imprimantes"
    order = 40

    def start(self):
        self.ctx.scheduler.every("printers.poll", 30, self.poll)

    def poll(self):
        # ... collecter ...
        self.ctx.emit("toner_low", "Toner bas sur HP-01", "warning")

    def register_routes(self, router):          # monté sous /api/printers
        router.get("/state", lambda req: {"items": []})

    def health(self):
        return Health("ok", "2 imprimantes")
```

2. Créer `frontend/src/modules/printers/index.tsx` (découvert automatiquement) et `Page.tsx` :

```tsx
import { Printer } from "lucide-react";
import { lazy } from "react";
import type { FrontModule } from "@/app/registry";

const mod: FrontModule = { id: "printers", icon: Printer, Page: lazy(() => import("./Page")) };
export default mod;
```

`Page.tsx` exporte par défaut un composant ; il lit `/api/printers/state` via `usePoll`. Ses sous-routes passent par `useParams()["*"]`.

3. `cd frontend; npm run build`, puis redémarrer : navigation, vue d'ensemble, santé, recherche Ctrl+K et événements incluent le module sans autre modification.

## Observations (alimenter le moteur d'alertes)
Un module publie des mesures en surchargeant `Module.observations()` : liste de
`{"target", "target_name", "item", "metric", "value"}` (`source` est ajouté par le gestionnaire ; erreurs isolées).
Le module `alerts` les collecte via `ctx.collect_observations()` et les confronte à ses règles : aucune autre
modification n'est nécessaire pour rendre une nouvelle métrique « alertable ». Le module `alerts` (moteur pur dans
`engine.py`, historique SQL dans `store.py`, écriture différée dans `journal.py`) est décrit dans [ALERTES-MYSQL.md](ALERTES-MYSQL.md).

## Watchdog du moteur Docker

Le module `docker` sépare deux cadences : `docker.watchdog` (sonde légère) et `docker.poll` (inventaire/stats).
- `watchdog.py` : logique pure (états healthy/degraded/hung/recovering, `WatchdogConfig` validée par bornes, `RecoveryGuard`), testée avec horloge injectée.
- `incident.py` : capture des preuves dans `data/incidents/` (étapes isolées, rétention) ; `recovery.py` : relance de Docker Desktop. Toutes les commandes passent par `Runner`.
- `DockerModule` orchestre : événements (`ctx.emit`), observations `docker_engine_*` sur `docker-host`, règles par défaut du module `alerts` (migration unique pour les bases existantes), `Context.peer("alerts").in_maintenance()` pour respecter les fenêtres de maintenance. Détails, seuils et risques de `auto_recover` : section « Watchdog du moteur Docker » du [README](../README.md).

## Ajouter un type de machine supervisée

Ajouter un fichier dans `theeye/modules/machines/collectors/` avec une classe `Collector` décorée `@register`
(`kind`, `label`, `fields`, `collect()`). Le formulaire d'ajout de l'interface est généré depuis `fields`.

## Configuration

`data/config.json` (optionnel) :

```json
{ "modules": { "network": { "scan_interval_min": 30 } }, "disabled_modules": ["docker"] }
```

## Contrat frontend

`FrontModule { id, icon, Page (lazy), search? }` (`frontend/src/app/registry.ts`). La navigation n'affiche que les modules présents dans `/api/modules`. React échappe le contenu par défaut : pas d'injection XSS.

## Développement frontend

`cd frontend; npm install; npm run dev` (http://localhost:5173, proxy `/api` → 8765 ; lancer `python eye.py` à côté). `npm run build` régénère `theeye/web`.

## Tests

`python -m unittest discover -s tests`
