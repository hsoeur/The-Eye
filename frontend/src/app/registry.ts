import type { ComponentType, LazyExoticComponent } from "react";
import type { LucideIcon } from "lucide-react";

export interface SearchItem { id: string; label: string; hint?: string; to: string }

/**
 * Contrat d'un module côté interface. Un module = un dossier `src/modules/<id>/index.tsx`
 * qui exporte par défaut un `FrontModule` ; il est découvert automatiquement (aucune autre modification).
 * L'`id` doit correspondre à celui du module backend : la navigation n'affiche que les modules actifs.
 */
export interface FrontModule {
  id: string;
  icon: LucideIcon;
  /** Page chargée à la demande ; gère ses propres sous-routes via useParams()["*"]. */
  Page: LazyExoticComponent<ComponentType>;
  /** Alimente la recherche globale (Ctrl+K) avec les éléments du module. */
  search?: { url: string; items: (data: any) => SearchItem[] };
}

const found = import.meta.glob<{ default: FrontModule }>("../modules/*/index.tsx", { eager: true });

export const frontModules: FrontModule[] = Object.values(found).map((m) => m.default);
export const frontModule = (id: string) => frontModules.find((m) => m.id === id);
