import { Copy, Eye, KeyRound, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, PageHeader, Skeleton } from "@/components/ui/card";
import { Modal, useConfirm } from "@/components/ui/dialog";
import { Field, Input, SearchInput, Select } from "@/components/ui/input";
import { Row, Table, Td, Th } from "@/components/ui/table";
import { Tab, TabList, TabPanel, Tabs } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import type { Host } from "@/modules/machines/types";
import type { Account, AccountForm, AuditEntry, Usage, VaultState } from "./types";

const URL = "/api/vault";
const CLIP_CLEAR_MS = 30_000;
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "Erreur");
const date = (t: number) => new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
const ageDays = (t: number) => Math.floor((Date.now() / 1000 - t) / 86400);

async function copySecret(secret: string) {
  await navigator.clipboard.writeText(secret);
  toast.success("Copié — le presse-papiers sera vidé dans 30 s");
  setTimeout(() => navigator.clipboard.writeText("").catch(() => {}), CLIP_CLEAR_MS);
}

export default function VaultPage() {
  const qc = useQueryClient();
  const { data, isLoading } = usePoll<VaultState>(URL, 10_000);
  const refresh = () => qc.invalidateQueries({ queryKey: [URL] });

  if (isLoading || !data) return <div className="space-y-3 p-6"><Skeleton className="h-8 w-48" /><Skeleton className="h-64" /></div>;
  if (!data.available)
    return <Empty icon={<KeyRound />} title="Dépendance manquante" hint={`Installez la bibliothèque : pip install cryptography (${data.error})`} />;
  if (!data.unlocked) return <Gate state={data} onDone={refresh} />;
  return <Unlocked state={data} onChange={refresh} />;
}

function Gate({ state, onDone }: { state: VaultState; onDone: () => void }) {
  const [pass, setPass] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const setup = !state.initialized;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (setup && pass !== confirm) return setError("Les deux phrases secrètes diffèrent");
    setBusy(true); setError("");
    try { await api.post(`${URL}/${setup ? "setup" : "unlock"}`, { passphrase: pass }); onDone(); }
    catch (err) { setError(errMsg(err)); }
    finally { setBusy(false); setPass(""); setConfirm(""); }
  };

  return (
    <div className="mx-auto mt-16 w-full max-w-md px-4">
      <form onSubmit={submit} className="grid gap-4 rounded-xl border bg-surface p-6">
        <div className="flex items-center gap-2 text-[15px] font-semibold"><Lock className="size-4" />{setup ? "Initialiser le coffre" : "Coffre verrouillé"}</div>
        <p className="text-[13px] text-muted">
          {setup ? `Choisissez une phrase secrète (${state.min_passphrase} caractères minimum). Elle n'est stockée nulle part : si vous la perdez, les mots de passe sont irrécupérables.`
            : "Saisissez la phrase secrète pour déverrouiller."}
        </p>
        <Field label="Phrase secrète"><Input autoFocus required type="password" autoComplete="off" value={pass} onChange={(e) => setPass(e.target.value)} /></Field>
        {setup && <Field label="Confirmation"><Input required type="password" autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>}
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <Button type="submit" variant="primary" disabled={busy}>{busy ? "…" : setup ? "Créer le coffre" : "Déverrouiller"}</Button>
      </form>
    </div>
  );
}

function Unlocked({ state, onChange }: { state: VaultState; onChange: () => void }) {
  const confirm = useConfirm();
  const [tab, setTab] = useState("accounts");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [revealing, setRevealing] = useState<Account | null>(null);
  const [changingPass, setChangingPass] = useState(false);
  const { data: machines } = usePoll<{ hosts: Host[] }>("/api/machines", 30_000);

  const needle = q.trim().toLowerCase();
  const rows = state.accounts.filter((a) => !needle ||
    [a.label, a.username, a.kind, ...a.usages.flatMap((u) => [u.machine, u.poste, u.usage])].some((s) => s.toLowerCase().includes(needle)));

  const remove = async (a: Account) => {
    if (!(await confirm({ title: `Supprimer « ${a.label} » ?`, description: "Le mot de passe sera définitivement perdu.", confirmLabel: "Supprimer", danger: true }))) return;
    try { await api.del(`${URL}/accounts/${a.id}`); onChange(); } catch (e) { toast.error(errMsg(e)); }
  };
  const lock = async () => { await api.post(`${URL}/lock`); onChange(); };

  return (
    <div className="flex h-full flex-col">
      <div className="px-6 pt-5 pb-3">
        <PageHeader title="Coffre" subtitle={`${state.count} compte${state.count > 1 ? "s" : ""} · verrouillage auto après ${Math.round(state.auto_lock_s / 60)} min d'inactivité`}
          actions={<>
            <Button onClick={() => setChangingPass(true)}>Changer la phrase secrète</Button>
            <Button onClick={lock}><Lock className="size-3.5" />Verrouiller</Button>
            <Button variant="primary" onClick={() => setEditing("new")}><Plus className="size-3.5" />Ajouter un compte</Button>
          </>} />
      </div>
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <div className="px-6"><TabList><Tab value="accounts" count={state.count}>Comptes</Tab><Tab value="audit">Audit</Tab></TabList></div>
        <div className="min-h-0 flex-1 overflow-auto">
          <TabPanel value="accounts">
            <div className="px-6 py-3"><SearchInput placeholder="Rechercher un compte, une machine, un poste…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            {!rows.length ? <Empty icon={<KeyRound />} title={state.count ? "Aucun résultat" : "Aucun compte"} hint={state.count ? undefined : "Ajoutez les comptes utilisés en production."} /> : (
              <Table>
                <thead><tr><Th>Compte</Th><Th>Identifiant</Th><Th>Type</Th><Th>Utilisé sur</Th><Th>Mot de passe changé</Th><Th className="w-32" /></tr></thead>
                <tbody>
                  {rows.map((a) => {
                    const d = ageDays(a.rotated_at), stale = state.stale_days > 0 && d > state.stale_days;
                    return (
                      <Row key={a.id}>
                        <Td className="font-medium">{a.label}</Td>
                        <Td className="text-muted">{a.username}</Td>
                        <Td><Badge>{a.kind}</Badge></Td>
                        <Td className="text-muted">{a.usages.length ? a.usages.map((u, i) => (
                          <div key={i}>{[u.machine, u.poste, u.usage].filter(Boolean).join(" · ")}</div>)) : "—"}</Td>
                        <Td>{stale ? <Badge tone="warn">il y a {d} j</Badge> : <span className="text-muted">il y a {d} j</span>}</Td>
                        <Td>
                          <div className="flex justify-end gap-1">
                            <Button variant="ghost" size="icon" aria-label="Afficher / copier" onClick={() => setRevealing(a)}><Eye className="size-4" /></Button>
                            <Button variant="ghost" size="icon" aria-label="Modifier" onClick={() => setEditing(a)}><Pencil className="size-4" /></Button>
                            <Button variant="ghost" size="icon" aria-label="Supprimer" onClick={() => remove(a)}><Trash2 className="size-4" /></Button>
                          </div>
                        </Td>
                      </Row>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </TabPanel>
          <TabPanel value="audit"><AuditTab /></TabPanel>
        </div>
      </Tabs>
      {editing && <AccountModal account={editing === "new" ? null : editing} state={state} hosts={machines?.hosts ?? []}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChange(); }} />}
      {revealing && <RevealModal account={revealing} onClose={() => setRevealing(null)} />}
      {changingPass && <PassphraseModal onClose={() => setChangingPass(false)} />}
    </div>
  );
}

function AuditTab() {
  const { data } = usePoll<{ audit: AuditEntry[] }>(`${URL}/audit`, 10_000);
  const rows = data?.audit ?? [];
  if (!rows.length) return <Empty title="Aucune activité" />;
  return (
    <Table>
      <thead><tr><Th>Date</Th><Th>Action</Th><Th>Compte</Th><Th>Poste client</Th></tr></thead>
      <tbody>{rows.map((r, i) => (
        <Row key={i}><Td className="text-muted">{date(r.t)}</Td><Td><Badge tone={r.action === "reveal" ? "warn" : "off"}>{r.action}</Badge></Td>
          <Td>{r.label || "—"}</Td><Td className="text-muted">{r.client}</Td></Row>))}</tbody>
    </Table>
  );
}

function AccountModal({ account, state, hosts, onClose, onSaved }: {
  account: Account | null; state: VaultState; hosts: Host[]; onClose: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState<AccountForm>({
    label: account?.label ?? "", username: account?.username ?? "", kind: account?.kind ?? "windows", secret: "",
    notes: account?.notes ?? "", usages: account?.usages ?? [],
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof AccountForm>(k: K, v: AccountForm[K]) => setF((s) => ({ ...s, [k]: v }));
  const setUsage = (i: number, patch: Partial<Usage>) => set("usages", f.usages.map((u, j) => (j === i ? { ...u, ...patch } : u)));
  const setMachine = (i: number, machine: string) => setUsage(i, { machine, host_id: hosts.find((h) => h.name === machine)?.id ?? "" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      if (account) await api.put(`${URL}/accounts/${account.id}`, f); else await api.post(`${URL}/accounts`, f);
      toast.success("Enregistré");
      onSaved();
    } catch (err) { setError(errMsg(err)); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} wide title={account ? "Modifier le compte" : "Ajouter un compte"}>
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Libellé"><Input autoFocus required placeholder="SQL Server prod" value={f.label} onChange={(e) => set("label", e.target.value)} /></Field>
          <Field label="Type"><Select value={f.kind} onChange={(e) => set("kind", e.target.value)}>{state.kinds.map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label="Identifiant"><Input required autoComplete="off" value={f.username} onChange={(e) => set("username", e.target.value)} /></Field>
          <Field label="Mot de passe" hint={account ? "Laisser vide pour ne pas le changer" : undefined}>
            <Input type="password" autoComplete="new-password" required={!account} value={f.secret} onChange={(e) => set("secret", e.target.value)} /></Field>
        </div>
        <Field label="Utilisé sur (machine / poste / usage)">
          <div className="grid gap-2">
            <datalist id="vault-hosts">{hosts.map((h) => <option key={h.id} value={h.name} />)}</datalist>
            {f.usages.map((u, i) => (
              <div key={i} className="flex gap-2">
                <Input list="vault-hosts" placeholder="Machine" value={u.machine} onChange={(e) => setMachine(i, e.target.value)} />
                <Input placeholder="Poste" value={u.poste} onChange={(e) => setUsage(i, { poste: e.target.value })} />
                <Input placeholder="Usage (service, tâche, appli…)" value={u.usage} onChange={(e) => setUsage(i, { usage: e.target.value })} />
                <Button variant="ghost" size="icon" aria-label="Retirer" onClick={() => set("usages", f.usages.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <div><Button onClick={() => set("usages", [...f.usages, { host_id: "", machine: "", poste: "", usage: "" }])}><Plus className="size-3.5" />Ajouter un usage</Button></div>
          </div>
        </Field>
        <Field label="Notes"><Input value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <div className="flex justify-end gap-2"><Button onClick={onClose}>Annuler</Button><Button type="submit" variant="primary" disabled={busy}>{busy ? "…" : "Enregistrer"}</Button></div>
      </form>
    </Modal>
  );
}

function RevealModal({ account, onClose }: { account: Account; onClose: () => void }) {
  const [pass, setPass] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (secret === null) return;
    const t = setTimeout(onClose, CLIP_CLEAR_MS);
    return () => clearTimeout(t);
  }, [secret, onClose]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { setSecret((await api.post<{ secret: string }>(`${URL}/accounts/${account.id}/reveal`, { passphrase: pass })).secret); }
    catch (err) { setError(errMsg(err)); }
    finally { setBusy(false); setPass(""); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={account.label} description={`Identifiant : ${account.username}`}>
      {secret === null ? (
        <form onSubmit={submit} className="grid gap-4">
          <Field label="Phrase secrète" hint="Re-saisie requise : cet accès est enregistré dans l'audit"><Input autoFocus required type="password" autoComplete="off" value={pass} onChange={(e) => setPass(e.target.value)} /></Field>
          {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Annuler</Button><Button type="submit" variant="primary" disabled={busy}>Afficher</Button></div>
        </form>
      ) : (
        <div className="grid gap-4">
          <code className="break-all rounded-md bg-raised px-3 py-2 text-[13px]">{secret}</code>
          <p className="text-[12px] text-muted">Se ferme automatiquement dans 30 s.</p>
          <div className="flex justify-end gap-2"><Button onClick={() => copySecret(secret).catch(() => toast.error("Copie impossible"))}><Copy className="size-3.5" />Copier</Button><Button variant="primary" onClick={onClose}>Fermer</Button></div>
        </div>
      )}
    </Modal>
  );
}

function PassphraseModal({ onClose }: { onClose: () => void }) {
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try { await api.post(`${URL}/passphrase`, { old, new: next }); toast.success("Phrase secrète changée"); onClose(); }
    catch (err) { setError(errMsg(err)); }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Changer la phrase secrète" description="Tous les mots de passe sont rechiffrés.">
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Phrase actuelle"><Input autoFocus required type="password" autoComplete="off" value={old} onChange={(e) => setOld(e.target.value)} /></Field>
        <Field label="Nouvelle phrase"><Input required type="password" autoComplete="off" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <div className="flex justify-end gap-2"><Button onClick={onClose}>Annuler</Button><Button type="submit" variant="primary">Changer</Button></div>
      </form>
    </Modal>
  );
}
