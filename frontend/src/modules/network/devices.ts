import { Boxes, Cpu, Database, Globe, HelpCircle, Monitor, Network, Printer, Radio, Router, Server, Terminal, type LucideIcon } from "lucide-react";

export interface Device {
  ip: string; mac?: string; vendor?: string; hostname?: string; label?: string; type: string; ttl?: number;
  online: boolean; new?: boolean; is_gateway?: boolean; is_self?: boolean; first_seen: number; last_seen: number; ports?: number[];
}
export interface NetState {
  devices: Record<string, Device>; subnets: string[]; ports: Record<string, string>; now: number;
  progress: { running: boolean; total: number; done: number; phase: string };
}

export const TYPES: Record<string, { label: string; icon: LucideIcon }> = {
  router: { label: "Routeur", icon: Router },
  switch: { label: "Switch", icon: Network },
  server: { label: "Serveur", icon: Server },
  windows: { label: "Windows", icon: Monitor },
  linux: { label: "Linux", icon: Terminal },
  printer: { label: "Imprimante", icon: Printer },
  plc: { label: "Automate", icon: Cpu },
  vm: { label: "Machine virtuelle", icon: Boxes },
  database: { label: "Base de données", icon: Database },
  web: { label: "Web", icon: Globe },
  iot: { label: "IoT", icon: Radio },
  unknown: { label: "Inconnu", icon: HelpCircle },
};

export const typeInfo = (t: string) => TYPES[t] ?? TYPES.unknown;
export const nameOf = (d: Device) => d.label || d.hostname || d.ip;

const num = (s: string) => s.split(".").reduce((x, y) => x * 256 + +y, 0);
export const inNet = (ip: string, cidr: string) => {
  const [base, bits] = cidr.split("/");
  const mask = +bits ? (~0 << (32 - +bits)) >>> 0 : 0;
  return ((num(ip) & mask) >>> 0) === ((num(base) & mask) >>> 0);
};
