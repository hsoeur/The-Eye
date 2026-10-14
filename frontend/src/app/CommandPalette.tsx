import { Command } from "cmdk";
import { CornerDownLeft, LayoutDashboard, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import type { ModuleInfo } from "@/lib/types";
import { frontModule, type SearchItem } from "./registry";
import { Kbd } from "@/components/ui/card";

export function CommandTrigger({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex h-8 w-full max-w-sm items-center gap-2 rounded-md border bg-surface px-2.5 text-[13px] text-faint transition-colors hover:border-faint">
      <Search className="size-3.5" />
      <span className="flex-1 text-left">Rechercher un équipement, un container…</span>
      <Kbd>Ctrl K</Kbd>
    </button>
  );
}

export function CommandPalette({ open, setOpen, modules }: { open: boolean; setOpen: (o: boolean) => void; modules: ModuleInfo[] }) {
  const nav = useNavigate();
  const { setTheme } = useTheme();
  const [query, setQuery] = useState("");

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(!open); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [open, setOpen]);

  useEffect(() => { if (!open) setQuery(""); }, [open]);

  const sources = modules.map((m) => ({ m, def: frontModule(m.id) })).filter((x) => x.def?.search);
  const results = useQueries({
    queries: sources.map(({ def }) => ({
      queryKey: [def!.search!.url], queryFn: () => api.get<unknown>(def!.search!.url), enabled: open, staleTime: 5000,
    })),
  });
  const entities = useMemo(() => sources.flatMap(({ m, def }, i) => {
    const d = results[i]?.data;
    return d ? def!.search!.items(d).map((it: SearchItem) => ({ ...it, group: m.label })) : [];
  }), [results.map((r) => r.dataUpdatedAt).join()]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = (to: string) => { setOpen(false); nav(to); };
  const itemCls = "flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[13px] data-[selected=true]:bg-raised";

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Recherche globale" shouldFilter
      overlayClassName="fade-in fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]"
      contentClassName="fade-in fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border bg-surface shadow-2xl">
      <Command.Input value={query} onValueChange={setQuery} placeholder="Aller à, ou rechercher…" className="h-12 w-full border-b bg-transparent px-4 text-[14px] outline-none placeholder:text-faint" />
      <Command.List className="max-h-[50vh] overflow-auto p-1.5">
        <Command.Empty className="px-3 py-8 text-center text-[13px] text-muted">Aucun résultat</Command.Empty>
        <Command.Group heading="Pages" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-faint">
          <Command.Item value="vue d'ensemble accueil" onSelect={() => go("/")} className={itemCls}><LayoutDashboard className="size-4 text-muted" />Vue d'ensemble</Command.Item>
          {modules.map((m) => {
            const Icon = frontModule(m.id)?.icon;
            return <Command.Item key={m.id} value={`${m.label} ${m.id}`} onSelect={() => go(`/${m.id}`)} className={itemCls}>
              {Icon && <Icon className="size-4 text-muted" />}{m.label}</Command.Item>;
          })}
        </Command.Group>
        {entities.length > 0 && (
          <Command.Group heading="Éléments" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-faint">
            {entities.map((e) => (
              <Command.Item key={e.group + e.id} value={`${e.label} ${e.hint ?? ""} ${e.group}`} onSelect={() => go(e.to)} className={itemCls}>
                <span className="flex-1 truncate">{e.label}</span>
                <span className="truncate text-xs text-faint">{e.hint}</span>
                <span className="text-[11px] text-faint">{e.group}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="Thème" className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:text-faint">
          {(["light", "dark", "system"] as const).map((t) => (
            <Command.Item key={t} value={`thème ${t}`} onSelect={() => { setTheme(t); setOpen(false); }} className={itemCls}>
              Thème {{ light: "clair", dark: "sombre", system: "système" }[t]}
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
      <div className="flex items-center gap-3 border-t px-3 py-2 text-[11px] text-faint">
        <span className="flex items-center gap-1"><CornerDownLeft className="size-3" /> ouvrir</span><span>↑↓ naviguer</span><span>Échap fermer</span>
      </div>
    </Command.Dialog>
  );
}
