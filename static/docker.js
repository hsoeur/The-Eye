let D = null, tab = "net", logTimer = null;
const collapsed = new Set();
const show = (id, on, d = "flex") => $(id).style.display = on ? d : "none";

function setTab(t) {
  tab = t;
  show("main", t === "net"); show("bar", t === "net", "block"); show("dock", t === "dock", "block");
  show("netctl", t === "net", "contents"); show("hostv", t === "host");
  if (t === "net") net.fit();
  refreshDocker(); if (window.refreshHosts) refreshHosts();
}
$("tabhost").onclick = () => setTab("host");
$("tabnet").onclick = () => setTab("net");
$("tabdock").onclick = () => setTab("dock");

function spark(cv, hist) {
  const w = cv.width = cv.clientWidth * 2, h = cv.height = 80, g = cv.getContext("2d");
  g.clearRect(0, 0, w, h);
  [[1, "#4fd1c5"], [2, "#ffd24a"]].forEach(([k, col]) => {
    if (hist.length < 2) return;
    const max = k === 1 ? Math.max(10, ...hist.map(p => p[1])) : 100;
    g.beginPath(); g.strokeStyle = col; g.lineWidth = 2;
    hist.forEach((p, i) => { const x = i / 89 * w + (w - (hist.length - 1) / 89 * w), y = h - 4 - p[k] / max * (h - 8); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  });
}

function renderDocker() {
  if (!D) return;
  if (!D.available) {
    $("dsum").innerHTML = `<span class="stat">🔴 Docker indisponible : ${esc(D.error)}</span>`;
    $("dgrid").innerHTML = ""; return;
  }
  const cs = D.containers, run = cs.filter(c => c.state === "running"), bad = cs.filter(c => c.health === "unhealthy" || ["exited", "dead"].includes(c.state) && /\((?!0\))\d+\)/.test(c.status));
  const cpu = run.reduce((a, c) => a + c.cpu, 0);
  $("dsum").innerHTML = `<span class="stat">🐳 ${cs.length} containers</span><span class="stat">🟢 ${run.length} actifs</span><span class="stat">⚫ ${cs.length - run.length} arrêtés</span><span class="stat">🔴 ${bad.length} en erreur</span><span class="stat">⚙️ CPU ${cpu.toFixed(1)}%</span><span class="stat">🕒 ${Math.round(D.now - D.t)}s</span>`;
  cs.sort((a, b) => a.name.localeCompare(b.name));
  const groups = {};
  cs.forEach(c => (groups[c.project || ""] ||= []).push(c));
  const card = c => {
    const up = c.state === "running", cls = c.health === "unhealthy" || bad.includes(c) ? "bad" : up ? "" : "stopped";
    const act = D.actions ? `<button data-a="${up ? "stop" : "start"}" data-id="${c.id}">${up ? "⏹ Stop" : "▶ Start"}</button><button data-a="restart" data-id="${c.id}">🔄</button>` : "";
    return `<div class="card ${cls}"><h4>${up ? "🟢" : "⚫"} ${esc(c.name)}</h4>
    <small>${esc(c.image)}</small><br>
    ${esc(c.status)} ${c.health === "unhealthy" ? "❌" : c.health === "healthy" ? "💚" : ""}<br><small>${esc(c.ports) || "aucun port"}</small>
    ${up ? `<div>CPU ${c.cpu.toFixed(1)}%</div><div class="bw"><i style="width:${Math.min(100, c.cpu)}%"></i></div>
    <div>RAM ${esc(c.mem)} (${c.mem_pct.toFixed(1)}%)</div><div class="bw"><i style="width:${c.mem_pct}%;background:#ffd24a"></i></div>
    <small>Net ${esc(c.net)} · Disque ${esc(c.blk)} · PIDs ${esc(c.pids)}</small><canvas data-h="${c.id}"></canvas>` : ""}
    <div><button data-a="logs" data-id="${c.id}" data-n="${esc(c.name)}">📜 Logs</button>${act}</div></div>`;
  };
  const names = Object.keys(groups).sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
  $("dgrid").innerHTML = names.map(p => {
    const l = groups[p], r = l.filter(c => c.state === "running"), nb = l.filter(c => bad.includes(c) || c.health === "unhealthy").length;
    const ico = nb ? "🔴" : r.length === l.length ? "🟢" : r.length ? "🟠" : "⚫";
    const open = !collapsed.has(p);
    return `<section class="stack"><div class="shead" data-p="${esc(p)}">${open ? "▼" : "▶"} ${ico} ${p ? "📦 " + esc(p) : "🐳 Containers hors stack"}
      <span class="stat">${r.length}/${l.length} actifs</span>${nb ? `<span class="stat">🔴 ${nb} en erreur</span>` : ""}
      <span class="stat">⚙️ ${r.reduce((a, c) => a + c.cpu, 0).toFixed(1)}% CPU</span>
      <span class="stat">🧠 ${r.reduce((a, c) => a + c.mem_pct, 0).toFixed(1)}% RAM</span></div>
      ${open ? `<div class="sgrid">${l.map(card).join("")}</div>` : ""}</section>`;
  }).join("");
  const grid = $("dgrid");
  grid.querySelectorAll("canvas").forEach(cv => spark(cv, D.history[cv.dataset.h] || []));
}

async function openLogs(id, name) {
  show("modal", true, "block"); $("mtitle").textContent = "📜 " + name;
  const load = async () => {
    const pre = $("mlogs"), bottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
    pre.textContent = (await (await fetch("/api/docker/logs?id=" + id)).json()).logs || "(vide)";
    if (bottom) pre.scrollTop = pre.scrollHeight;
  };
  await load(); $("mlogs").scrollTop = $("mlogs").scrollHeight;
  clearInterval(logTimer); logTimer = setInterval(load, 3000);
}
$("mclose").onclick = () => { show("modal", false); clearInterval(logTimer); };

$("dgrid").onclick = async e => {
  const hd = e.target.closest(".shead");
  if (hd) { const p = hd.dataset.p; collapsed.has(p) ? collapsed.delete(p) : collapsed.add(p); return renderDocker(); }
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.a === "logs") return openLogs(b.dataset.id, b.dataset.n);
  b.disabled = true;
  const r = await post("/api/docker/action", { id: b.dataset.id, action: b.dataset.a });
  if (!r.ok) alert((await r.json()).out || "Échec");
  refreshDocker();
};

async function refreshDocker() {
  if (tab !== "dock") return;
  try { D = await (await fetch("/api/docker")).json(); renderDocker(); } catch (e) { }
}
setInterval(refreshDocker, 2000);
