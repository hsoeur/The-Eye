import { h, render } from "../core/dom.js";
import { ago } from "../core/format.js";
import { dot, empty, panel } from "../core/ui.js";

const STATUS_LABEL = { ok: "Opérationnel", warning: "Attention", critical: "Alerte", unknown: "Inconnu" };

export default {
  mount(el, ctx) {
    const banner = h("div");
    const cards = h("div", { class: "grid" });
    const feed = h("div");
    render(el, h("div", { class: "page" },
      h("div", { class: "head" }, h("h1", null, "Vue d'ensemble")),
      banner, cards, panel("Activité récente", feed)));

    const card = (m) => h("div", { class: "card click", tabindex: 0, onclick: () => ctx.navigate(m.id),
      onkeydown: (e) => e.key === "Enter" && ctx.navigate(m.id) },
      h("div", { class: "row" }, dot(m.health.status), h("h2", { class: "grow" }, m.label),
        h("small", null, STATUS_LABEL[m.health.status])),
      h("p", { class: "muted" }, m.health.summary || "—"),
      h("div", { class: "row" }, (m.health.stats || []).map((s) =>
        h("div", { style: { minWidth: "72px" } }, h("div", { class: "metric" }, s.value), h("small", null, s.label)))));

    const eventRow = (e, now) => h("div", { class: "row", style: { padding: "5px 0", borderBottom: "1px solid var(--border)" } },
      dot(e.severity === "ok" ? "ok" : e.severity === "info" ? "" : e.severity),
      h("small", { style: { width: "92px" } }, ago(e.t, now)),
      h("small", { style: { width: "72px" } }, e.source),
      h("span", { class: "grow" }, e.message));

    return ctx.poll(async () => {
      const data = await ctx.api.get("/api/overview");
      const alerts = data.modules.filter((m) => ["critical", "warning"].includes(m.health.status));
      render(banner, alerts.length ? h("div", { class: `banner ${alerts.some((m) => m.health.status === "critical") ? "critical" : "warning"}` },
        alerts.map((m) => h("div", null, h("b", null, m.label), " : ", m.health.summary))) : null);
      render(cards, data.modules.map(card));
      render(feed, data.events.length ? data.events.map((e) => eventRow(e, data.now)) : empty("Aucun événement pour le moment"));
    }, 5000);
  },
};
