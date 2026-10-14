import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/card";
import { Modal, useConfirm } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Row, Table, Td, Th } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { useAuthor } from "./shared";
import type { Catalog, Maintenance } from "./types";

const URL = "/api/alerts/maintenance";
const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const KIND = { once: "Ponctuelle", daily: "Tous les jours", weekly: "Chaque semaine" };

/** Valeur d'un <input type="datetime-local"> (heure locale) ↔ timestamp serveur. */
const toLocal = (t: number) => { const d = new Date(t * 1000 - new Date().getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); };
const fromLocal = (s: string) => new Date(s).getTime() / 1000;

export function MaintenanceTab() {
  const { data } = usePoll<{ windows: Maintenance[] }>(URL, 10000);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [edit, setEdit] = useState<Maintenance | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: [URL] });
  const windows = data?.windows ?? [];

  const remove = async (m: Maintenance) => {
    if (!(await confirm({ title: `Supprimer « ${m.name} » ?`, confirmLabel: "Supprimer", danger: true }))) return;
    await api.del(`${URL}/${m.id}`);
    refresh();
  };
  const describe = (m: Maintenance) => m.kind === "once" ? `${dateTime(m.starts_at)} → ${dateTime(m.ends_at)}`
    : `${m.kind === "weekly" ? m.days.map((d) => DAYS[d]).join(", ") + " · " : ""}${m.start_time} pendant ${m.duration_min} min`;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-muted">Pendant une fenêtre, les alertes des cibles concernées sont mises en silence (elles restent historisées).</p>
        <Button variant="primary" onClick={() => setEdit({ id: "", name: "", targets: ["*"], kind: "once", starts_at: Date.now() / 1000, ends_at: Date.now() / 1000 + 3600, days: [0], start_time: "02:00", duration_min: 60, comment: "", enabled: true, created_by: "" })}><Plus className="size-3.5" />Nouvelle fenêtre</Button>
      </div>
      {!windows.length ? <Empty title="Aucune fenêtre de maintenance" hint="Planifiez un redémarrage ou une mise à jour pour éviter les fausses alertes." /> : (
        <Table>
          <thead><tr><Th>Nom</Th><Th>Type</Th><Th>Quand</Th><Th>Cibles</Th><Th /><Th className="w-40" /></tr></thead>
          <tbody>
            {windows.map((m) => (
              <Row key={m.id}>
                <Td className="font-medium">{m.name}{m.active && <Badge tone="warn" className="ml-2">en cours</Badge>}</Td>
                <Td className="text-muted">{KIND[m.kind]}</Td>
                <Td className="text-muted">{describe(m)}</Td>
                <Td className="max-w-48 truncate text-muted">{m.targets.join(", ")}</Td>
                <Td>{!m.enabled && <Badge>désactivée</Badge>}</Td>
                <Td className="space-x-1 text-right"><Button size="sm" onClick={() => setEdit(m)}>Modifier</Button><Button size="sm" variant="danger" onClick={() => remove(m)}>Supprimer</Button></Td>
              </Row>
            ))}
          </tbody>
        </Table>
      )}
      {edit && <Form m={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); refresh(); }} />}
    </div>
  );
}

function Form({ m, onClose, onSaved }: { m: Maintenance; onClose: () => void; onSaved: () => void }) {
  const { data: cat } = usePoll<Catalog>("/api/alerts/catalog", 60000);
  const [author] = useAuthor();
  const [v, setV] = useState(m);
  const [targets, setTargets] = useState(m.targets.join(", "));
  const [error, setError] = useState("");
  const set = <K extends keyof Maintenance>(k: K, val: Maintenance[K]) => setV((s) => ({ ...s, [k]: val }));
  const isNew = !m.id;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const t = targets.split(",").map((x) => x.trim()).filter(Boolean);
    const body = { ...v, targets: t.length ? t : ["*"], author };
    try {
      if (isNew) await api.post(URL, body); else await api.put(`${URL}/${m.id}`, body);
      toast.success("Fenêtre enregistrée");
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Erreur"); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={isNew ? "Nouvelle fenêtre de maintenance" : "Modifier la fenêtre"}>
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Nom"><Input required value={v.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Type"><Select value={v.kind} onChange={(e) => set("kind", e.target.value as Maintenance["kind"])}>{Object.entries(KIND).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>
        {v.kind === "once" ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Début"><Input required type="datetime-local" value={toLocal(v.starts_at)} onChange={(e) => set("starts_at", fromLocal(e.target.value))} /></Field>
            <Field label="Fin"><Input required type="datetime-local" value={toLocal(v.ends_at)} onChange={(e) => set("ends_at", fromLocal(e.target.value))} /></Field>
          </div>
        ) : (
          <>
            {v.kind === "weekly" && (
              <Field label="Jours"><div className="flex flex-wrap gap-1.5">{DAYS.map((d, i) => (
                <Button key={d} size="sm" variant={v.days.includes(i) ? "primary" : "secondary"} onClick={() => set("days", v.days.includes(i) ? v.days.filter((x) => x !== i) : [...v.days, i].sort())}>{d}</Button>
              ))}</div></Field>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Heure de début"><Input required type="time" value={v.start_time} onChange={(e) => set("start_time", e.target.value)} /></Field>
              <Field label="Durée (minutes)"><Input required type="number" min={1} max={1440} value={v.duration_min} onChange={(e) => set("duration_min", Number(e.target.value))} /></Field>
            </div>
          </>
        )}
        <Field label="Cibles" hint="« * » pour tout le parc, ou identifiants séparés par des virgules.">
          <Input list="maint-targets" value={targets} onChange={(e) => setTargets(e.target.value)} />
          <datalist id="maint-targets">{cat?.targets.map((t) => <option key={t.target} value={t.target}>{t.name}</option>)}</datalist>
        </Field>
        <Field label="Commentaire"><Input value={v.comment} onChange={(e) => set("comment", e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={v.enabled} onChange={(e) => set("enabled", e.target.checked)} />Active</label>
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <div className="flex justify-end gap-2"><Button onClick={onClose}>Annuler</Button><Button type="submit" variant="primary">Enregistrer</Button></div>
      </form>
    </Modal>
  );
}
