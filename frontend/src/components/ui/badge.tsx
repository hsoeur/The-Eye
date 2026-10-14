import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Level } from "@/lib/format";

export type Tone = "ok" | "warn" | "crit" | "off" | "info";

const dotColor: Record<Tone, string> = {
  ok: "bg-ok", warn: "bg-warn", crit: "bg-crit pulse-crit", off: "bg-faint/60", info: "bg-accent",
};

export function StatusDot({ tone, className }: { tone: Tone; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", dotColor[tone], className)} />;
}

const badge: Record<Tone, string> = {
  ok: "bg-ok/12 text-ok", warn: "bg-warn/12 text-warn", crit: "bg-crit/12 text-crit",
  off: "bg-raised text-muted", info: "bg-accent/12 text-accent",
};

export function Badge({ tone = "off", className, children, ...p }: { tone?: Tone; children: ReactNode } & HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium leading-none", badge[tone], className)} {...p}>
      {children}
    </span>
  );
}

export const toneOf = (s: string): Tone =>
  s === "ok" ? "ok" : s === "warning" ? "warn" : s === "critical" ? "crit" : s === "info" ? "info" : "off";

export const toneOfLevel = (l: Level): Tone => l;
