# Architecture de The Eye

## Principes

- **Noyau minimal, modules autonomes** : le noyau (`theeye/core`) ne connaît aucun module ; chaque module (`theeye/modules/<id>`) embarque son backend **et** son interface.
- **Aucune dépendance externe** (Python ≥ 3.9 stdlib uniquement, JS natif sans build).
- **Isolation des pannes** : un module qui plante au chargement/démarrage est désactivé, les autres continuent ; chaque job planifié est protégé.
- **Contrats explicites** plutôt que couplage : routes, événements, santé, vue web.

```
eye.py                      point d'entrée
theeye/
  app.py                    assemblage (config, bus, scheduler, modules, serveur)
  core/                     config, storage, events, scheduler, process, http, module
  modules/<id>/
    __init__.py             classe Module (contrat)
    service.py ...          logique métier
    web/view.js             interface du module
  web/                      shell (nav, routeur, thème) + boîte à outils UI
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

2. Créer `theeye/modules/printers/web/view.js` :

```js
import { h, render } from "/js/core/dom.js";
export default { mount(el, ctx) { render(el, h("p", null, "Imprimantes")); return ctx.poll(async () => { /* api */ }, 5000); } };
```

3. Redémarrer : le module est **découvert automatiquement** ; navigation, vue d'ensemble, santé et événements l'incluent sans autre modification.

## Ajouter un type de machine supervisée

Ajouter un fichier dans `theeye/modules/machines/collectors/` avec une classe `Collector` décorée `@register`
(`kind`, `label`, `fields`, `collect()`). Le formulaire d'ajout de l'interface est généré depuis `fields`.

## Configuration

`data/config.json` (optionnel) :

```json
{ "modules": { "network": { "scan_interval_min": 30 } }, "disabled_modules": ["docker"] }
```

## Contrat frontend

`export default { mount(el, ctx) → cleanup }` ; `ctx` = `{ api, sub, navigate, toast, modules, poll(fn, ms), onRoute(fn) }`.
Le DOM est construit avec `h()` (pas d'`innerHTML`) : pas d'injection XSS.

## Tests

`python -m unittest discover -s tests`
