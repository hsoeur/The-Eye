export type Severity = "info" | "warning" | "critical";

export interface Alert {
  id: string; rule_id: string; rule_name: string; source: string; target: string; target_name: string; item: string;
  metric: string; severity: Severity; started_at: number; value: number; peak_value: number; threshold: number;
  operator: string; message: string; state: "firing" | "resolved"; resolved_at: number | null; resolve_reason: string;
  acked: boolean; ack_by: string; ack_comment: string; ack_at: number | null; ack_until: number | null;
  silenced: boolean; silence_name: string; suppressed_by: string | null; flaps: number; notes: number; reopened: number;
  needs_attention: boolean; flapping: boolean;
}

export interface AlertEvent {
  id: string; alert_id: string; t: number; type: string; author: string; comment: string; severity: string;
  value: number | null; data: { ip?: string; until?: number | null };
}

export interface DbStatus {
  type: string; target: string; ok: boolean; loaded: boolean; pending: number; dropped: number; last_error: string; last_ok: number;
}

export interface AlertsStatus { last_eval: number; last_eval_ms: number; interval: number; db: DbStatus; retention_days: number }

export interface Counts { active: number; to_handle: number; critical: number; warning: number; info: number; acked: number; silenced: number; suppressed: number }

export interface Maintenance {
  id: string; name: string; targets: string[]; kind: "once" | "daily" | "weekly"; starts_at: number; ends_at: number;
  days: number[]; start_time: string; duration_min: number; comment: string; enabled: boolean; created_by: string; active?: boolean;
}

export interface AlertsData { alerts: Alert[]; counts: Counts; status: AlertsStatus; maintenance_active: Maintenance[] }

export interface Rule {
  id: string; name: string; metric: string; operator: string; threshold: number; severity: Severity;
  critical_threshold: number | null; for_seconds: number; recover_seconds: number; hysteresis: number;
  source: string; targets: string[]; exclude: string[]; item: string; enabled: boolean; description: string;
}

export interface Catalog { targets: { target: string; name: string }[]; metrics: { metric: string; source: string; unit: string }[] }

export const SEVERITY_LABEL: Record<Severity, string> = { critical: "Critique", warning: "Avertissement", info: "Info" };

export const EVENT_LABEL: Record<string, string> = {
  fired: "Déclenchée", escalated: "Aggravée", deescalated: "Atténuée", acked: "Acquittée", unacked: "Acquittement retiré",
  ack_expired: "Acquittement expiré", comment: "Commentaire", silenced: "Mise en silence (maintenance)",
  unsilenced: "Fin du silence", suppressed: "Masquée (cause racine)", unsuppressed: "Démasquée", resolved: "Résolue", reopened: "Réouverte",
};

export const REASON_LABEL: Record<string, string> = {
  recovered: "Retour à la normale", no_data: "Plus de données", rule_deleted: "Règle supprimée", rule_disabled: "Règle désactivée",
};
