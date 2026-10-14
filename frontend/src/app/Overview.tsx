import { ArrowUpRight, CheckCircle2, Info, TriangleAlert, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, StatusDot, toneOf } from "@/components/ui/badge";
import { Card, CardHeader, Empty, PageHeader, Skeleton } from "@/components/ui/card";
import { ago } from "@/lib/format";
import type { EyeEvent, ModuleInfo, Overview as OverviewData } from "@/lib/types";
import { usePoll } from "@/lib/usePoll";
import { cn } from "@/lib/utils";
import { frontModule } from "./registry";

const STATUS = { ok: "Opérationnel", warning: "Attention", critical: "Alerte", unknown: "Inconnu" } as const;
const EDGE = { ok: "before:bg-ok", warning: "before:bg-warn", critical: "before:bg-crit", unknown: "before:bg-faint" } as const;

function ModuleCard({ m }: { m: ModuleInfo }) {
  const Icon = frontModule(m.id)?.icon;
  return (
    <Link to={`/${m.id}`} className={cn("group relative block overflow-hidden rounded-card border bg-surface p-4 transition-colors hover:border-faint",
      "before:absolute before:inset-y-0 before:left-0 before:w-[3px]", EDGE[m.health.status])}>
      <div className="flex items-center gap-2">
        {Icon && <Icon className="size-4 text-muted" />}
        <h2 className="flex-1 text-[14px] font-semibold">{m.label}</h2>
        <ArrowUpRight className="size-4 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[13px] text-muted">
        <StatusDot tone={toneOf(m.health.status)} />{STATUS[m.health.status]}
      </div>
      <p className="mt-2 min-h-[1.25rem] truncate text-[13px]">{m.health.summary || "—"}</p>
      <div className="mt-4 flex gap-6">
        {m.health.stats.map((s) => (
          <div key={s.label}>
            <div className="text-xl font-semibold tabular-nums leading-none">{s.value}</div>
            <div className="mt-1 text-xs text-muted">{s.label}</div>
          </div>
        ))}
      </div>
    </Link>
  );
}

const sev = {
  critical: { icon: XCircle, cls: "text-crit" },
  warning: { icon: TriangleAlert, cls: "text-warn" },
  ok: { icon: CheckCircle2, cls: "text-ok" },
  info: { icon: Info, cls: "text-faint" },
} as const;

export function EventRow({ e, now }: { e: EyeEvent; now: number }) {
  const { icon: Icon, cls } = sev[e.severity] ?? sev.info;
  return (
    <li className="flex items-start gap-3 px-4 py-2.5">
      <Icon className={cn("mt-0.5 size-4 shrink-0", cls)} />
      <span className="min-w-0 flex-1 text-[13px]">{e.message}</span>
      <Badge className="shrink-0">{e.source}</Badge>
      <span className="w-24 shrink-0 text-right text-xs text-faint">{ago(e.t, now)}</span>
    </li>
  );
}

export default function Overview() {
  const { data } = usePoll<OverviewData>("/api/overview", 5000);
  const modules = [...(data?.modules ?? [])].sort((a, b) => {
    const rank = { critical: 0, warning: 1, unknown: 2, ok: 3 } as const;
    return rank[a.health.status] - rank[b.health.status];
  });
  return (
    <div className="fade-in mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader title="Vue d'ensemble" subtitle="État de l'ensemble des modules de supervision" />
      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{modules.map((m) => <ModuleCard key={m.id} m={m} />)}</div>
      )}
      <Card>
        <CardHeader title="Activité récente" />
        {data?.events.length ? (
          <ul className="mt-2 divide-y pb-1">{data.events.map((e, i) => <EventRow key={i} e={e} now={data.now} />)}</ul>
        ) : (
          <Empty icon={<CheckCircle2 />} title="Aucun événement" hint="Les changements d'état (équipement, container, service) apparaîtront ici." />
        )}
      </Card>
    </div>
  );
}
