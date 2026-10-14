import { List, Map as MapIcon, Radar, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, KV, PageHeader, Skeleton } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/dialog";
import { Field, Input, SearchInput, Select } from "@/components/ui/input";
import { PanelHeader, Row, Split, Table, Td, Th, Toolbar } from "@/components/ui/table";
import { api } from "@/lib/api";
import { ago, dateTime, ipNum } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { cn } from "@/lib/utils";
import { NetworkMap } from "./NetworkMap";
import { TYPES, nameOf, typeInfo, type Device, type NetState } from "./devices";

export default function NetworkPage() {
  const { "*": sel } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data, isLoading } = usePoll<NetState>("/api/network/state", 2000);
  const [view, setView] = useState<"map" | "list">("map");
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [offline, setOffline] = useState(true);
  const [cidr, setCidr] = useState("");

  const all = useMemo(() => Object.values(data?.devices ?? {}), [data]);
  const visible = useMemo(() => all.filter((d) => (offline || d.online) && (!type || d.type === type) &&
    (!q || [d.ip, d.hostname, d.label, d.vendor, d.mac, typeInfo(d.type).label].join(" ").toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => ipNum(a.ip) - ipNum(b.ip)), [all, q, type, offline]);
  const selected = sel ? data?.devices[sel] : undefined;
  const types = useMemo(() => [...new Set(all.map((d) => d.type))].sort(), [all]);

  if (isLoading || !data) return <div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-96" /></div>;

  const on = all.filter((d) => d.online).length, fresh = all.filter((d) => d.new).length;
  const p = data.progress;
  const scan = async () => {
    try {
      await api.post("/api/network/scan", { cidrs: cidr.split(/[ ,;]+/).filter(Boolean) });
      qc.invalidateQueries({ queryKey: ["/api/network/state"] });
    } catch (e) { toast.error((e as Error).message); }
  };
  const select = (ip: string | null) => nav(ip ? `/network/${ip}` : "/network");

  return (
    <div className="flex h-full flex-col">
      <div className="px-6 pt-5 pb-3">
        <PageHeader title="Réseau" subtitle={`${all.length} équipements · ${on} en ligne · ${all.length - on} hors ligne`}
          actions={<>
            {fresh > 0 && <Badge tone="warn">{fresh} nouveau{fresh > 1 ? "x" : ""}</Badge>}
            <Input className="w-56" placeholder="Plages à scanner (auto)" aria-label="Plages à scanner" value={cidr} onChange={(e) => setCidr(e.target.value)} />
            <Button variant="primary" onClick={scan} disabled={p.running}><Radar className={cn("size-3.5", p.running && "animate-spin")} />
              {p.running ? `${p.phase} ${p.done}/${p.total}` : "Scanner"}</Button>
          </>} />
      </div>
      <div className={cn("h-0.5 bg-transparent", p.running && "bg-raised")}><div className="h-full bg-accent transition-[width] duration-500" style={{ width: p.running && p.total ? `${(100 * p.done) / p.total}%` : 0 }} /></div>
      <Toolbar>
        <SearchInput className="w-64" placeholder="IP, nom, fabricant, MAC…" aria-label="Rechercher" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-44" aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Tous les types</option>{types.map((t) => <option key={t} value={t}>{typeInfo(t).label}</option>)}
        </Select>
        <label className="flex items-center gap-2 text-[13px] text-muted"><input type="checkbox" className="accent-[var(--accent)]" checked={offline} onChange={(e) => setOffline(e.target.checked)} />Hors ligne</label>
        <div role="group" aria-label="Affichage" className="ml-auto flex rounded-md border p-0.5">
          {([["map", MapIcon, "Carte"], ["list", List, "Liste"]] as const).map(([id, Icon, label]) => (
            <button key={id} onClick={() => setView(id)} aria-pressed={view === id} className={cn("flex h-6 items-center gap-1.5 rounded px-2 text-xs font-medium text-muted", view === id && "bg-raised text-fg")}>
              <Icon className="size-3.5" />{label}
            </button>
          ))}
        </div>
      </Toolbar>
      <div className="min-h-0 flex-1">
        <Split
          list={!all.length ? (
            <Empty icon={<Radar />} title="Aucun équipement découvert" hint="Lancez un scan pour cartographier automatiquement votre réseau." action={<Button variant="primary" onClick={scan}>Scanner le réseau</Button>} />
          ) : !visible.length ? <Empty title="Aucun résultat" hint="Aucun équipement ne correspond aux filtres." />
          : view === "map" ? <div className="h-full min-h-[420px]"><NetworkMap devices={visible} subnets={data.subnets} selected={sel} onSelect={select} /></div>
          : <DeviceTable rows={visible} sel={sel} now={data.now} onSelect={select} />}
          detail={selected && <DeviceDetail key={selected.ip} d={selected} ports={data.ports} now={data.now} onClose={() => select(null)} />}
        />
      </div>
    </div>
  );
}

function DeviceTable({ rows, sel, now, onSelect }: { rows: Device[]; sel?: string; now: number; onSelect: (ip: string) => void }) {
  return (
    <Table>
      <thead><tr><Th className="w-8" /><Th>Nom</Th><Th>Adresse IP</Th><Th>Type</Th><Th>Fabricant</Th><Th>Ports</Th><Th>Dernière vue</Th></tr></thead>
      <tbody>
        {rows.map((d) => {
          const Icon = typeInfo(d.type).icon;
          return (
            <Row key={d.ip} selected={d.ip === sel} onClick={() => onSelect(d.ip)}>
              <Td><StatusDot tone={d.online ? "ok" : "off"} /></Td>
              <Td className="font-medium">{nameOf(d)}{d.new && <Badge tone="warn" className="ml-2">nouveau</Badge>}</Td>
              <Td className="font-mono text-xs text-muted">{d.ip}</Td>
              <Td><span className="flex items-center gap-1.5 text-muted"><Icon className="size-3.5" />{typeInfo(d.type).label}</span></Td>
              <Td className="max-w-48 truncate text-muted">{d.vendor || "—"}</Td>
              <Td className="max-w-40 truncate font-mono text-xs text-muted">{(d.ports ?? []).join(", ") || "—"}</Td>
              <Td className="text-muted">{ago(d.last_seen, now)}</Td>
            </Row>
          );
        })}
      </tbody>
    </Table>
  );
}

function DeviceDetail({ d, ports, now, onClose }: { d: Device; ports: Record<string, string>; now: number; onClose: () => void }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [label, setLabel] = useState(d.label ?? "");
  const [type, setType] = useState(d.type);
  const dirty = label !== (d.label ?? "") || type !== d.type;
  const refresh = () => qc.invalidateQueries({ queryKey: ["/api/network/state"] });

  const save = async () => {
    try { await api.post("/api/network/device", { ip: d.ip, label, type }); toast.success("Enregistré"); refresh(); }
    catch (e) { toast.error((e as Error).message); }
  };
  const forget = async () => {
    if (!(await confirm({ title: `Oublier « ${nameOf(d)} » ?`, description: "L'équipement réapparaîtra au prochain scan s'il est présent.", confirmLabel: "Oublier", danger: true }))) return;
    await api.post("/api/network/forget", { ip: d.ip });
    onClose(); refresh();
  };

  return (
    <>
      <PanelHeader title={<span className="flex items-center gap-2"><StatusDot tone={d.online ? "ok" : "off"} />{nameOf(d)}</span>}
        subtitle={`${d.online ? "En ligne" : "Hors ligne"}${d.is_self ? " · cette machine" : ""}${d.is_gateway ? " · passerelle" : ""}`} onClose={onClose} />
      <div className="space-y-5 p-4">
        <KV rows={[["Adresse IP", d.ip], ["MAC", d.mac || "—"], ["Fabricant", d.vendor || "inconnu"], ["Nom d'hôte", d.hostname || "—"], ["TTL", String(d.ttl ?? "—")],
          ["Première vue", dateTime(d.first_seen)], ["Dernière vue", ago(d.last_seen, now)]]} />
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Ports ouverts</h3>
          <div className="flex flex-wrap gap-1.5">
            {d.ports?.length ? d.ports.map((p) => <Badge key={p} className="font-mono">{p}{ports[p] ? ` · ${ports[p]}` : ""}</Badge>) : <span className="text-[13px] text-muted">Aucun</span>}
          </div>
        </div>
        <div className="grid gap-3 border-t pt-4">
          <Field label="Nom personnalisé"><Input value={label} maxLength={80} placeholder={d.hostname || d.ip} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="Type d'équipement">
            <Select value={type} onChange={(e) => setType(e.target.value)}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
          </Field>
          <div className="flex gap-2">
            <Button variant="primary" onClick={save} disabled={!dirty}>Enregistrer</Button>
            <Button variant="danger" onClick={forget} className="ml-auto"><Trash2 className="size-3.5" />Oublier</Button>
          </div>
        </div>
      </div>
    </>
  );
}
