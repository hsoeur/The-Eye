import { ChevronDown, ChevronRight, Container as ContainerIcon, Play, RotateCw, ScrollText, Square, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge, StatusDot, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, KV, Meter, PageHeader, Skeleton } from "@/components/ui/card";
import { TimeChart } from "@/components/ui/charts";
import { Modal, useConfirm } from "@/components/ui/dialog";
import { SearchInput, Select } from "@/components/ui/input";
import { PanelHeader, Row, Split, Table, Td, Th, Toolbar } from "@/components/ui/table";
import { api } from "@/lib/api";
import { level } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";

interface Ctn {
  id: string; name: string; image: string; state: string; status: string; health: string; project: string; ports: string;
  cpu: number; mem_pct: number; mem: string; net: string; blk: string; pids: number; fault: boolean;
}
interface DockerData {
  available: boolean; error?: string; actions: boolean; containers: Ctn[]; history: Record<string, number[][]>;
}

const tone = (c: Ctn): Tone => (c.fault ? "crit" : c.state === "running" ? "ok" : "off");
const FILTERS = { all: "Tous", running: "Actifs", stopped: "Arrêtés", fault: "En défaut" } as const;
type Filter = keyof typeof FILTERS;

export default function DockerPage() {
  const { "*": sel } = useParams();
  const nav = useNavigate();
  const { data, isLoading } = usePoll<DockerData>("/api/docker", 2000);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const selected = data?.containers.find((c) => c.id === sel);

  const groups = useMemo(() => {
    const list = (data?.containers ?? []).filter((c) =>
      (!q || [c.name, c.image, c.project].join(" ").toLowerCase().includes(q.toLowerCase())) &&
      (filter === "all" || (filter === "running" && c.state === "running") || (filter === "stopped" && c.state !== "running") || (filter === "fault" && c.fault)));
    const g = new Map<string, Ctn[]>();
    list.sort((a, b) => a.name.localeCompare(b.name)).forEach((c) => g.set(c.project, [...(g.get(c.project) ?? []), c]));
    return [...g.entries()].sort(([a], [b]) => (a === "" ? 1 : 0) - (b === "" ? 1 : 0) || a.localeCompare(b));
  }, [data, q, filter]);

  if (isLoading) return <div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-64" /></div>;
  if (!data?.available) return <Empty icon={<ContainerIcon />} title="Docker indisponible" hint={data?.error || "Impossible de joindre le moteur Docker. Vérifiez que Docker est démarré et que la commande « docker » est accessible."} />;

  const cs = data.containers, run = cs.filter((c) => c.state === "running").length, bad = cs.filter((c) => c.fault).length;

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-4 px-6 pt-5 pb-3">
        <PageHeader title="Docker" subtitle={`${cs.length} containers · ${run} actifs · ${cs.length - run} arrêtés`}
          actions={bad > 0 && <Badge tone="crit"><TriangleAlert className="size-3" />{bad} en défaut</Badge>} />
      </div>
      <Toolbar>
        <SearchInput className="w-64" placeholder="Rechercher un container, une image…" aria-label="Rechercher" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-36" aria-label="Filtrer par état" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          {Object.entries(FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Toolbar>
      <div className="min-h-0 flex-1">
        <Split
          list={groups.length ? (
            <Table>
              <thead><tr><Th className="w-8" /><Th>Nom</Th><Th>Image</Th><Th>État</Th><Th className="text-right">CPU</Th><Th className="text-right">Mémoire</Th><Th>Ports</Th></tr></thead>
              {groups.map(([project, items]) => {
                const open = !collapsed.has(project);
                const toggle = () => setCollapsed((s) => { const n = new Set(s); open ? n.add(project) : n.delete(project); return n; });
                return (
                  <tbody key={project}>
                    <tr className="cursor-pointer bg-raised/60 hover:bg-raised" onClick={toggle}>
                      <td colSpan={7} className="border-b px-3 py-1.5 text-xs font-medium">
                        <span className="flex items-center gap-1.5">
                          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                          {project || "Hors stack"}
                          <span className="font-normal text-muted">{items.filter((c) => c.state === "running").length}/{items.length} actifs</span>
                          {items.some((c) => c.fault) && <Badge tone="crit">défaut</Badge>}
                        </span>
                      </td>
                    </tr>
                    {open && items.map((c) => {
                      const up = c.state === "running";
                      return (
                        <Row key={c.id} selected={c.id === sel} onClick={() => nav(`/docker/${c.id}`)}>
                          <Td><StatusDot tone={tone(c)} /></Td>
                          <Td className="font-medium">{c.name}</Td>
                          <Td className="max-w-56 truncate text-muted">{c.image}</Td>
                          <Td className="text-muted">{c.status}</Td>
                          <Td className="text-right tabular-nums">{up ? `${c.cpu.toFixed(1)} %` : "—"}</Td>
                          <Td className="text-right tabular-nums">{up ? `${c.mem_pct.toFixed(1)} %` : "—"}</Td>
                          <Td className="max-w-48 truncate text-muted">{c.ports || "—"}</Td>
                        </Row>
                      );
                    })}
                  </tbody>
                );
              })}
            </Table>
          ) : <Empty icon={<ContainerIcon />} title="Aucun container" hint="Aucun container ne correspond aux filtres." />}
          detail={selected && <Detail c={selected} history={data.history[selected.id] ?? []} actions={data.actions} onClose={() => nav("/docker")} />}
        />
      </div>
    </div>
  );
}

function Detail({ c, history, actions, onClose }: { c: Ctn; history: number[][]; actions: boolean; onClose: () => void }) {
  const [logs, setLogs] = useState(false);
  const confirm = useConfirm();
  const qc = useQueryClient();
  const up = c.state === "running";
  const chart = useMemo(() => history.map(([t, cpu, mem]) => ({ t, cpu, mem })), [history]);

  const act = async (action: string, label: string) => {
    if (action !== "start" && !(await confirm({ title: `${label} « ${c.name} » ?`, confirmLabel: label, danger: action === "stop" }))) return;
    try {
      await api.post("/api/docker/action", { id: c.id, action });
      toast.success(`${label} : demandé`);
      qc.invalidateQueries({ queryKey: ["/api/docker"] });
    } catch (e) { toast.error((e as Error).message); }
  };

  return (
    <>
      <PanelHeader title={<span className="flex items-center gap-2"><StatusDot tone={tone(c)} />{c.name}</span>} subtitle={c.image} onClose={onClose} />
      <div className="space-y-5 p-4">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setLogs(true)}><ScrollText className="size-3.5" />Logs</Button>
          {actions && (up
            ? <><Button onClick={() => act("restart", "Redémarrer")}><RotateCw className="size-3.5" />Redémarrer</Button>
                <Button variant="danger" onClick={() => act("stop", "Arrêter")}><Square className="size-3.5" />Arrêter</Button></>
            : <Button variant="primary" onClick={() => act("start", "Démarrer")}><Play className="size-3.5" />Démarrer</Button>)}
        </div>
        {up && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div><div className="mb-1 flex justify-between text-xs text-muted"><span>CPU</span><b className="text-fg">{c.cpu.toFixed(1)} %</b></div><Meter value={c.cpu} tone={level(c.cpu)} /></div>
              <div><div className="mb-1 flex justify-between text-xs text-muted"><span>Mémoire</span><b className="text-fg">{c.mem_pct.toFixed(1)} %</b></div><Meter value={c.mem_pct} tone={level(c.mem_pct)} /></div>
            </div>
            <TimeChart data={chart} max={100} format={(v) => `${v.toFixed(0)}%`}
              series={[{ key: "cpu", label: "CPU", color: "var(--accent)" }, { key: "mem", label: "Mémoire", color: "var(--warn)" }]} />
            <div className="flex gap-4 text-xs text-muted"><span className="flex items-center gap-1.5"><i className="size-2 rounded-full bg-accent" />CPU</span><span className="flex items-center gap-1.5"><i className="size-2 rounded-full bg-warn" />Mémoire</span></div>
          </div>
        )}
        <KV rows={[["État", c.status], ["Santé", c.health || "—"], ["Stack", c.project || "—"], ["Ports", c.ports || "—"],
          ...(up ? ([["Mémoire", c.mem], ["Réseau", c.net], ["Disque", c.blk], ["Processus", String(c.pids)]] as [string, string][]) : []), ["Identifiant", c.id]]} />
      </div>
      {logs && <LogsModal c={c} onClose={() => setLogs(false)} />}
    </>
  );
}

function LogsModal({ c, onClose }: { c: Ctn; onClose: () => void }) {
  const { data } = usePoll<{ logs: string }>(`/api/docker/logs?id=${c.id}`, 3000);
  const ref = useRef<HTMLPreElement>(null);
  const stick = useRef(true);
  useEffect(() => { if (stick.current && ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [data]);
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Logs — ${c.name}`} description="Actualisé toutes les 3 secondes" wide>
      <pre ref={ref} onScroll={(e) => { const t = e.currentTarget; stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < 40; }}
        className="h-[52vh] overflow-auto whitespace-pre-wrap break-all rounded-md border bg-bg p-3 font-mono text-xs leading-relaxed">
        {data ? data.logs || "(vide)" : "Chargement…"}
      </pre>
    </Modal>
  );
}
