import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal, useConfirm } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Row, Table, Td, Th } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { SevBadge } from "./shared";
import type { Catalog, Rule } from "./types";

const URL = "/api/alerts/rules";
const OPS = [">", ">=", "<", "<=", "==", "!="];
const blank: Rule = { id: "", name: "", metric: "cpu_pct", operator: ">", threshold: 90, severity: "warning", critical_threshold: null,
  for_seconds: 300, recover_seconds: 60, hysteresis: 0, source: "", targets: ["*"], exclude: [], item: "", enabled: true, description: "" };

export function RulesTab() {
  const { data } = usePoll<{ rules: Rule[] }>(URL, 10000);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [edit, setEdit] = useState<Rule | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: [URL] });

  const remove = async (r: Rule) => {
    if (!(await confirm({ title: `Supprimer la règle « ${r.name} » ?`, description: "Les alertes actives issues de cette règle seront résolues.", confirmLabel: "Supprimer", danger: true }))) return;
    await api.del(`${URL}/${r.id}`);
    refresh();
  };
  const toggle = async (r: Rule) => { await api.put(`${URL}/${r.id}`, { ...r, enabled: !r.enabled }); refresh(); };

  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button variant="primary" onClick={() => setEdit({ ...blank, id: "" })}><Plus className="size-3.5" />Nouvelle règle</Button></div>
      <Table>
        <thead><tr><Th>Règle</Th><Th>Condition</Th><Th>Gravité</Th><Th>Délai avant alerte</Th><Th>Cibles</Th><Th className="w-52" /></tr></thead>
        <tbody>
          {(data?.rules ?? []).map((r) => (
            <Row key={r.id} className={r.enabled ? "" : "opacity-50"}>
              <Td className="font-medium">{r.name}{!r.enabled && <Badge className="ml-2">désactivée</Badge>}</Td>
              <Td className="text-muted">{r.metric} {r.operator} {r.threshold}{r.critical_threshold != null && ` (critique : ${r.critical_threshold})`}{r.item && ` · ${r.item}`}</Td>
              <Td><SevBadge s={r.severity} /></Td>
              <Td className="text-muted">{r.for_seconds ? `${Math.round(r.for_seconds / 60)} min` : "immédiat"}</Td>
              <Td className="max-w-48 truncate text-muted">{r.targets.join(", ")}{r.exclude.length ? ` (hors ${r.exclude.join(", ")})` : ""}</Td>
              <Td className="space-x-1 text-right">
                <Button size="sm" onClick={() => toggle(r)}>{r.enabled ? "Désactiver" : "Activer"}</Button>
                <Button size="sm" onClick={() => setEdit(r)}>Modifier</Button>
                <Button size="sm" variant="danger" onClick={() => remove(r)}>Supprimer</Button>
              </Td>
            </Row>
          ))}
        </tbody>
      </Table>
      {edit && <RuleForm rule={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); refresh(); }} />}
    </div>
  );
}

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

function RuleForm({ rule, onClose, onSaved }: { rule: Rule; onClose: () => void; onSaved: () => void }) {
  const { data: cat } = usePoll<Catalog>("/api/alerts/catalog", 60000);
  const [r, setR] = useState(rule);
  const [targets, setTargets] = useState(rule.targets.join(", "));
  const [exclude, setExclude] = useState(rule.exclude.join(", "));
  const [error, setError] = useState("");
  const isNew = !rule.id;
  const set = <K extends keyof Rule>(k: K, v: Rule[K]) => setR((s) => ({ ...s, [k]: v }));
  const num = (v: string) => (v === "" ? 0 : Number(v));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const body = { ...r, targets: list(targets).length ? list(targets) : ["*"], exclude: list(exclude) };
    try {
      if (isNew) await api.post(URL, body); else await api.put(`${URL}/${rule.id}`, body);
      toast.success("Règle enregistrée");
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Erreur"); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={isNew ? "Nouvelle règle" : "Modifier la règle"} wide
      description="Une alerte se déclenche quand la condition reste vraie pendant le délai indiqué (anti-rebond).">
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <Field label="Nom"><Input required value={r.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Métrique">
          <Input required list="alert-metrics" value={r.metric} onChange={(e) => set("metric", e.target.value)} />
          <datalist id="alert-metrics">{cat?.metrics.map((m) => <option key={m.metric} value={m.metric}>{m.source}</option>)}</datalist>
        </Field>
        <Field label="Condition">
          <div className="flex gap-2">
            <Select className="w-24" value={r.operator} onChange={(e) => set("operator", e.target.value)}>{OPS.map((o) => <option key={o}>{o}</option>)}</Select>
            <Input required type="number" step="any" value={r.threshold} onChange={(e) => set("threshold", num(e.target.value))} />
          </div>
        </Field>
        <Field label="Gravité">
          <Select value={r.severity} onChange={(e) => set("severity", e.target.value as Rule["severity"])}><option value="info">Info</option><option value="warning">Avertissement</option><option value="critical">Critique</option></Select>
        </Field>
        <Field label="Seuil critique" hint="Optionnel : passe l'alerte en critique au-delà.">
          <Input type="number" step="any" value={r.critical_threshold ?? ""} onChange={(e) => set("critical_threshold", e.target.value === "" ? null : Number(e.target.value))} />
        </Field>
        <Field label="Délai avant alerte (secondes)" hint="Évite les fausses alertes sur un pic bref."><Input type="number" min={0} value={r.for_seconds} onChange={(e) => set("for_seconds", num(e.target.value))} /></Field>
        <Field label="Délai de retour à la normale (secondes)"><Input type="number" min={0} value={r.recover_seconds} onChange={(e) => set("recover_seconds", num(e.target.value))} /></Field>
        <Field label="Hystérésis" hint="Marge de sortie pour éviter l'oscillation autour du seuil."><Input type="number" min={0} step="any" value={r.hysteresis} onChange={(e) => set("hysteresis", num(e.target.value))} /></Field>
        <Field label="Cibles" hint="« * » pour toutes, ou identifiants séparés par des virgules.">
          <Input list="alert-targets" value={targets} onChange={(e) => setTargets(e.target.value)} />
          <datalist id="alert-targets">{cat?.targets.map((t) => <option key={t.target} value={t.target}>{t.name}</option>)}</datalist>
        </Field>
        <Field label="Exclure"><Input value={exclude} onChange={(e) => setExclude(e.target.value)} /></Field>
        <Field label="Élément (disque, service…)" hint="Optionnel : filtre sur l'élément mesuré."><Input value={r.item} onChange={(e) => set("item", e.target.value)} /></Field>
        <Field label="Description"><Input value={r.description} onChange={(e) => set("description", e.target.value)} /></Field>
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit md:col-span-2">{error}</p>}
        <div className="flex justify-end gap-2 md:col-span-2">
          <Button onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary">Enregistrer</Button>
        </div>
      </form>
    </Modal>
  );
}
