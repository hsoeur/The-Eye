import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { Modal } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { ago, dateTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { itemLabel, SevBadge, StateBadges, useAuthor } from "./shared";
import { EVENT_LABEL, REASON_LABEL, type Alert, type AlertEvent } from "./types";

const DURATIONS: [string, number][] = [["Jusqu'à résolution", 0], ["1 heure", 3600], ["4 heures", 14400], ["24 heures", 86400], ["7 jours", 604800]];

type Mode = "ack" | "comment" | "unack";
const TEXT: Record<Mode, { title: string; label: string; ok: string }> = {
  ack: { title: "Acquitter l'alerte", label: "Commentaire (obligatoire)", ok: "Acquitter" },
  comment: { title: "Ajouter un commentaire", label: "Commentaire", ok: "Ajouter" },
  unack: { title: "Retirer l'acquittement", label: "Motif (facultatif)", ok: "Retirer" },
};

export function ActionDialog({ alert, mode, onClose }: { alert: Alert; mode: Mode; onClose: () => void }) {
  const qc = useQueryClient();
  const [author, setAuthor] = useAuthor();
  const [text, setText] = useState("");
  const [dur, setDur] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const t = TEXT[mode];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const body = mode === "ack" ? { author, comment: text, until: dur ? Date.now() / 1000 + dur : null }
        : mode === "comment" ? { author, text } : { author, comment: text };
      await api.post(`/api/alerts/${alert.id}/${mode}`, body);
      toast.success(mode === "ack" ? "Alerte acquittée" : mode === "comment" ? "Commentaire ajouté" : "Acquittement retiré");
      qc.invalidateQueries({ queryKey: ["/api/alerts"] });
      qc.invalidateQueries({ queryKey: [`/api/alerts/${alert.id}`] });
      onClose();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Erreur"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={t.title} description={`${alert.message} — ${itemLabel(alert)}`}>
      <form onSubmit={submit} className="grid gap-4">
        <Field label="Votre nom" hint="Mémorisé dans ce navigateur ; tracé avec votre adresse IP.">
          <Input required autoFocus={!author} maxLength={80} value={author} onChange={(e) => setAuthor(e.target.value)} />
        </Field>
        <Field label={t.label}>
          <textarea required={mode !== "unack"} autoFocus={!!author} rows={3} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border bg-surface px-2.5 py-2 text-[13px] focus-visible:outline-2 focus-visible:outline-accent" />
        </Field>
        {mode === "ack" && (
          <Field label="Durée" hint="Passé ce délai, l'alerte redevient « à traiter » si elle persiste.">
            <Select value={dur} onChange={(e) => setDur(+e.target.value)}>{DURATIONS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}</Select>
          </Field>
        )}
        {error && <p role="alert" className="rounded-md bg-crit/10 px-3 py-2 text-[13px] text-crit">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary" disabled={busy}>{busy ? "…" : t.ok}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function AlertDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, isError } = usePoll<{ alert: Alert; events: AlertEvent[] }>(`/api/alerts/${id}`, 5000);
  const [mode, setMode] = useState<Mode | null>(null);
  const a = data?.alert;

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} wide title={a ? a.message : "Alerte"} description={a ? itemLabel(a) : undefined}>
      {isError && !a ? <p className="text-[13px] text-crit">Alerte introuvable.</p> : !a ? <Skeleton className="h-40" /> : (
        <div className="grid gap-5">
          <div className="flex flex-wrap items-center gap-2">
            <SevBadge s={a.severity} /><StateBadges a={a} />
            <span className="text-xs text-muted">depuis {dateTime(a.started_at)} ({ago(a.started_at)})</span>
            <div className="ml-auto flex gap-2">
              <Button onClick={() => setMode("comment")}>Commenter</Button>
              {a.state === "firing" && (a.acked
                ? <Button onClick={() => setMode("unack")}>Retirer l'acquittement</Button>
                : <Button variant="primary" onClick={() => setMode("ack")}>Acquitter</Button>)}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px] md:grid-cols-4">
            {([["Règle", a.rule_name], ["Valeur actuelle", a.value], ["Pic", a.peak_value], ["Seuil", `${a.operator} ${a.threshold}`],
              ["Réouvertures", a.reopened], ["Oscillations (1 h)", a.flaps],
              ["Fin", a.resolved_at ? `${dateTime(a.resolved_at)} — ${REASON_LABEL[a.resolve_reason] ?? a.resolve_reason}` : "En cours"],
              ["Acquittement", a.acked ? `${a.ack_by} : ${a.ack_comment}` : "—"]] as [string, string | number][]).map(([k, v]) => (
              <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="break-words font-medium">{v}</dd></div>
            ))}
          </dl>
          <div>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Historique de l'alerte</h3>
            <ol className="space-y-2 border-l pl-4">
              {data!.events.map((e) => (
                <li key={e.id} className="relative text-[13px]">
                  <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-accent" />
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium">{EVENT_LABEL[e.type] ?? e.type}</span>
                    <span className="text-xs text-muted">{dateTime(e.t)} · {e.author}{e.data?.ip ? ` (${e.data.ip})` : ""}</span>
                  </div>
                  {e.comment && <p className="mt-0.5 whitespace-pre-wrap text-muted">{e.comment}</p>}
                </li>
              ))}
              {!data!.events.length && <li className="text-[13px] text-muted">Aucun évènement enregistré.</li>}
            </ol>
          </div>
        </div>
      )}
      {mode && a && <ActionDialog alert={a} mode={mode} onClose={() => setMode(null)} />}
    </Modal>
  );
}
