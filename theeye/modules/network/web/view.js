import { h, render } from "/js/core/dom.js";
import { ago, dateTime } from "/js/core/format.js";
import { button, confirmDialog, dot, empty, field, kv, tag, toast } from "/js/core/ui.js";

const TYPES = { router: "Routeur", switch: "Switch", server: "Serveur", windows: "Windows", linux: "Linux",
  printer: "Imprimante", plc: "Automate", vm: "Machine virtuelle", database: "Base de données", web: "Web",
  iot: "IoT", unknown: "Inconnu" };
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nameOf = (d) => d.label || d.hostname || d.ip;

let visLoaded;
const loadVis = () => visLoaded ||= new Promise((resolve, reject) => {
  const s = document.createElement("script");
  s.src = "/modules/network/vendor/vis-network.min.js";
  s.onload = resolve; s.onerror = () => reject(new Error("bibliothèque de carte introuvable"));
  document.head.append(s);
});

const inNet = (ip, cidr) => {
  const [base, bits] = cidr.split("/");
  const n = (s) => s.split(".").reduce((x, y) => x * 256 + +y, 0);
  const mask = +bits ? (~0 << (32 - +bits)) >>> 0 : 0;
  return ((n(ip) & mask) >>> 0) === ((n(base) & mask) >>> 0);
};

export default {
  async mount(el, ctx) {
    await loadVis();
    let S = null, selected = ctx.sub[0] || null, mode = "map", mapSig = "", asideKey = "";
    const f = { q: "", type: "", off: true };

    const scanBtn = button("Scanner", scan, "primary");
    const cidr = h("input", { placeholder: "CIDR (ex. 10.0.0.0/24) — vide : automatique", size: 34, "aria-label": "Plages à scanner" });
    const search = h("input", { type: "search", placeholder: "Rechercher", "aria-label": "Rechercher", oninput: (e) => { f.q = e.target.value.toLowerCase(); redraw(); } });
    const typeSel = h("select", { "aria-label": "Type", onchange: (e) => { f.type = e.target.value; redraw(); } });
    const offBox = h("input", { type: "checkbox", checked: true, onchange: (e) => { f.off = e.target.checked; redraw(); } });
    const stats = h("small", { class: "grow", style: { textAlign: "right" } });
    const modeBtns = { map: button("Carte", () => setMode("map")), list: button("Liste", () => setMode("list")) };
    const bar = h("i");
    const mapEl = h("div", { id: "map" });
    const listEl = h("div", { style: { display: "none" } });
    const aside = h("div", { class: "aside" });

    render(el,
      h("div", { class: "toolbar" }, scanBtn, cidr, search, typeSel,
        h("label", { class: "check" }, offBox, "Hors ligne"), h("span", { class: "row" }, modeBtns.map, modeBtns.list), stats),
      h("div", { class: "progress" }, bar),
      h("div", { class: "split" }, h("div", { class: "main" }, mapEl, listEl), aside));

    const nodes = new vis.DataSet(), edges = new vis.DataSet();
    const net = new vis.Network(mapEl, { nodes, edges }, {
      physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -70, springLength: 110 }, stabilization: { iterations: 150 } },
      nodes: { shape: "box", margin: 8, borderWidth: 1, font: { size: 12 } },
      edges: { smooth: { type: "continuous" }, width: 1 },
      interaction: { hover: true },
    });
    net.once("stabilizationIterationsDone", () => net.fit());
    net.on("click", (p) => select(p.nodes[0] && S?.devices[p.nodes[0]] ? p.nodes[0] : null));

    function setMode(m) {
      mode = m;
      mapEl.style.display = m === "map" ? "" : "none";
      listEl.style.display = m === "list" ? "" : "none";
      modeBtns.map.classList.toggle("primary", m === "map");
      modeBtns.list.classList.toggle("primary", m === "list");
      if (m === "map") net.redraw();
      redraw();
    }

    function select(ip) {
      selected = ip;
      ctx.navigate(ip ? `network/${ip}` : "network");
      renderAside(true);
      if (mode === "list") renderList();
    }
    ctx.onRoute?.((sub) => { selected = sub[0] || null; renderAside(true); });

    async function scan() {
      const cidrs = cidr.value.split(/[ ,;]+/).filter(Boolean);
      try { await ctx.api.post("/api/network/scan", { cidrs }); refresh(); }
      catch (e) { toast(e.message, "critical"); }
    }

    function visible() {
      return Object.values(S.devices).filter((d) => (f.off || d.online) && (!f.type || d.type === f.type) &&
        (!f.q || [d.ip, d.hostname, d.label, d.vendor, d.mac, TYPES[d.type]].join(" ").toLowerCase().includes(f.q)));
    }

    function drawMap(devs) {
      const sig = JSON.stringify([devs.map((d) => [d.ip, nameOf(d), d.online, d.type, d.new, d.is_gateway]), S.subnets]);
      if (sig === mapSig) return;
      mapSig = sig;
      const bg = css("--surface-2"), border = css("--border"), text = css("--text"), muted = css("--muted");
      const ok = css("--ok"), warn = css("--warn"), accent = css("--accent");
      const want = new Map();
      (S.subnets || []).forEach((s) => want.set("net:" + s, { id: "net:" + s, label: s, shape: "ellipse",
        color: { background: bg, border: accent }, font: { color: text, size: 13 } }));
      devs.forEach((d) => want.set(d.ip, {
        id: d.ip, label: `${nameOf(d)}\n${d.ip}${d.type !== "unknown" ? "\n" + TYPES[d.type] : ""}`,
        color: { background: bg, border: d.new ? warn : d.online ? ok : border, highlight: { background: bg, border: accent } },
        borderWidth: d.new ? 3 : d.is_gateway ? 2 : 1, shapeProperties: { borderDashes: d.online ? false : [4, 4] },
        font: { color: d.online ? text : muted, size: d.is_gateway ? 14 : 12 },
      }));
      nodes.update([...want.values()]);
      nodes.remove(nodes.getIds().filter((id) => !want.has(id)));
      const nets = S.subnets || [];
      edges.clear();
      edges.add(devs.flatMap((d) => {
        const n = nets.find((c) => inNet(d.ip, c));
        return n ? [{ id: "e:" + d.ip, from: "net:" + n, to: d.ip, width: d.is_gateway ? 3 : 1, dashes: !d.online,
          color: { color: border, highlight: accent } }] : [];
      }));
    }

    function renderList() {
      const rows = visible().sort((a, b) => a.ip.split(".").reduce((x, y) => x * 256 + +y, 0) - b.ip.split(".").reduce((x, y) => x * 256 + +y, 0));
      render(listEl, rows.length ? h("table", { class: "t" },
        h("thead", null, h("tr", null, ["", "Nom", "Adresse IP", "Type", "Fabricant", "Ports", "Dernière vue"].map((t) => h("th", null, t)))),
        h("tbody", null, rows.map((d) => h("tr", { class: `click ${d.ip === selected ? "sel" : ""}`, onclick: () => select(d.ip) },
          h("td", null, dot(d.online ? "ok" : "off")), h("td", null, nameOf(d), d.new && h("span", { class: "t-warning" }, "  nouveau")),
          h("td", { class: "mono" }, d.ip), h("td", null, TYPES[d.type] || d.type), h("td", null, d.vendor || "—"),
          h("td", null, (d.ports || []).join(", ") || "—"), h("td", null, ago(d.last_seen, S.now)))))) : empty("Aucun équipement"));
    }

    function renderAside(force) {
      const d = S && S.devices[selected];
      const key = selected + JSON.stringify(d || null);
      if (!force && key === asideKey) return;
      if (!force && aside.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
      asideKey = key;
      if (!d) return render(aside, h("p", { class: "muted" }, "Sélectionnez un équipement pour voir ses détails."));
      const label = h("input", { value: d.label || "", maxlength: 80, placeholder: d.hostname || d.ip });
      const type = h("select", null, Object.entries(TYPES).map(([k, v]) => h("option", { value: k, selected: k === d.type }, v)));
      render(aside, h("div", { class: "stack" },
        h("div", { class: "row" }, dot(d.online ? "ok" : "off"), h("h2", null, nameOf(d))),
        h("small", null, d.online ? "En ligne" : "Hors ligne", d.is_self && " · cette machine", d.new && " · nouvel équipement"),
        kv([["Adresse IP", d.ip], ["MAC", d.mac || "—"], ["Fabricant", d.vendor || "inconnu"], ["Hôte", d.hostname || "—"],
          ["TTL", d.ttl || "—"], ["Première vue", dateTime(d.first_seen)], ["Dernière vue", ago(d.last_seen, S.now)]]),
        h("div", null, h("h3", { style: { marginBottom: "6px" } }, "Ports ouverts"),
          (d.ports || []).length ? d.ports.map((p) => tag(`${p} ${S.ports[p] || ""}`.trim())) : h("small", null, "aucun")),
        field("Nom personnalisé", label), field("Type", type),
        h("div", { class: "row" },
          button("Enregistrer", async () => {
            try { await ctx.api.post("/api/network/device", { ip: d.ip, label: label.value, type: type.value }); toast("Enregistré", "ok"); refresh(); }
            catch (e) { toast(e.message, "critical"); }
          }, "primary"),
          button("Oublier", async () => {
            if (!await confirmDialog(`Oublier ${nameOf(d)} ? Il réapparaîtra au prochain scan s'il est présent.`)) return;
            await ctx.api.post("/api/network/forget", { ip: d.ip }); select(null); refresh();
          }, "danger"))));
    }

    function redraw() {
      if (!S) return;
      const all = Object.values(S.devices), on = all.filter((d) => d.online).length;
      stats.textContent = `${all.length} équipements · ${on} en ligne · ${all.length - on} hors ligne · ${all.filter((d) => d.new).length} nouveaux`;
      const types = [...new Set(all.map((d) => d.type))].sort();
      if (typeSel.dataset.k !== types.join()) {
        typeSel.dataset.k = types.join();
        render(typeSel, h("option", { value: "" }, "Tous les types"),
          types.map((t) => h("option", { value: t, selected: t === f.type }, TYPES[t] || t)));
      }
      const devs = visible();
      drawMap(devs);
      if (mode === "list") renderList();
      renderAside(false);
    }

    async function refresh() {
      S = await ctx.api.get("/api/network/state");
      const p = S.progress;
      bar.style.width = p.running && p.total ? `${(100 * p.done) / p.total}%` : "0";
      scanBtn.textContent = p.running ? `Scan : ${p.phase} ${p.done}/${p.total}` : "Scanner";
      scanBtn.disabled = p.running;
      redraw();
    }

    setMode("map");
    const stop = ctx.poll(refresh, 2000);
    return () => { stop(); net.destroy(); };
  },
};
