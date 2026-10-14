import { h, render } from "/js/core/dom.js";
import { lineChart, meter } from "/js/core/chart.js";
import { bytes, dateTime, level, uptime } from "/js/core/format.js";
import { button, confirmDialog, dot, empty, field, kv, modal, panel, tag, toast } from "/js/core/ui.js";

const TABS = [["summary", "Résumé"], ["services", "Services"], ["procs", "Processus"], ["events", "Journal"]];
const isBad = (s) => s.state === "failed" || (s.start === "auto" && s.state !== "running");
const hostStatus = (x) => (x.ok === false ? "critical" : x.ok ? "ok" : "");

export default {
  mount(el, ctx) {
    let HS = [], types = [], selected = ctx.sub[0] || null, tab = "summary", view = null, viewHost = null;

    const list = h("div");
    const detail = h("div", { class: "main", style: { padding: "16px 20px" } });
    render(el, h("div", { class: "split" },
      h("div", { class: "list" },
        h("div", { class: "toolbar" }, button("Ajouter une machine", openAdd, "primary")), list),
      detail));

    ctx.onRoute?.((sub) => { selected = sub[0] || null; draw(); });
    const select = (id) => { selected = id; ctx.navigate(id ? `machines/${id}` : "machines"); draw(); };

    function openAdd() {
      const kind = h("select", { onchange: build }, types.map((t) => h("option", { value: t.kind }, t.label)));
      const ip = h("input", { placeholder: "Adresse IP ou nom DNS", required: true });
      const name = h("input", { placeholder: "Nom affiché (optionnel)" });
      const extra = h("div", { class: "stack" });
      let inputs = {};
      function build() {
        const t = types.find((x) => x.kind === kind.value);
        inputs = {};
        render(extra, t.fields.map((fd) => {
          inputs[fd.name] = h("input", { type: fd.type || "text", placeholder: fd.placeholder || "", autocomplete: "off" });
          return field(fd.label, inputs[fd.name]);
        }));
      }
      build();
      const submit = async () => {
        const body = { kind: kind.value, ip: ip.value, name: name.value };
        for (const [k, input] of Object.entries(inputs)) body[k] = input.value;
        try {
          const { id } = await ctx.api.post("/api/machines", body);
          m.close(); select(id); refresh();
        } catch (e) { toast(e.message, "critical"); }
      };
      const m = modal({ title: "Ajouter une machine", body: [field("Type", kind), field("Adresse", ip), field("Nom", name), extra],
        actions: [button("Annuler", () => m.close()), button("Ajouter", submit, "primary")] });
      ip.focus();
    }

    // Chaque onglet fournit { el, update(host) } : le contenu se met à jour sans détruire les champs de saisie.
    const tabs = {
      summary() {
        const box = h("div", { class: "stack" });
        return { el: box, update(x) {
          const m = x.metrics;
          if (!m) return render(box, empty(x.ok === false ? "Aucune mesure disponible" : "Première mesure en cours…"));
          const memP = m.mem_total ? (100 * m.mem_used) / m.mem_total : 0, hist = x.history || [];
          const gauge = (title, p, sub, idx) => h("div", { class: "panel" }, h("h3", null, title),
            h("div", { class: "metric" }, `${p.toFixed(1)} %`), meter(p, level(p)), h("small", null, sub),
            lineChart([{ data: hist.map((q) => q[idx]), cls: "a" }], { max: 100 }));
          render(box,
            h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))" } },
              gauge("Processeur", m.cpu, `${m.cores} cœurs`, 1),
              gauge("Mémoire", memP, `${bytes(m.mem_used)} / ${bytes(m.mem_total)}`, 2),
              h("div", { class: "panel" }, h("h3", null, "Réseau"),
                h("div", null, "Réception ", h("b", null, `${bytes(m.rx_rate)}/s`)), h("div", null, "Émission ", h("b", null, `${bytes(m.tx_rate)}/s`)),
                lineChart([{ data: hist.map((q) => q[3]), cls: "a" }, { data: hist.map((q) => q[4]), cls: "b" }]))),
            panel("Disques", (m.disks || []).length ? m.disks.map((d) => {
              const p = 100 * (1 - d.free / (d.total || 1));
              return h("div", { style: { marginBottom: "8px" } }, h("div", { class: "row" }, h("span", { class: "grow" }, d.name),
                h("small", null, `${bytes(d.total - d.free)} / ${bytes(d.total)} · ${p.toFixed(0)} %`)), meter(p, level(p)));
            }) : h("small", null, "—")),
            panel("Ports en écoute", (m.ports || []).length ? m.ports.map((p) => tag(p)) : h("small", null, "—")));
        } };
      },
      services() {
        const state = { q: "", only: "all" };
        const body = h("div");
        let last = null;
        const draw = () => {
          if (!last) return;
          const all = last.metrics?.services || [];
          const rows = all.filter((s) => (!state.q || (s.name + s.display).toLowerCase().includes(state.q)) &&
            (state.only === "all" || (state.only === "bad" ? isBad(s) : state.only === "running" ? s.state === "running" : s.state !== "running")))
            .sort((a, b) => isBad(b) - isBad(a) || a.name.localeCompare(b.name));
          render(body, rows.length ? h("table", { class: "t" },
            h("thead", null, h("tr", null, ["", "Service", "Nom affiché", "État", "Démarrage"].map((t) => h("th", null, t)))),
            h("tbody", null, rows.slice(0, 500).map((s) => h("tr", null, h("td", null, dot(s.state === "running" ? "ok" : isBad(s) ? "critical" : "off")),
              h("td", null, s.name), h("td", { class: "muted" }, s.display), h("td", { class: isBad(s) ? "t-critical" : "" }, s.state), h("td", { class: "muted" }, s.start || "—")))))
            : empty("Aucun service"));
        };
        const q = h("input", { type: "search", placeholder: "Filtrer", oninput: (e) => { state.q = e.target.value.toLowerCase(); draw(); } });
        const only = h("select", { onchange: (e) => { state.only = e.target.value; draw(); } },
          [["all", "Tous"], ["running", "Actifs"], ["stopped", "Arrêtés"], ["bad", "En défaut"]].map(([v, l]) => h("option", { value: v }, l)));
        return { el: h("div", { class: "stack" }, h("div", { class: "row" }, q, only), body), update(x) { last = x; draw(); } };
      },
      procs() {
        const box = h("div");
        return { el: box, update(x) {
          const m = x.metrics;
          render(box, m ? h("table", { class: "t" },
            h("thead", null, h("tr", null, ["PID", "Nom", "Mémoire", x.proc_cpu_unit === "s" ? "Temps CPU" : "CPU"].map((t) => h("th", null, t)))),
            h("tbody", null, (m.procs || []).map((p) => h("tr", null, h("td", { class: "mono" }, p.pid), h("td", null, p.name), h("td", null, bytes(p.mem)),
              h("td", null, x.proc_cpu_unit === "s" ? `${p.cpu.toFixed(0)} s` : `${p.cpu} %`))))) : empty("Aucune mesure"));
        } };
      },
      events() {
        const box = h("div", { class: "stack" });
        return { el: box, update(x) {
          const m = x.metrics || {};
          render(box,
            panel("Changements détectés", (x.changes || []).length ? x.changes.slice().reverse().map((c) =>
              h("div", { class: "row" }, h("small", { style: { width: "140px" } }, dateTime(c.t)), h("span", null, c.msg))) : h("small", null, "Aucun pour le moment")),
            panel("Erreurs récentes des journaux système", (m.events || []).length ? m.events.map((e) =>
              h("div", { class: "row", style: { alignItems: "flex-start" } }, h("small", { style: { width: "140px", flex: "none" } }, String(e.t).replace("T", " ").slice(0, 19)),
                h("b", { style: { flex: "none" } }, e.src), h("span", null, e.msg))) : h("small", { class: "t-ok" }, "Aucune erreur")));
        } };
      },
    };

    function drawDetail() {
      const x = HS.find((v) => v.id === selected);
      if (!x) { view = viewHost = null; return render(detail, empty(HS.length ? "Sélectionnez une machine." : "Aucune machine supervisée. Ajoutez-en une pour commencer.")); }
      if (viewHost !== x.id) buildDetail(x);
      head.update(x);
      view.update(x);
    }

    let head;
    function buildDetail(x) {
      viewHost = x.id;
      const title = h("h1", null), sub = h("small"), status = h("div"), meta = h("small");
      head = { update(v) {
        render(title, v.name, " ", h("small", null, v.ip));
        render(status, v.ok === false ? h("div", { class: "banner critical" }, `Injoignable : ${v.error}`) : null);
        const m = v.metrics;
        render(meta, m ? `${m.hostname} · ${m.os} · disponibilité ${uptime(m.uptime_s)} · ${m.nproc} processus · mesure il y a ${Math.round(Date.now() / 1000 - v.t_data)} s` : "");
      } };
      const body = h("div");
      const showTab = () => { view = tabs[tab](); render(body, view.el); };
      const bar = h("div", { class: "tabs" });
      const drawBar = () => render(bar, TABS.map(([id, label]) => h("button", { class: id === tab ? "active" : "",
        onclick: () => { tab = id; drawBar(); showTab(); view.update(HS.find((v) => v.id === viewHost)); } }, label)));
      drawBar(); showTab();
      render(detail, h("div", { class: "stack" },
        h("div", { class: "head" }, h("div", { class: "grow" }, h("div", { class: "row" }, dot(hostStatus(x)), title), meta),
          button("Retirer", async () => {
            if (!await confirmDialog(`Retirer ${x.name} de la supervision ?`)) return;
            await ctx.api.del(`/api/machines/${x.id}`); select(null); refresh();
          }, "danger")),
        status, bar, body));
    }

    function drawList() {
      render(list, HS.length ? HS.map((x) => h("div", { class: `item ${x.id === selected ? "sel" : ""}`, onclick: () => select(x.id) },
        dot(hostStatus(x)), h("div", { class: "grow" }, h("div", null, x.name),
          h("small", null, x.ip, x.metrics ? ` · CPU ${x.metrics.cpu.toFixed(0)} %` : "")),
        h("small", null, (types.find((t) => t.kind === x.kind)?.label || x.kind).split(" ")[0]))) : h("div", { class: "empty" }, "Aucune machine"));
    }

    function draw() {
      if (!selected && HS.length) selected = HS[0].id;
      drawList(); drawDetail();
    }

    async function refresh() {
      const d = await ctx.api.get("/api/machines");
      HS = d.hosts; types = d.types;
      draw();
    }
    return ctx.poll(refresh, 3000);
  },
};
