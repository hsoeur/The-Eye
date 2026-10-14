const ICONS = {router:"🌐",switch:"🔀",server:"🗄️",windows:"🖥️",linux:"🐧",printer:"🖨️",plc:"🏭",vm:"☁️",
  database:"🛢️",web:"🕸️",iot:"🍓",unknown:"❓"};
const $ = id => document.getElementById(id);
let S = null, nodes = new vis.DataSet(), edges = new vis.DataSet(), net, selected = null;

net = new vis.Network($("net"), {nodes, edges}, {
  physics:{solver:"forceAtlas2Based",forceAtlas2Based:{gravitationalConstant:-70,springLength:110},stabilization:{iterations:150}},
  nodes:{shape:"box",margin:8,borderWidth:2,font:{color:"#fff",size:14,multi:true},shadow:true},
  edges:{color:{color:"#4a5a99",highlight:"#4fd1c5"},smooth:{type:"continuous"}},
  interaction:{hover:true}});
net.on("click", p => { selected = p.nodes[0] || null; renderSide(); });

function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function ago(t){const s=S.now-t;return s<90?"à l'instant":s<5400?Math.round(s/60)+" min":s<86400?Math.round(s/3600)+" h":Math.round(s/86400)+" j"}

function draw(){
  const q = $("q").value.toLowerCase(), f = $("f").value, showOff = $("off").checked;
  const devs = Object.values(S.devices).filter(d =>
    (showOff || d.online) && (!f || d.type === f) &&
    (!q || [d.ip,d.hostname,d.label,d.vendor,d.mac,d.type].join(" ").toLowerCase().includes(q)));
  const want = new Map();
  (S.subnets||[]).forEach(s => want.set("net:"+s, {id:"net:"+s,label:"🕸️ "+s,color:{background:"#3b2a7a",border:"#8b6cff"},shape:"ellipse",font:{color:"#fff",size:16}}));
  devs.forEach(d => {
    const name = d.label || d.hostname || d.ip;
    const dot = d.online ? "🟢" : "🔴";
    want.set(d.ip, {id:d.ip, label:`${ICONS[d.type]||"❓"} ${name}\n${dot} ${d.ip}${d.vendor?"\\n🏷️ "+d.vendor.slice(0,28):""}`,
      color:{background:d.online?"#1d3b5c":"#3a2a2a",border:d.new?"#ffd24a":d.online?"#4fd1c5":"#a14"},
      borderWidth:d.new?4:2, opacity:d.online?1:.5,
      size:d.type==="router"?30:20, font:{color:"#fff",size:d.type==="router"?18:13}});
  });
  nodes.update([...want.values()]);
  nodes.remove(nodes.getIds().filter(id => !want.has(id)));
  const E = [];
  const nets = (S.subnets||[]).map(s => ({s, p:s.split("/")[0].split(".").map(Number), bits:+s.split("/")[1]}));
  const inNet = (ip,n) => { const a=ip.split(".").reduce((x,y)=>x*256+ +y,0), b=n.p.reduce((x,y)=>x*256+y,0), m=n.bits?(~0<<(32-n.bits))>>>0:0; return ((a&m)>>>0)===((b&m)>>>0); };
  devs.forEach(d => {
    const n = nets.find(n => inNet(d.ip,n)); if(!n) return;
    if (d.is_gateway) E.push({id:"g:"+d.ip,from:"net:"+n.s,to:d.ip,width:4});
    else E.push({id:"e:"+d.ip,from:S.gateway&&want.has(S.gateway)&&d.type!=="router"?"net:"+n.s:"net:"+n.s,to:d.ip,dashes:!d.online});
  });
  edges.clear(); edges.add(E);

  const all = Object.values(S.devices), on = all.filter(d=>d.online).length;
  $("stats").innerHTML = `<span class="stat">📡 ${all.length} machines</span><span class="stat">🟢 ${on}</span><span class="stat">🔴 ${all.length-on}</span><span class="stat">✨ ${all.filter(d=>d.new).length} nouvelles</span>`;
  const types = [...new Set(all.map(d=>d.type))].sort(), cur = $("f").value;
  $("f").innerHTML = '<option value="">Tous types</option>'+types.map(t=>`<option ${t===cur?"selected":""} value="${t}">${ICONS[t]||""} ${t}</option>`).join("");
}

function renderSide(){
  const d = S && S.devices[selected];
  if (!d) { $("side").innerHTML = "<i>Cliquez sur une machine…</i>"; return; }
  const ports = (d.ports||[]).map(p=>`<span class="tag">${p} ${esc(S.ports[p]||"")}</span>`).join("") || "<i>aucun</i>";
  $("side").innerHTML = `<h3>${ICONS[d.type]||""} ${esc(d.label||d.hostname||d.ip)}</h3>
  ${d.online?"🟢 en ligne":"🔴 hors-ligne"}${d.is_self?" · <b>The Eye</b>":""}${d.new?" · ✨ nouvelle":""}<br>
  IP: <b>${d.ip}</b><br>MAC: ${esc(d.mac)||"?"}<br>Fabricant: <b>${esc(d.vendor)||"inconnu"}</b><br>Hôte: ${esc(d.hostname)||"?"}<br>TTL: ${d.ttl||"?"}<br>
  Vu la 1ère fois: ${ago(d.first_seen)}<br>Dernière vue: ${ago(d.last_seen)}
  <h3>Ports ouverts</h3>${ports}
  <label>Nom perso<input id="lab" value="${esc(d.label)}" style="width:100%"></label>
  <label>Type<select id="typ" style="width:100%">${Object.keys(ICONS).map(t=>`<option ${t===d.type?"selected":""}>${t}</option>`).join("")}</select></label>
  <p><button id="sv">💾 Enregistrer</button> <button id="fg">🗑️ Oublier</button></p>`;
  $("sv").onclick = async()=>{await post("/api/device",{ip:d.ip,label:$("lab").value,type:$("typ").value});refresh()};
  $("fg").onclick = async()=>{await post("/api/forget",{ip:d.ip});selected=null;refresh()};
}

const post = (u,b) => fetch(u,{method:"POST",body:JSON.stringify(b)});
async function refresh(){
  S = await (await fetch("/api/state")).json();
  const p = S.progress;
  $("bar").firstChild.style.width = p.running && p.total ? (100*p.done/p.total)+"%" : "0";
  $("scan").textContent = p.running ? `⏳ ${p.phase} ${p.done}/${p.total}` : "🔍 Scanner";
  $("scan").disabled = p.running;
  if (!(document.activeElement && ["lab","typ"].includes(document.activeElement.id))) { draw(); renderSide(); }
}
$("scan").onclick = async()=>{const c=$("cidr").value.split(/[ ,;]+/).filter(Boolean);
  const r = await post("/api/scan",{cidrs:c}); if(!r.ok) alert("CIDR invalide"); refresh();};
["q","f","off"].forEach(i=>$(i).oninput=()=>draw());
refresh(); setInterval(refresh, 2000);
