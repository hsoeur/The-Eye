import { useState } from "react";
import { Badge, type Tone } from "@/components/ui/badge";
import type { Alert, Severity } from "./types";
import { SEVERITY_LABEL } from "./types";

export const sevTone = (s: Severity): Tone => (s === "critical" ? "crit" : s === "warning" ? "warn" : "info");

export const SevBadge = ({ s }: { s: Severity }) => <Badge tone={sevTone(s)}>{SEVERITY_LABEL[s]}</Badge>;

/** Nom de l'opérateur mémorisé dans le navigateur (pas d'authentification pour l'instant). */
export function useAuthor(): [string, (v: string) => void] {
  const [author, set] = useState(() => localStorage.getItem("eye.author") ?? "");
  return [author, (v) => { localStorage.setItem("eye.author", v); set(v); }];
}

export const itemLabel = (a: Pick<Alert, "target_name" | "item">) => (a.item ? `${a.target_name} · ${a.item}` : a.target_name);

export const duration = (s: number): string => {
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${(s / 3600).toFixed(1).replace(".0", "")} h`;
  return `${(s / 86400).toFixed(1).replace(".0", "")} j`;
};

export function StateBadges({ a }: { a: Alert }) {
  return (
    <>
      {a.state === "resolved" && <Badge tone="ok">résolue</Badge>}
      {a.acked && <Badge tone="info">acquittée</Badge>}
      {a.silenced && <Badge tone="off">maintenance</Badge>}
      {a.suppressed_by && <Badge tone="off">dépendante</Badge>}
      {a.flapping && <Badge tone="warn">instable</Badge>}
    </>
  );
}
