import { Eye, LayoutDashboard, WifiOff } from "lucide-react";
import { Suspense, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { StatusDot, toneOf } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/card";
import { usePoll } from "@/lib/usePoll";
import type { Overview } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CommandPalette, CommandTrigger } from "./CommandPalette";
import { ThemeToggle } from "./ThemeToggle";
import { frontModule } from "./registry";

const link = ({ isActive }: { isActive: boolean }) =>
  cn("group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-muted transition-colors hover:bg-raised hover:text-fg",
    isActive && "bg-raised text-fg");

export function Layout() {
  const { data, isError } = usePoll<Overview>("/api/overview", 5000);
  const [palette, setPalette] = useState(false);
  const modules = data?.modules ?? [];
  const alerts = modules.filter((m) => m.health.status === "critical" || m.health.status === "warning");
  const critical = modules.some((m) => m.health.status === "critical");

  return (
    <div className="flex h-full">
      <aside className="flex w-14 shrink-0 flex-col border-r bg-surface md:w-56">
        <div className="flex h-14 items-center gap-2.5 px-3.5">
          <div className="flex size-7 items-center justify-center rounded-lg bg-accent text-accent-fg"><Eye className="size-4" /></div>
          <span className="hidden text-[15px] font-semibold tracking-tight md:block">The Eye</span>
        </div>
        <nav aria-label="Navigation principale" className="flex-1 space-y-0.5 px-2 py-2">
          <NavLink to="/" end className={link}>
            <LayoutDashboard className="size-4 shrink-0" /><span className="hidden md:block">Vue d'ensemble</span>
          </NavLink>
          <div className="px-2.5 pb-1 pt-4 text-[11px] font-medium uppercase tracking-wide text-faint max-md:hidden">Supervision</div>
          {modules.map((m) => {
            const Icon = frontModule(m.id)?.icon;
            if (!Icon) return null;
            return (
              <NavLink key={m.id} to={`/${m.id}`} className={link} title={m.label}>
                <Icon className="size-4 shrink-0" />
                <span className="hidden flex-1 md:block">{m.label}</span>
                <StatusDot tone={toneOf(m.health.status)} className="max-md:hidden" />
              </NavLink>
            );
          })}
        </nav>
        <div className="space-y-2 p-2 max-md:hidden"><ThemeToggle /></div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-surface px-4">
          <CommandTrigger onClick={() => setPalette(true)} />
          <div className="ml-auto flex items-center gap-3">
            {isError ? (
              <span className="flex items-center gap-1.5 text-[13px] font-medium text-crit"><WifiOff className="size-4" />Serveur injoignable</span>
            ) : alerts.length ? (
              <NavLink to="/" className={cn("flex items-center gap-2 rounded-md px-2.5 py-1 text-[13px] font-medium", critical ? "bg-crit/12 text-crit" : "bg-warn/12 text-warn")}>
                <StatusDot tone={critical ? "crit" : "warn"} />{alerts.length} alerte{alerts.length > 1 ? "s" : ""}
              </NavLink>
            ) : modules.length ? (
              <span className="flex items-center gap-2 text-[13px] text-muted"><StatusDot tone="ok" />Tout est opérationnel</span>
            ) : null}
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-64 w-full" /></div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <CommandPalette open={palette} setOpen={setPalette} modules={modules} />
    </div>
  );
}
