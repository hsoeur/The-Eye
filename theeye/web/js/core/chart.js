import { h, svg } from "./dom.js";

// Courbes SVG légères. series : [{ data: number[], cls: "a"|"b" }]
export function lineChart(series, { max } = {}) {
  const all = series.flatMap((s) => s.data);
  const top = max ?? Math.max(10, ...all);
  const el = svg("svg", { class: "chart", viewBox: "0 0 100 30", preserveAspectRatio: "none" });
  el.append(svg("line", { x1: 0, y1: 29.5, x2: 100, y2: 29.5 }));
  for (const s of series) {
    if (s.data.length < 2) continue;
    const step = 100 / Math.max(1, s.data.length - 1);
    const pts = s.data.map((v, i) => `${(i * step).toFixed(2)},${(28 - (Math.min(v, top) / top) * 26).toFixed(2)}`);
    el.append(svg("polyline", { class: s.cls || "a", points: pts.join(" ") }));
  }
  return el;
}

export function meter(percent, lvl) {
  const p = Math.max(0, Math.min(100, percent || 0));
  return h("div", { class: "meter" }, h("i", { class: lvl || "", style: { width: p + "%" } }));
}
