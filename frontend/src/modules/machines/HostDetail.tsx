import { ArrowLeft, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Empty, Meter } from "@/components/ui/card";
import { TimeChart } from "@/components/ui/charts";
import { SearchInput, Select } from "@/components/ui/input";
import { Row, Table, Td, Th } from "@/components/ui/table";
import { Tab, TabList, TabPanel, Tabs } from "@/components/ui/tabs";
import { ago, bytes, dateTime, level, uptime } from "@/lib/format";
import { isBad, type Host, type MachineType, type Service } from "./types";

export function HostDetail({ host: h, types, onBack, onRemove }: { host: Host; types: MachineType[]; onBack: () => void; onRemove: () => void }) {
  const m = h.metrics;
  const badServices = m?.services.filter(isBad).length ?? 0;
  return (
    <div className="min-h-0 flex-1 overflow-auto border-t">
      <div className="mx-auto max-w-6xl space-y-5 p-6">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" onClick={onBack} aria-label="Retour à la liste"><ArrowLeft className="size-4" /></Button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5"><StatusDot tone={h.ok === false ? "crit" : h.ok ? "ok" : "off"} /><h2 className="truncate text-lg font-semibold tracking-tight">{h.name}</h2>
              <span className="text-[13px] text-muted">{h.ip}</span></div>
            <p className="mt-0.5 text-[13px] text-muted">
              {types.find((t) => t.kind === h.kind)?.label ?? h.kind}
              {m && ` · ${m.os} · disponibilité ${uptime(m.uptime_s)} · mesure ${ago(h.t_data)}`}
            </p>
          </div>
          <Button variant="danger" onClick={onRemove}><Trash2 className="size-3.5" />Retirer</Button>
        </div>
        {h.ok === false && (
          <div role="alert" className="rounded-card border border-crit/30 bg-crit/8 px-4 py-3 text-[13px] text-crit">
            <b>Machine injoignable.</b> {h.error}
          </div>
        )}
        <Tabs defaultValue="summary">
          <TabList>
            <Tab value="summary">Résumé</Tab>
            <Tab value="services" count={badServices}>Services</Tab>
            <Tab value="procs">Processus</Tab>
            <Tab value="events">Journal</Tab>
          </TabList>
          <TabPanel value="summary"><Summary h={h} /></TabPanel>
          <TabPanel value="services"><Services services={m?.services ?? []} /></TabPanel>
          <TabPanel value="procs"><Procs h={h} /></TabPanel>
          <TabPanel value="events"><Events h={h} /></TabPanel>
        </Tabs>
      </div>
    </div>
  );
}

function Gauge({ title, value, sub, data, dataKey, color }: { title: string; value: number; sub: string; data: object[]; dataKey: string; color: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{title}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value.toFixed(1)} %</div>
      <div className="mt-2"><Meter value={value} tone={level(value)} /></div>
      <div className="mt-1.5 text-xs text-muted">{sub}</div>
      <div className="-mx-1 mt-2"><TimeChart data={data as Record<string, number>[]} series={[{ key: dataKey, label: title, color }]} max={100} height={80} format={(v) => `${v.toFixed(0)}%`} /></div>
    </Card>
  );
}

function Summary({ h }: { h: Host }) {
  const m = h.metrics;
  const data = useMemo(() => h.history.map(([t, cpu, mem, rx, tx]) => ({ t, cpu, mem, rx, tx })), [h.history]);
  if (!m) return <Empty title={h.ok === false ? "Aucune mesure disponible" : "Première mesure en cours…"} />;
  const mem = m.mem_total ? (100 * m.mem_used) / m.mem_total : 0;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Gauge title="Processeur" value={m.cpu} sub={`${m.cores} cœurs · ${m.nproc} processus`} data={data} dataKey="cpu" color="var(--accent)" />
        <Gauge title="Mémoire" value={mem} sub={`${bytes(m.mem_used)} / ${bytes(m.mem_total)}`} data={data} dataKey="mem" color="var(--warn)" />
        <Card className="p-4">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">Réseau</div>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <div><div className="text-xl font-semibold tabular-nums">{bytes(m.rx_rate)}/s</div><div className="text-xs text-muted">Réception</div></div>
            <div><div className="text-xl font-semibold tabular-nums">{bytes(m.tx_rate)}/s</div><div className="text-xs text-muted">Émission</div></div>
          </div>
          <div className="-mx-1 mt-[3.4rem]"><TimeChart data={data} series={[{ key: "rx", label: "Réception", color: "var(--accent)" }, { key: "tx", label: "Émission", color: "var(--ok)" }]} height={80} format={(v) => bytes(v)} /></div>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Disques" />
          <div className="space-y-3 p-4">
            {m.disks.length ? m.disks.map((d) => {
              const used = 100 * (1 - d.free / (d.total || 1));
              return (
                <div key={d.name}>
                  <div className="mb-1 flex justify-between text-[13px]"><span className="font-medium">{d.name}</span>
                    <span className="text-muted">{bytes(d.total - d.free)} / {bytes(d.total)} · {used.toFixed(0)} %</span></div>
                  <Meter value={used} tone={level(used)} />
                </div>
              );
            }) : <span className="text-[13px] text-muted">—</span>}
          </div>
        </Card>
        <Card>
          <CardHeader title="Ports en écoute" />
          <div className="flex flex-wrap gap-1.5 p-4">
            {m.ports.length ? m.ports.map((p) => <Badge key={p} className="font-mono">{p}</Badge>) : <span className="text-[13px] text-muted">—</span>}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Services({ services }: { services: Service[] }) {
  const [q, setQ] = useState("");
  const [only, setOnly] = useState("all");
  const rows = services
    .filter((s) => (!q || (s.name + s.display).toLowerCase().includes(q.toLowerCase())) &&
      (only === "all" || (only === "bad" ? isBad(s) : only === "running" ? s.state === "running" : s.state !== "running")))
    .sort((a, b) => Number(isBad(b)) - Number(isBad(a)) || a.name.localeCompare(b.name));
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <SearchInput className="w-64" placeholder="Filtrer les services" aria-label="Filtrer les services" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="w-36" aria-label="État" value={only} onChange={(e) => setOnly(e.target.value)}>
          <option value="all">Tous</option><option value="running">Actifs</option><option value="stopped">Arrêtés</option><option value="bad">En défaut</option>
        </Select>
        <span className="ml-auto self-center text-xs text-muted">{rows.length} service{rows.length > 1 ? "s" : ""}</span>
      </div>
      <Card className="overflow-hidden">
        {rows.length ? (
          <Table>
            <thead><tr><Th className="w-8" /><Th>Service</Th><Th>Nom affiché</Th><Th>État</Th><Th>Démarrage</Th></tr></thead>
            <tbody>
              {rows.slice(0, 500).map((s) => (
                <Row key={s.name}>
                  <Td><StatusDot tone={s.state === "running" ? "ok" : isBad(s) ? "crit" : "off"} /></Td>
                  <Td className="font-medium">{s.name}</Td><Td className="max-w-72 truncate text-muted">{s.display}</Td>
                  <Td>{isBad(s) ? <Badge tone="crit">{s.state}</Badge> : <span className="text-muted">{s.state}</span>}</Td>
                  <Td className="text-muted">{s.start || "—"}</Td>
                </Row>
              ))}
            </tbody>
          </Table>
        ) : <Empty title="Aucun service" hint="Aucun service ne correspond au filtre." />}
      </Card>
    </div>
  );
}

function Procs({ h }: { h: Host }) {
  const procs = h.metrics?.procs ?? [];
  if (!procs.length) return <Empty title="Aucune mesure" />;
  return (
    <Card className="overflow-hidden">
      <Table>
        <thead><tr><Th>PID</Th><Th>Nom</Th><Th className="text-right">Mémoire</Th><Th className="text-right">{h.proc_cpu_unit === "s" ? "Temps CPU" : "CPU"}</Th></tr></thead>
        <tbody>
          {procs.map((p) => (
            <Row key={p.pid}>
              <Td className="font-mono text-muted">{p.pid}</Td><Td className="font-medium">{p.name}</Td>
              <Td className="text-right tabular-nums">{bytes(p.mem)}</Td>
              <Td className="text-right tabular-nums">{h.proc_cpu_unit === "s" ? `${p.cpu.toFixed(0)} s` : `${p.cpu} %`}</Td>
            </Row>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

function Events({ h }: { h: Host }) {
  const changes = [...h.changes].reverse();
  const errors = h.metrics?.events ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Changements détectés" />
        {changes.length ? (
          <ul className="mt-2 divide-y pb-1">{changes.map((c, i) => (
            <li key={i} className="flex gap-3 px-4 py-2 text-[13px]"><span className="w-28 shrink-0 text-xs text-faint">{dateTime(c.t)}</span>{c.msg}</li>))}</ul>
        ) : <p className="p-4 text-[13px] text-muted">Aucun changement pour le moment.</p>}
      </Card>
      <Card>
        <CardHeader title="Erreurs récentes des journaux système" />
        {errors.length ? (
          <ul className="mt-2 divide-y pb-1">{errors.map((e, i) => (
            <li key={i} className="px-4 py-2 text-[13px]"><div className="flex gap-2 text-xs text-faint"><span>{String(e.t).replace("T", " ").slice(0, 19)}</span><b className="text-muted">{e.src}</b></div><div className="mt-0.5">{e.msg}</div></li>))}</ul>
        ) : <p className="p-4 text-[13px] text-ok">Aucune erreur.</p>}
      </Card>
    </div>
  );
}
