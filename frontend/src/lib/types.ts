export type Status = "ok" | "warning" | "critical" | "unknown";
export type Severity = "info" | "ok" | "warning" | "critical";

export interface Health {
  status: Status;
  summary: string;
  stats: { label: string; value: string | number }[];
}

export interface ModuleInfo {
  id: string;
  label: string;
  health: Health;
}

export interface EyeEvent {
  t: number;
  source: string;
  kind: string;
  message: string;
  severity: Severity;
}

export interface Overview {
  modules: ModuleInfo[];
  events: EyeEvent[];
  now: number;
}
