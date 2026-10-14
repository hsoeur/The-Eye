let HS = [], hsel = null, svcFilter = "", svcOnly = "all";
const fmtB = n => { n = +n || 0; const u = ["o", "Ko", "Mo", "Go", "To"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return n.toFixed(i > 1 ? 1 : 0) + " " + u[i]; };
const fmtUp = s => { s = +s || 0; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + " j " : "") + h + " h " + m + " min"; };
const col = p => p > 90 ? "r" : p > 75 ? "o" : "gr";
const bar = (p, c) => `<div class="bw"><i style="width:${Math.min(100, p)}%;background:${p > 90 ? "#e5484d" : p > 75 ? "#ffb454" : c || "#4fd1c5"}"></i></div>`;

$("hlist").innerHTML = `<h3>➕ Ajouter une machine</h3>
<input id="h_ip" placeholder="IP ou nom" style="width:100%;margin-bottom:4px">
<input id="h_name" placeholder="Nom affiché (optionnel)" style="width:100%;margin-bottom:4px">
<select id="h_os" style="width:100%;margin-bottom:4px"><option value="windows">Windows (WinRM)</option><option value="linux">Linux (SSH)</option></select>
<input id="h_user" placeholder="Utilisateur (vide = compte courant)" style="width:100%;margin-bottom:4px">
<input id="h_pw" type="password" placeholder="Mot de passe (Windows)" style="width:100%;margin-bottom:4px">
<input id="h_key" placeholder="Clé SSH privée (Linux, optionnel)" style="width:100%;margin-bottom:4px;display:none">
<button id="h_add" style="width:100%">Ajouter</button><h3>Machines</h3><div id="hitems"></div>`;
$("h_os").onchange = () => { const w = $("h_os").value === "windows"; show("h_pw", w, "block"); show("h_key", !w, "block"); };
$("h_add").onclick = async () => {
  const r = await post("/api/hosts/add", { ip: $("h_ip").value, name: $("h_name").value, os: $("h_os").value, user: $("h_user").value, password: $("h_pw").value, key: $("h_key").value });
  const j = await r.json(); if (!r.ok) return alert(j.error);
  ["h_ip", "h_name", "h_user", "h_pw", "h_key"].forEach(i => $(i).value = ""); hsel = j.id; refreshHosts();
};

function hgauge(label, p, sub, hist, k) {
  return `<div class="g">${label}<br><b class="${col(p)}">${p.toFixed(1)}%</b>${bar(p)}<small>${sub}</small>${hist ? `<canvas data-hk="${k}"></canvas>` : ""}</div>`;
}

function renderHosts() {
  $("hitems").innerHTML = HS.map(h => `<div class="hi ${h.ok ? "ok" : h.ok === false ? "ko" : ""} ${h.id === hsel ? "sel" : ""}" data-id="${h.id}">
    ${h.ok ? "🟢" : h.ok === false ? "🔴" : "⏳"} ${h.os === "windows" ? "🪟" : "🐧"} <b>${esc(h.name)}</b><br><small>${esc(h.ip)}${h.metrics ? " · CPU " + h.metrics.cpu.toFixed(0) + "%" : ""}</small></div>`).join("") || "<i>Aucune machine</i>";
  const h = HS.find(x => x.id === hsel);
  if (!h) { $("hdet").innerHTML = "<i>Sélectionnez ou ajoutez une machine…</i>"; return; }
  const ae = document.activeElement, keep = ae && ae.id === "sf" ? ae.selectionStart : null;
  const m = h.metrics;
  let out = `<h2 style="margin:0">${h.os === "windows" ? "🪟" : "🐧"} ${esc(h.name)} <small>${esc(h.ip)}</small>
    <button id="hdel" style="float:right">🗑️ Retirer</button></h2>`;
  if (h.ok === false) out += `<p class="r">🔴 Injoignable : ${esc(h.error)}</p>`;
  if (m) {
    const mp = 100 * m.mem_used / (m.mem_total || 1), svc = m.services || [];
    const bad = svc.filter(s => s.state === "failed" || (s.start === "auto" && s.state !== "running"));
    out += `<small>${esc(m.hostname)} · ${esc(m.os)} · up ${fmtUp(m.uptime_s)} · ${m.cores} CPU · ${m.nproc} processus · mesure il y a ${Math.round(S2(h))} s</small>
    <div class="gauges">${hgauge("⚙️ CPU", m.cpu, m.cores + " cœurs", 1, 1)}${hgauge("🧠 Mémoire", mp, fmtB(m.mem_used) + " / " + fmtB(m.mem_total), 1, 2)}
    <div class="g">🌐 Réseau<br>⬇ <b>${fmtB(m.rx_rate)}/s</b><br>⬆ <b>${fmtB(m.tx_rate)}/s</b></div>
    <div class="g">🛠️ Services<br><b class="${bad.length ? "r" : "gr"}">${svc.filter(s => s.state === "running").length}</b> actifs / ${svc.length}<br>${bad.length ? `<span class="r">${bad.length} en défaut</span>` : "aucun défaut"}</div></div>
    <div class="pan"><h3>💽 Disques</h3>${(m.disks || []).map(d => { const p = 100 * (1 - d.free / (d.total || 1)); return `${esc(d.name)} — ${fmtB(d.total - d.free)} / ${fmtB(d.total)} (<span class="${col(p)}">${p.toFixed(0)}%</span>)${bar(p, "#8b6cff")}`; }).join("") || "—"}</div>
    <div class="pan"><h3>🛠️ Services ${bad.length ? `<span class="r">· ${bad.length} en défaut</span>` : ""}</h3>
      <input id="sf" placeholder="Filtrer…" value="${esc(svcFilter)}"> <select id="so">${[["all", "Tous"], ["running", "Actifs"], ["stopped", "Arrêtés"], ["bad", "En défaut"]].map(([v, l]) => `<option value="${v}" ${v === svcOnly ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div style="max-height:320px;overflow:auto;margin-top:6px"><table class="t"><tr><th>Service</th><th>Nom</th><th>État</th><th>Démarrage</th></tr>
      ${svc.filter(s => (!svcFilter || (s.name + s.display).toLowerCase().includes(svcFilter.toLowerCase())) && (svcOnly === "all" || (svcOnly === "bad" ? bad.includes(s) : svcOnly === "running" ? s.state === "running" : s.state !== "running")))
        .sort((a, b) => bad.includes(b) - bad.includes(a) || a.name.localeCompare(b.name)).slice(0, 400)
        .map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.display)}</td><td class="${s.state === "running" ? "gr" : bad.includes(s) ? "r" : ""}">${s.state === "running" ? "🟢" : bad.includes(s) ? "🔴" : "⚫"} ${esc(s.state)}</td><td>${esc(s.start)}</td></tr>`).join("")}</table></div></div>
    <div class="pan"><h3>📋 Top processus (mémoire)</h3><table class="t"><tr><th>PID</th><th>Nom</th><th>Mémoire</th><th>CPU</th></tr>
      ${(m.procs || []).map(p => `<tr><td>${p.pid}</td><td>${esc(p.name)}</td><td>${fmtB(p.mem)}</td><td>${h.os === "windows" ? p.cpu.toFixed(0) + " s" : p.cpu + " %"}</td></tr>`).join("")}</table></div>
    <div class="pan"><h3>🔌 Ports en écoute</h3>${(m.ports || []).map(p => `<span class="tag">${p}${S && S.ports && S.ports[p] ? " " + esc(S.ports[p]) : ""}</span>`).join("") || "—"}</div>
    <div class="pan"><h3>🚨 Erreurs récentes (${h.os === "windows" ? "journaux Windows, 24 h" : "journalctl"})</h3>
      ${(m.events || []).map(e => `<div><small>${esc(String(e.t).replace("T", " ").slice(0, 19))}</small> <b>${esc(e.src)}</b> ${esc(e.msg)}</div>`).join("") || "<span class='gr'>Aucune erreur 🎉</span>"}</div>`;
  }
  out += `<div class="pan"><h3>🕒 Changements détectés</h3>${(h.changes || []).slice().reverse().map(c => `<div><small>${new Date(c.t * 1000).toLocaleString()}</small> ${esc(c.msg)}</div>`).join("") || "<small>Aucun pour le moment</small>"}</div>`;
  $("hdet").innerHTML = out;
  if (m && h.history) $("hdet").querySelectorAll("canvas").forEach(cv => {
    const k = +cv.dataset.hk, w = cv.width = cv.clientWidth * 2, ht = cv.height = 80, g = cv.getContext("2d");
    g.strokeStyle = k === 1 ? "#4fd1c5" : "#ffd24a"; g.lineWidth = 2; g.beginPath();
    h.history.forEach((p, i) => { const x = i / Math.max(1, h.history.length - 1) * w, y = ht - 4 - p[k] / 100 * (ht - 8); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
  });
  if ($("hdel")) $("hdel").onclick = async () => { if (confirm("Retirer " + h.name + " ?")) { await post("/api/hosts/delete", { id: h.id }); hsel = null; refreshHosts(); } };
  if ($("sf")) {
    $("sf").oninput = e => { svcFilter = e.target.value; renderHosts(); };
    $("so").onchange = e => { svcOnly = e.target.value; renderHosts(); };
    if (keep !== null) { $("sf").focus(); $("sf").setSelectionRange(keep, keep); }
  }
}
const S2 = h => (Date.now() / 1000 - h.t_data) || 0;
$("hitems").onclick = e => { const d = e.target.closest(".hi"); if (d) { hsel = d.dataset.id; renderHosts(); } };

async function refreshHosts() {
  if (tab !== "host") return;
  try { HS = (await (await fetch("/api/hosts")).json()).hosts; if (!hsel && HS.length) hsel = HS[0].id; renderHosts(); } catch (e) { }
}
setInterval(refreshHosts, 3000);
