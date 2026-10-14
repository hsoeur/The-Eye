export interface Disk { name: string; total: number; free: number }
export interface Service { name: string; display: string; state: string; start?: string }
export interface Proc { pid: number; name: string; mem: number; cpu: number }
export interface Metrics {
  hostname: string; os: string; uptime_s: number; cpu: number; cores: number; mem_total: number; mem_used: number;
  rx_rate: number; tx_rate: number; nproc: number; disks: Disk[]; ports: (string | number)[];
  services: Service[]; procs: Proc[]; events: { t: string; src: string; msg: string }[];
}
export interface Host {
  id: string; name: string; ip: string; kind: string; ok: boolean | null; error?: string; t_data: number;
  metrics: Metrics | null; history: number[][]; changes: { t: number; msg: string }[]; proc_cpu_unit: "s" | "%";
}
export interface FieldSpec { name: string; label: string; type?: string; placeholder?: string }
export interface MachineType { kind: string; label: string; fields: FieldSpec[] }
export interface MachinesData { hosts: Host[]; types: MachineType[] }

export const isBad = (s: Service) => s.state === "failed" || (s.start === "auto" && s.state !== "running");
