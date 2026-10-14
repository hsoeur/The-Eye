import { BellOff, CheckCircle2, Download, Wrench } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, PageHeader, Skeleton } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Row, Table, Td, Th, Toolbar } from "@/components/ui/table";
import { Tab, TabList, TabPanel, Tabs } from "@/components/ui/tabs";
import { ago, dateTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { AlertDetail, ActionDialog } from "./AlertDetail";
import { MaintenanceTab } from "./MaintenanceTab";
import { RulesTab } from "./RulesTab";
import { duration, itemLabel, SevBadge, StateBadges } from "./shared";
import type { Alert, AlertsData } from "./types";

export default function AlertsPage() {
  const { "*": sel } = useParams();
  const nav = useNavigate();
  const [tab, setTab] = useState("active");
  const { data, isLoading } = usePoll<AlertsData>("/api/alerts", 5000);
  if (isLoading) return <div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-64" /></div>;
  const c = data?.counts;

  return (
    <div className="flex h-full flex-col">
      <div className="px-6 pt-5 pb-2">
        <PageHeader title="Alertes" subtitle={c ? `${c.to_handle} à traiter · ${c.acked} acquittée(s) · ${c.silenced} en maintenance · ${c.suppressed} dépendante(s)` : ""} />
        {data && <StatusLine data={data} />}
      </div>
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <div className="px-6"><TabList>
          <Tab value="active" count={c?.to_handle}>À traiter</Tab>
          <Tab value="history">Historique</Tab>
          <Tab value="rules">Règles</Tab>
          <Tab value="maintenance">Maintenance</Tab>
        </TabList></div>
        <div className="min-h-0 flex-1 overflow-auto">
          <TabPanel value="active"><ActiveList alerts={data?.alerts ?? []} onOpen={(a) => nav(`/alerts/${a.id}`)} /></TabPanel>
          <TabPanel value="history"><History onOpen={(a) => nav(`/alerts/${a.id}`)} /></TabPanel>
          <TabPanel value="rules"><div className="px-6 pb-6"><RulesTab /></div></TabPanel>
          <TabPanel value="maintenance"><div className="px-6 pb-6"><MaintenanceTab /></div></TabPanel>
        </div>
      </Tabs>
      {sel && <AlertDetail id={sel} onClose={() => nav("/alerts")} />}
    </div>
  );
}

function StatusLine({ data }: { data: AlertsData }) {
  const s = data.status, late = s.last_eval && Date.now() / 1000 - s.last_eval > s.interval * 4;
  return (
    <div className="mt-2 space-y-1.5 text-xs text-muted">
      <div>Dernière évaluation {s.last_eval ? ago(s.last_eval) : "—"} (toutes les {s.interval} s) · base {s.db.type} {s.db.ok ? "connectée" : "indisponible"}</div>
      {late && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">La supervision n'a pas évalué les alertes depuis {ago(s.last_eval).replace("il y a ", "")} : les informations affichées peuvent être périmées.</p>}
      {!s.db.ok && <p role="alert" className="rounded-md bg-warn/12 px-3 py-2 text-[13px] text-warn">Base d'historique indisponible{s.db.last_error ? ` (${s.db.last_error})` : ""} — {s.db.pending} opération(s) en attente, rien n'est perdu.</p>}
      {data.maintenance_active.length > 0 && <p className="flex items-center gap-1.5 text-[13px]"><Wrench className="size-3.5" />Maintenance en cours : {data.maintenance_active.map((m) => m.name).join(", ")}</p>}
    </div>
  );
}

function ActiveList({ alerts, onOpen }: { alerts: Alert[]; onOpen: (a: Alert) => void }) {
  const [showAll, setShowAll] = useState(false);
  const [ack, setAck] = useState<Alert | null>(null);
  const rows = showAll ? alerts : alerts.filter((a) => !a.suppressed_by);
  const hidden = alerts.length - alerts.filter((a) => !a.suppressed_by).length;
  if (!alerts.length) return <Empty icon={<CheckCircle2 />} title="Aucune alerte active" hint="Tout est dans les seuils définis." />;
  return (
    <>
      {hidden > 0 && <Toolbar><label className="flex items-center gap-2 text-[13px] text-muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />Afficher les {hidden} alerte(s) dépendante(s) d'une cause déjà signalée</label></Toolbar>}
      <Table>
        <thead><tr><Th>Gravité</Th><Th>Cible</Th><Th>Alerte</Th><Th>Depuis</Th><Th>État</Th><Th className="w-28" /></tr></thead>
        <tbody>
          {rows.map((a) => (
            <Row key={a.id} onClick={() => onOpen(a)} className={a.needs_attention ? "" : "opacity-60"}>
              <Td><SevBadge s={a.severity} /></Td>
              <Td className="font-medium">{itemLabel(a)}</Td>
              <Td className="max-w-md truncate">{a.message}</Td>
              <Td className="text-muted" title={dateTime(a.started_at)}>{duration(Date.now() / 1000 - a.started_at)}</Td>
              <Td className="space-x-1"><StateBadges a={a} />{a.acked && <span className="text-xs text-muted">{a.ack_by}</span>}</Td>
              <Td onClick={(e) => e.stopPropagation()}>{!a.acked && <Button size="sm" onClick={() => setAck(a)}><BellOff className="size-3.5" />Acquitter</Button>}</Td>
            </Row>
          ))}
        </tbody>
      </Table>
      {ack && <ActionDialog alert={ack} mode="ack" onClose={() => setAck(null)} />}
    </>
  );
}

const PERIODS: [string, number][] = [["24 heures", 1], ["7 jours", 7], ["30 jours", 30], ["1 an", 365]];

function History({ onOpen }: { onOpen: (a: Alert) => void }) {
  const [q, setQ] = useState(""), [state, setState] = useState(""), [severity, setSeverity] = useState(""), [days, setDays] = useState(7);
  const [page, setPage] = useState(0);
  const size = 50;
  const since = Math.floor(Date.now() / 1000 / 60) * 60 - days * 86400;
  const params = new URLSearchParams({ since: String(since) });
  if (q) params.set("q", q);
  if (state) params.set("state", state);
  if (severity) params.set("severity", severity);
  const { data, isError, error } = usePoll<{ alerts: Alert[]; total: number }>(`/api/alerts/history?${params}&limit=${size}&offset=${page * size}`, 15000);
  const reset = <T,>(f: (v: T) => void) => (v: T) => { f(v); setPage(0); };

  return (
    <>
      <Toolbar>
        <Input className="w-64" type="search" placeholder="Rechercher (message, machine, commentaire…)" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        <Select className="w-36" value={state} onChange={(e) => reset(setState)(e.target.value)}><option value="">Tous états</option><option value="firing">En cours</option><option value="resolved">Résolues</option></Select>
        <Select className="w-44" value={severity} onChange={(e) => reset(setSeverity)(e.target.value)}><option value="">Toutes gravités</option><option value="critical">Critique</option><option value="warning">Avertissement</option><option value="info">Info</option></Select>
        <Select className="w-32" value={days} onChange={(e) => reset(setDays)(+e.target.value)}>{PERIODS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}</Select>
        <a className="ml-auto" href={`/api/alerts/export.csv?${params}`}><Button><Download className="size-3.5" />Export CSV</Button></a>
      </Toolbar>
      {isError ? <p className="p-6 text-[13px] text-crit">{(error as Error)?.message}</p> : (
        <>
          <Table>
            <thead><tr><Th>Début</Th><Th>Gravité</Th><Th>Cible</Th><Th>Alerte</Th><Th>Durée</Th><Th>État</Th><Th>Acquittement</Th></tr></thead>
            <tbody>
              {(data?.alerts ?? []).map((a) => (
                <Row key={a.id} onClick={() => onOpen(a)}>
                  <Td className="text-muted">{dateTime(a.started_at)}</Td>
                  <Td><SevBadge s={a.severity} /></Td>
                  <Td className="font-medium">{itemLabel(a)}</Td>
                  <Td className="max-w-sm truncate">{a.message}</Td>
                  <Td className="text-muted">{duration((a.resolved_at ?? Date.now() / 1000) - a.started_at)}</Td>
                  <Td><StateBadges a={a} />{a.state === "firing" && !a.acked && <Badge tone="crit">en cours</Badge>}</Td>
                  <Td className="max-w-xs truncate text-muted">{a.ack_by ? `${a.ack_by} : ${a.ack_comment}` : "—"}</Td>
                </Row>
              ))}
            </tbody>
          </Table>
          {data && !data.alerts.length && <Empty title="Aucune alerte sur cette période" />}
          {data && data.total > size && (
            <div className="flex items-center justify-end gap-2 p-3 text-xs text-muted">
              {page * size + 1}–{Math.min(data.total, (page + 1) * size)} sur {data.total}
              <Button size="sm" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</Button>
              <Button size="sm" disabled={(page + 1) * size >= data.total} onClick={() => setPage(page + 1)}>Suivant</Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
