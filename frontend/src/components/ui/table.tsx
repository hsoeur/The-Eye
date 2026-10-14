import { X } from "lucide-react";
import type { HTMLAttributes, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

export const Table = ({ className, ...p }: HTMLAttributes<HTMLTableElement>) =>
  <table className={cn("w-full border-collapse text-[13px]", className)} {...p} />;

export const Th = ({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) =>
  <th className={cn("sticky top-0 z-10 border-b bg-surface px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted", className)} {...p} />;

export const Td = ({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) =>
  <td className={cn("whitespace-nowrap border-b px-3 py-2 align-middle", className)} {...p} />;

export function Row({ selected, onClick, className, ...p }: HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }) {
  return <tr tabIndex={onClick ? 0 : undefined} onClick={onClick}
    onKeyDown={(e) => { if (onClick && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onClick(e as never); } }}
    className={cn("transition-colors", onClick && "cursor-pointer hover:bg-raised", selected && "bg-accent/8 hover:bg-accent/10", className)} {...p} />;
}

/** Disposition maître/détail : liste à gauche, panneau de détail à droite. */
export function Split({ list, detail }: { list: ReactNode; detail: ReactNode | null }) {
  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto">{list}</div>
      {detail && <aside className="fade-in w-[26rem] max-w-[45%] shrink-0 overflow-auto border-l bg-surface max-lg:fixed max-lg:inset-y-14 max-lg:right-0 max-lg:z-30 max-lg:max-w-full max-lg:shadow-2xl">{detail}</aside>}
    </div>
  );
}

export function PanelHeader({ title, subtitle, onClose, actions }: { title: ReactNode; subtitle?: ReactNode; onClose: () => void; actions?: ReactNode }) {
  return (
    <div className="sticky top-0 z-10 flex items-start gap-2 border-b bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-[15px] font-semibold">{title}</h2>
        {subtitle && <div className="mt-0.5 truncate text-xs text-muted">{subtitle}</div>}
      </div>
      {actions}
      <Button variant="ghost" size="icon" aria-label="Fermer le détail" onClick={onClose} className="-mr-1.5 -mt-0.5"><X className="size-4" /></Button>
    </div>
  );
}

export const Toolbar = ({ children }: { children: ReactNode }) =>
  <div className="flex flex-wrap items-center gap-2 border-b bg-surface px-4 py-2.5">{children}</div>;
