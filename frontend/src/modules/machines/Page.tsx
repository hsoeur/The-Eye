import { Plus, Server as ServerIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge, StatusDot, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, PageHeader, Skeleton } from "@/components/ui/card";
import { Modal, useConfirm } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Row, Table, Td, Th } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { level, uptime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { HostDetail } from "./HostDetail";
import { isBad, type Host, type MachinesData, type MachineType } from "./types";

const tone = (h: Host): Tone => (h.ok === false ? "crit" : h.ok ? (h.metrics?.services.some(isBad) ? "warn" : "ok") : "off");

export default function MachinesPage() {
  const { "*": sel } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const { data, isLoading } = usePoll<MachinesData>("/api/machines", 3000);
  const [adding, setAdding] = useState(false);
  const selected = data?.hosts.find((h) => h.id === sel);

  if (isLoading) return <div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-64" /></div>;
  const hosts = data?.hosts ?? [];

  const remove = async (h: Host) => {
    if (!(await confirm({ title: `Retirer « ${h.name} » ?`, description: "La machine ne sera plus supervisée.", confirmLabel: "Retirer", danger: true }))) return;
    await api.del(`/api/machines/${h.id}`);
    nav("/machines");
    qc.invalidateQueries({ queryKey: ["/api/machines"] });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="px-6 pt-5 pb-3">
        <PageHeader title="Machines" subtitle={`${hosts.length} machine${hosts.length > 1 ? "s" : ""} supervisée${hosts.length > 1 ? "s" : ""}`}
          actions={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-3.5" />Ajouter une machine</Button>} />
      </div>
      {!hosts.length ? (
        <Empty icon={<ServerIcon />} title="Aucune machine supervisée" hint="Ajoutez un serveur Windows ou Linux pour suivre ses ressources, ses services et ses journaux."
          action={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-3.5" />Ajouter une machine</Button>} />
      ) : selected ? (
        <HostDetail host={selected} types={data!.types} onBack={() => nav("/machines")} onRemove={() => remove(selected)} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto border-t">
          <Table>
            <thead><tr><Th className="w-8" /><Th>Nom</Th><Th>Adresse</Th><Th>Type</Th><Th className="w-44">CPU</Th><Th className="w-44">Mémoire</Th><Th>Disponibilité</Th></tr></thead>
            <tbody>
              {hosts.map((h) => {
                const m = h.metrics, mem = m && m.mem_total ? (100 * m.mem_used) / m.mem_total : 0;
                return (
                  <Row key={h.id} onClick={() => nav(`/machines/${h.id}`)}>
                    <Td><StatusDot tone={tone(h)} /></Td>
                    <Td className="font-medium">{h.name}{h.ok === false && <Badge tone="crit" className="ml-2">injoignable</Badge>}</Td>
                    <Td className="text-muted">{h.ip}</Td>
                    <Td className="text-muted">{data!.types.find((t) => t.kind === h.kind)?.label ?? h.kind}</Td>
                    <Td>{m ? <Bar v={m.cpu} /> : "—"}</Td>
                    <Td>{m ? <Bar v={mem} /> : "—"}</Td>
                    <Td className="text-muted">{m ? uptime(m.uptime_s) : "—"}</Td>
                  </Row>
                );
              })}
            </tbody>
          </Table>
        </div>
      )}
      {adding && data && <AddMachine types={data.types} onClose={() => setAdding(false)}
        onAdded={(id) => { setAdding(false); qc.invalidateQueries({ queryKey: ["/api/machines"] }); nav(`/machines/${id}`); }} />}
    </div>
  );
}

const Bar = ({ v }: { v: number }) => {
  const l = level(v);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-raised"><div className={`h-full rounded-full ${l === "crit" ? "bg-crit" : l === "warn" ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(100, v)}%` }} /></div>
      <span className="w-10 text-xs tabular-nums text-muted">{v.toFixed(0)} %</span>
    </div>
  );
};

function AddMachine({ types, onClose, onAdded }: { types: MachineType[]; onClose: () => void; onAdded: (id: string) => void }) {
  const [kind, setKind] = useState(types[0]?.kind ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const type = types.find((t) => t.kind === kind);
  const set = (k: string, v: string) => setValues((s) => ({ ...s, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const { id } = await api.post<{ id: string }>("/api/machines", { kind, ...values });
      toast.success("Machine ajoutée");
      onAdded(id);
    } catch (err) { setError(err instanceof ApiError ? err.message : "Erreur"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Ajouter une machine" description="Elle sera mesurée toutes les 10 secondes, en lecture seule.">
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Type de machine">
          <Select value={kind} onChange={(e) => { setKind(e.target.value); setValues((s) => ({ ip: s.ip, name: s.name })); }}>
            {types.map((t) => <option key={t.kind} value={t.kind}>{t.label}</option>)}
          </Select>
        </Field>
        <Field label="Adresse IP ou nom DNS"><Input autoFocus required placeholder="192.168.1.10" value={values.ip ?? ""} onChange={(e) => set("ip", e.target.value)} /></Field>
        <Field label="Nom affiché" hint="Optionnel"><Input value={values.name ?? ""} onChange={(e) => set("name", e.target.value)} /></Field>
        {type?.fields.map((f) => (
          <Field key={f.name} label={f.label}>
            <Input type={f.type || "text"} placeholder={f.placeholder} autoComplete="off" value={values[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)} />
          </Field>
        ))}
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary" disabled={busy}>{busy ? "Ajout…" : "Ajouter"}</Button>
        </div>
      </form>
    </Modal>
  );
}
