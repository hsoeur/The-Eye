import { h, render } from "./dom.js";

export const dot = (status) => h("span", { class: `dot ${status || ""}`, title: status || "" });

export const panel = (title, body, extra) => h("section", { class: "panel" }, title && h("h3", null, title, extra), body);

export const empty = (text) => h("div", { class: "empty" }, text);

export const tag = (text) => h("span", { class: "tag" }, text);

export function button(label, onclick, cls = "") {
  return h("button", { class: cls, onclick, type: "button" }, label);
}

export function field(label, input) {
  return h("label", { class: "field" }, label, input);
}

export function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
}

export function toast(message, kind = "info") {
  const el = h("div", { class: `toast ${kind}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "critical" ? 8000 : 4000);
}

export function modal({ title, body, actions = [], wide = false, onclose }) {
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); onclose?.(); };
  const onKey = (e) => e.key === "Escape" && close();
  const back = h("div", { class: "modal-back", onclick: (e) => e.target === back && close() },
    h("div", { class: `modal${wide ? " wide" : ""}`, role: "dialog", "aria-label": title },
      h("header", null, h("h2", { class: "grow" }, title), button("Fermer", close)),
      h("div", { class: "body" }, body),
      actions.length ? h("footer", null, actions) : null));
  document.addEventListener("keydown", onKey);
  document.body.append(back);
  return { close, el: back };
}

// Remplace un bloc seulement si son contenu a changé, afin de conserver défilement et focus.
export function keyedRender(el, key, build) {
  if (el.dataset.key === key) return false;
  el.dataset.key = key;
  render(el, build());
  return true;
}

export function confirmDialog(message) {
  return new Promise((resolve) => {
    const m = modal({
      title: "Confirmation", body: h("p", null, message),
      actions: [button("Annuler", () => { m.close(); resolve(false); }),
                button("Confirmer", () => { m.close(); resolve(true); }, "primary")],
      onclose: () => resolve(false),
    });
  });
}
