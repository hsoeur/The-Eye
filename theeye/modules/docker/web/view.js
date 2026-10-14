import { h, render } from "/js/core/dom.js";
import { lineChart, meter } from "/js/core/chart.js";
import { button, confirmDialog, dot, empty, kv, modal, toast } from "/js/core/ui.js";

const stateDot = (c) => (c.fault ? "critical" : c.state === "running" ? "ok" : "off");
const STATE_FILTERS = { all: "Tous", running: "Actifs", stopped: "Arrêtés", fault: "En défaut" };

export default {
  mount(el, ctx) {
    let D = null, selected = ctx.sub[0] || null;
    const f = { q: "", state: "all" };
    const collapsed = new Set();

    const summary = h("small", { class: "grow", style: { textAlign: "right" } });
    const search = h("input", { type: "search", placeholder: "Rechercher", "aria-label": "Rechercher", oninput: (e) => { f.q = e.target.value.toLowerCase(); draw(); } });
    const stateSel = h("select", { "aria-label": "État", onchange: (e) => { f.state = e.target.value; draw(); } },
      Object.entries(STATE_FILTERS).map(([k, v]) => h("option", { value: k }, v)));
    const table = h("div");
    const aside = h("div", { class: "aside" });
    render(el, h("div", { class: "toolbar" }, search, stateSel, summary),
      h("div", { class: "split" }, h("div", { class: "main" }, table), aside));

    ctx.onRoute?.((sub) => { selected = sub[0] || null; draw(); });
    const select = (id) => { selected = id; ctx.navigate(id ? `docker/${id}` : "docker"); draw(); };

    function matches(c) {
      if (f.q && ![c.name, c.image, c.project].join(" ").toLowerCase().includes(f.q)) return false;
      return f.state === "all" || (f.state === "running" && c.state === "running") ||
        (f.state === "stopped" && c.state !== "running") || (f.state === "fault" && c.fault);
    }

    function row(c) {
      const up = c.state === "running";
      return h("tr", { class: `click ${c.id === selected ? "sel" : ""}`, onclick: () => select(c.id) },
        h("td", null, dot(stateDot(c))), h("td", null, c.name), h("td", { class: "muted" }, c.image),
        h("td", null, c.status), h("td", { class: "num" }, up ? `${c.cpu.toFixed(1)} %` : "—"),
        h("td", { class: "num" }, up ? `${c.mem_pct.toFixed(1)} %` : "—"), h("td", { class: "muted" }, c.ports || "—"));
    }

    function drawTable(list) {
      const groups = {};
      list.forEach((c) => (groups[c.project || ""] ||= []).push(c));
      const names = Object.keys(groups).sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
      if (!names.length) return render(table, empty("Aucun container"));
      render(table, h("table", { class: "t" },
        h("thead", null, h("tr", null, ["", "Nom", "Image", "État", "CPU", "Mémoire", "Ports"].map((t, i) => h("th", { class: i === 4 || i === 5 ? "num" : "" }, t)))),
        names.map((p) => {
          const l = groups[p], run = l.filter((c) => c.state === "running").length, bad = l.filter((c) => c.fault).length;
          const open = !collapsed.has(p);
          return h("tbody", null,
            h("tr", { class: "group", onclick: () => { open ? collapsed.add(p) : collapsed.delete(p); draw(); } },
              h("td", { colspan: 7 }, `${open ? "▾" : "▸"} ${p || "Hors stack"}  `,
                h("small", null, `${run}/${l.length} actifs`, bad ? ` · ${bad} en défaut` : ""))),
            open && l.map(row));
        })));
    }

    function drawAside() {
      const c = D.containers.find((x) => x.id === selected);
      if (!c) return render(aside, h("p", { class: "muted" }, "Sélectionnez un container pour voir ses détails."));
      const up = c.state === "running", hist = D.history[c.id] || [];
      const act = (a, label, cls) => button(label, async () => {
        if (a !== "start" && !await confirmDialog(`${label} « ${c.name} » ?`)) return;
        try { await ctx.api.post("/api/docker/action", { id: c.id, action: a }); toast(`${label} : demandé`, "ok"); refresh(); }
        catch (e) { toast(e.message, "critical"); }
      }, cls);
      render(aside, h("div", { class: "stack" },
        h("div", { class: "row" }, dot(stateDot(c)), h("h2", null, c.name)),
        kv([["Image", c.image], ["État", c.status], ["Santé", c.health || "—"], ["Stack", c.project || "—"], ["Ports", c.ports || "—"], ["Identifiant", c.id]]),
        up && h("div", { class: "stack" },
          h("div", null, h("div", { class: "row" }, h("span", { class: "grow" }, "CPU"), h("b", null, `${c.cpu.toFixed(1)} %`)), meter(c.cpu)),
          h("div", null, h("div", { class: "row" }, h("span", { class: "grow" }, "Mémoire"), h("b", null, `${c.mem_pct.toFixed(1)} %`)),
            meter(c.mem_pct), h("small", null, c.mem)),
          lineChart([{ data: hist.map((p) => p[1]), cls: "a" }, { data: hist.map((p) => p[2]), cls: "b" }], { max: 100 }),
          h("small", null, "CPU (bleu) · mémoire (orange) · ", `Réseau ${c.net} · Disque ${c.blk} · ${c.pids} processus`)),
        h("div", { class: "row" }, button("Logs", () => openLogs(c)),
          D.actions && [up ? act("stop", "Arrêter") : act("start", "Démarrer"), up && act("restart", "Redémarrer")])));
    }

    function openLogs(c) {
      const pre = h("pre", { class: "logs" }, "Chargement…");
      let timer;
      const m = modal({ title: `Logs — ${c.name}`, body: pre, wide: true, onclose: () => clearInterval(timer) });
      const load = async () => {
        try {
          const nearBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
          pre.textContent = (await ctx.api.get(`/api/docker/logs?id=${c.id}`)).logs || "(vide)";
          if (nearBottom) pre.scrollTop = pre.scrollHeight;
        } catch (e) { pre.textContent = e.message; }
      };
      load().then(() => { pre.scrollTop = pre.scrollHeight; });
      timer = setInterval(load, 3000);
      return m;
    }

    function draw() {
      if (!D) return;
      if (!D.available) {
        summary.textContent = "";
        render(table, empty(`Docker indisponible : ${D.error}`));
        return render(aside);
      }
      const cs = D.containers, run = cs.filter((c) => c.state === "running").length, bad = cs.filter((c) => c.fault).length;
      summary.textContent = `${cs.length} containers · ${run} actifs · ${cs.length - run} arrêtés · ${bad} en défaut`;
      drawTable(cs.filter(matches).sort((a, b) => a.name.localeCompare(b.name)));
      drawAside();
    }

    async function refresh() { D = await ctx.api.get("/api/docker"); draw(); }
    return ctx.poll(refresh, 2000);
  },
};
