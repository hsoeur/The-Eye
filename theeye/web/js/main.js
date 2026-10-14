import { api } from "./core/api.js";
import { h, render } from "./core/dom.js";
import { dot, empty, toast } from "./core/ui.js";

const nav = document.getElementById("nav");
const view = document.getElementById("view");
let modules = [];
let version = "";
let current = null;     // { id, cleanup, timers }
let navToken = 0;

const overview = { id: "overview", label: "Vue d'ensemble", entry: "/js/views/overview.js" };

function parseRoute() {
  const [id = "overview", ...sub] = location.hash.replace(/^#\/?/, "").split("/");
  return { id: id || "overview", sub: sub.map(decodeURIComponent) };
}

export const navigate = (path) => { location.hash = "#/" + path; };

function renderNav(activeId) {
  const items = [overview, ...modules];
  render(nav,
    h("div", { class: "brand" }, "The Eye"),
    h("ul", null, items.map((m) => h("li", null,
      h("a", { href: `#/${m.id}`, class: m.id === activeId ? "active" : "" },
        dot(m.id === "overview" ? worst() : m.health?.status), m.label)))),
    h("div", { class: "foot" }, version && `v${version}`));
}

const worst = () => ["critical", "warning", "ok"].find((s) => modules.some((m) => m.health?.status === s)) || "unknown";

async function refreshModules() {
  try {
    const data = await api.get("/api/modules");
    modules = data.modules;
    version = data.version;
    renderNav(parseRoute().id);
  } catch { /* le serveur peut redémarrer : on réessaie au prochain cycle */ }
}

function makeContext(sub) {
  const timers = [];
  const ctx = {
    api, sub, navigate, toast, modules,
    poll(fn, ms) {
      const run = async () => {
        if (document.hidden) return;
        try { await fn(); } catch (e) { console.error(e); }
      };
      run();
      const id = setInterval(run, ms);
      timers.push(id);
      return () => clearInterval(id);
    },
  };
  return { ctx, dispose: () => timers.forEach(clearInterval) };
}

async function show() {
  const token = ++navToken;
  const { id, sub } = parseRoute();
  if (current && current.id === id && current.sub.join("/") !== sub.join("/")) {
    // Même module, autre sous-route : le module gère via ctx.onRoute s'il le souhaite.
    current.sub = sub;
    current.onRoute?.(sub);
    return;
  }
  teardown();
  const target = [overview, ...modules].find((m) => m.id === id) || overview;
  renderNav(target.id);
  render(view);
  const { ctx, dispose } = makeContext(sub);
  current = { id: target.id, sub, dispose, cleanup: null };
  try {
    const mod = (await import(target.entry)).default;
    if (token !== navToken) return dispose();
    ctx.onRoute = (fn) => { current.onRoute = fn; };
    current.cleanup = await mod.mount(view, ctx);
  } catch (e) {
    console.error(e);
    render(view, h("div", { class: "page" }, empty(`Impossible d'afficher « ${target.label} » : ${e.message}`)));
  }
}

function teardown() {
  if (!current) return;
  current.dispose?.();
  try { current.cleanup?.(); } catch (e) { console.error(e); }
  current = null;
}

window.addEventListener("hashchange", show);
await refreshModules();
setInterval(refreshModules, 10000);
show();
