"""Gabarit de la visualisation 3D (cerveau.html) : 3d-force-graph (three.js) chargé depuis un CDN, données intégrées.

Sans connexion ou sans WebGL, la page le dit et renvoie vers cerveau-2d.html (100 % local) et la vue tableau."""

LIBS = (
    "https://cdn.jsdelivr.net/npm/3d-force-graph@1.80.0/dist/3d-force-graph.min.js",
    "https://unpkg.com/3d-force-graph@1.80.0/dist/3d-force-graph.min.js",
)

TEMPLATE_3D = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cerveau de Claude — 3D</title>
<style>
:root{--bg:#05070c;--glass:rgba(13,16,25,.82);--ink:#eef1f8;--ink2:#a9b2c6;--muted:#6e7890;--line:rgba(255,255,255,.10);
--chip:rgba(255,255,255,.07);--hover:rgba(255,255,255,.10);--accent:#7aa2ff;--shadow:0 10px 40px rgba(0,0,0,.45)}
:root[data-theme="light"]{--bg:#eef0f5;--glass:rgba(255,255,255,.90);--ink:#0f131b;--ink2:#3c4456;--muted:#77809a;
--line:rgba(0,0,0,.10);--chip:rgba(0,0,0,.05);--hover:rgba(0,0,0,.06);--accent:#2b5ad8;--shadow:0 10px 30px rgba(20,30,60,.16)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;overflow:hidden}
#graph{position:fixed;inset:0}
#labels{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:2}
.lbl{position:absolute;left:0;top:0;white-space:nowrap;font-size:11.5px;font-weight:600;color:var(--ink);
text-shadow:0 0 4px var(--bg),0 0 8px var(--bg),0 0 2px var(--bg);will-change:transform,opacity;display:none}
.lbl.big{font-size:13px}
.glass{background:var(--glass);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
#bar{position:fixed;left:12px;right:12px;top:12px;z-index:5;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 10px}
#bar h1{font-size:16px;margin:0 6px 0 2px;font-weight:700;white-space:nowrap}
#stats{color:var(--ink2);font-size:12.5px;margin-right:auto}
select,input[type=search],button,.btn{font:inherit;font-size:13px;color:var(--ink);background:var(--chip);border:1px solid var(--line);
border-radius:9px;padding:6px 10px;text-decoration:none;cursor:pointer}
button:hover,select:hover,.btn:hover{background:var(--hover)}
button[aria-pressed=true]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
input[type=search]{min-width:150px;flex:0 1 230px;cursor:text}
#panel{position:fixed;right:12px;top:var(--top,76px);bottom:12px;width:360px;z-index:4;padding:14px 16px;overflow:auto;display:none}
#panel.open{display:block}
#panel h2{font-size:17px;margin:2px 0 6px;overflow-wrap:anywhere}
#panel h3{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:16px 0 6px}
#panel .x{position:absolute;right:10px;top:8px;border:0;background:none;font-size:18px;color:var(--muted)}
.meta{color:var(--ink2);font-size:12.5px;display:flex;flex-wrap:wrap;gap:4px 10px}
.body{white-space:pre-wrap;font-size:13.3px;line-height:1.5;margin-top:10px;overflow-wrap:anywhere;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:12px;color:var(--ink2)}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.list button{width:100%;text-align:left;display:flex;gap:8px;align-items:flex-start;padding:6px 8px;font-size:12.8px;line-height:1.35}
.list button small{display:block;color:var(--muted);font-size:11.5px}
.list .t{flex:1;min-width:0;overflow-wrap:anywhere}
.muted{color:var(--muted)}code{font-size:12px;color:var(--ink2)}
#timeline{position:fixed;left:50%;transform:translateX(-50%);bottom:12px;z-index:4;display:none;gap:8px;align-items:center;
padding:6px 10px;width:min(440px,calc(100vw - 24px))}
#timeline input{flex:1;accent-color:var(--accent)}#timeline span{font-size:12px;color:var(--ink2);white-space:nowrap}
#timeline button{padding:3px 9px}
@media (max-width:1100px){#timeline{left:auto;right:12px;transform:none;bottom:56px}}
#legend{position:fixed;left:12px;bottom:12px;z-index:4;max-width:min(420px,calc(100vw - 24px));max-height:38vh;overflow:auto;padding:8px 10px}
#legend .row{display:flex;flex-wrap:wrap;gap:4px}
#legend button{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 8px;background:transparent;border-color:transparent}
#legend button[aria-pressed=false]{opacity:.38;text-decoration:line-through}
#legend .hint{font-size:11.5px;color:var(--muted);margin:2px 2px 4px}
#tablewrap{position:fixed;inset:var(--top,76px) 12px 12px 12px;z-index:6;display:none;overflow:auto;padding:0}
#tablewrap.open{display:block}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--glass);color:var(--ink2);font-weight:600;backdrop-filter:blur(10px)}
tr[tabindex]{cursor:pointer}tr[tabindex]:hover,tr[tabindex]:focus{background:var(--hover);outline:none}
#fallback{position:fixed;inset:0;display:none;align-items:center;justify-content:center;z-index:7;padding:16px}
#fallback .glass{max-width:520px;padding:22px 24px}
#help{position:fixed;right:12px;bottom:12px;z-index:3;font-size:11.5px;color:var(--muted);padding:6px 10px}
.scene-tip{background:var(--glass)!important;color:var(--ink)!important;border:1px solid var(--line);border-radius:10px;padding:8px 10px;
max-width:300px;font:12.5px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:var(--shadow)}
.scene-tip b{display:block;margin-bottom:2px}.scene-tip span{color:var(--ink2)}
@media (max-width:820px){#panel{left:12px;right:12px;width:auto;top:auto;height:52vh}#help{display:none}#stats{width:100%;order:9}}
</style>
</head>
<body>
<div id="graph" aria-label="Graphe 3D interactif du cerveau (la vue tableau donne le même contenu)"></div>
<div id="labels" aria-hidden="true"></div>
<div id="bar" class="glass">
  <h1>🧠 Cerveau</h1>
  <span id="stats"></span>
  <select id="view" aria-label="Vue"></select>
  <select id="color" aria-label="Couleur selon">
    <option value="comm">Couleur : communauté</option>
    <option value="type">Couleur : type</option>
    <option value="proj">Couleur : projet</option>
  </select>
  <input type="search" id="q" placeholder="Rechercher…  ( / )" aria-label="Rechercher">
  <button id="infBtn" aria-pressed="true" title="Afficher les liens déduits du contenu">Liens déduits</button>
  <button id="conBtn" aria-pressed="true" title="Concepts repérés automatiquement (outils, sujets, sigles…)">Concepts</button>
  <button id="lblBtn" aria-pressed="true" title="Étiquettes des nœuds">Étiquettes</button>
  <button id="rotBtn" aria-pressed="false" title="Rotation automatique (R)">Rotation</button>
  <button id="fitBtn" title="Recentrer (F)">Recentrer</button>
  <button id="repBtn" title="Rapport façon graphify">Rapport</button>
  <button id="tblBtn" aria-pressed="false">Tableau</button>
  <a class="btn" href="cerveau-2d.html" title="Vue 2D, fonctionne hors ligne">2D</a>
  <button id="pngBtn" title="Enregistrer la vue en image (PNG)">📷</button>
  <button id="themeBtn" title="Thème">☾</button>
</div>
<aside id="panel" class="glass" aria-live="polite"></aside>
<div id="legend" class="glass"></div>
<div id="timeline" class="glass"><button id="playBtn" title="Voir le cerveau grandir jour après jour">▶</button>
<input type="range" id="tl" min="0" max="0" value="0" aria-label="Chronologie : afficher les souvenirs jusqu'à une date"><span id="tlLabel"></span></div>
<div id="tablewrap" class="glass"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div id="help" class="glass">glisser : tourner · molette : zoom · clic droit : déplacer · clic : détails · Maj+clic : chemin</div>
<div id="fallback"><div class="glass"><h2 style="margin-top:0">Vue 3D indisponible</h2><p id="fbmsg"></p>
<p><a class="btn" href="cerveau-2d.html">Ouvrir la vue 2D (hors ligne)</a> <button id="fbTable">Vue tableau</button></p></div></div>
<script>const DATA = __DATA__;</script>
<script>
"use strict";
const LIBS = __LIBS__;
const $ = s => document.querySelector(s);
const root = document.documentElement;
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fold = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const short = (s, n) => { s = String(s || ""); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };
const PALETTE = ["#5b8cff","#ff7a45","#2fd18b","#f7c948","#c77dff","#ff5c8a","#3ad1d1","#a0e05a","#ff9f1c","#8fa3ff",
                 "#ff6f61","#4cc9f0","#e0aaff","#90be6d","#f9844a","#b8c0ff"];
const TYPES = {user:["Profil","#5b8cff"], feedback:["Règle","#c77dff"], project:["Projet","#ff7a45"], decision:["Décision","#f7c948"],
  fact:["Fait","#2fd18b"], learning:["Apprentissage","#3ad1d1"], reference:["Référence","#9aa5b8"], entity:["Entité","#ff5c8a"],
  todo:["À faire","#ff6f61"]};
const KIND = {code:"code", doc:"document", data:"données", asset:"média", other:"autre"};
const store = { get(k){ try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v){ try { localStorage.setItem(k, v); } catch (e) {} } };
const st = {view: "mem", color: "comm", inf: true, labels: true, rotate: false, q: "", hidden: new Set(),
            sel: null, hover: null, focus: null, focusLabel: ""};
let G = null, cur = null, labels = [];
const graphEl = $("#graph"), panel = $("#panel");
const COMMS = DATA.comms || [];
const commById = new Map(COMMS.map(c => [c.id, c]));
const PROJECTS = DATA.nodes.filter(n => n.t === "project");
const projIndex = new Map(PROJECTS.map((p, i) => [p.id, i]));

function hexA(hex, a){ const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map(x => x + x).join("") : h, 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }
function idOf(x){ return typeof x === "object" && x ? x.id : x; }
function dark(){ return root.getAttribute("data-theme") !== "light"; }

// ------------------------------------------------------------------ données des vues
function memData(){
  const nodes = DATA.nodes.map(n => Object.assign({}, n, {kind: "mem", name: n.title}));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = [];
  for (const e of DATA.edges) if (byId.has(e.s) && byId.has(e.t)) links.push({source: e.s, target: e.t, rel: e.r, inf: false});
  for (const e of (DATA.inf || [])) if (byId.has(e.s) && byId.has(e.t))
    links.push({source: e.s, target: e.t, rel: "déduit", inf: true, w: e.w, why: e.why, conf: e.conf});
  for (const c of (DATA.concepts || [])){  // concepts façon graphify : un nœud par outil/sujet partagé
    const members = c.members.filter(m => byId.has(m));
    if (members.length < 2) continue;
    const cn = {id: c.id, kind: "concept", name: c.label, title: c.label, ck: c.kind, members, n: members.length};
    nodes.push(cn); byId.set(cn.id, cn);
    for (const m of members) links.push({source: m, target: c.id, rel: "mentionne", con: true});
  }
  return finish(nodes, links, null);
}
function mapData(m){
  const mods = new Map((m.mods12 || []).map((x, i) => [x.key, i]));
  const top = Math.max(1e-9, ...m.nodes.map(f => f.pr || 0));
  const nodes = m.nodes.map(f => ({id: f.id, kind: "file", name: f.id.split("/").pop(), title: f.id, d: f.d, k: f.k, mod: f.mod,
    c: mods.has(f.mod) ? mods.get(f.mod) : -1, pr: (f.pr || 0) / top, lines: f.lines}));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = m.edges.filter(([s, t]) => byId.has(s) && byId.has(t)).map(([s, t]) => ({source: s, target: t, rel: "importe", inf: false}));
  return finish(nodes, links, m);
}
function finish(nodes, links, map){
  const byId = new Map(nodes.map(n => [n.id, n]));
  const adj = new Map(nodes.map(n => [n.id, new Set()]));
  for (const l of links){ adj.get(l.source).add(l.target); adj.get(l.target).add(l.source); }
  return {nodes, links, byId, adj, map};
}

// ------------------------------------------------------------------ couleurs, tailles, visibilité
function legendKey(n){
  if (n.kind === "concept") return "k:concept";
  if (n.kind === "file") return "m:" + (n.c >= 0 ? n.c : "x");
  if (st.color === "type") return "t:" + n.t;
  if (st.color === "proj") return "p:" + ((n.t === "project" ? n.id : n.p) || "-");
  const c = commById.get(n.c);
  return "c:" + (c && c.size >= 2 ? n.c : "iso");
}
function baseColor(n){
  if (n.kind === "concept") return dark() ? "#dfe6f3" : "#566079";
  if (n.kind === "file") return n.c >= 0 ? PALETTE[n.c % PALETTE.length] : "#7d8799";
  if (st.color === "type") return (TYPES[n.t] || ["", "#9aa5b8"])[1];
  if (st.color === "proj"){ const p = n.t === "project" ? n.id : n.p; return projIndex.has(p) ? PALETTE[(projIndex.get(p) + 1) % PALETTE.length] : "#8b93a7"; }
  const c = commById.get(n.c);
  return c && c.size < 2 ? "#8b93a7" : PALETTE[(n.c || 0) % PALETTE.length];
}
function nodeColor(n){ const b = baseColor(n); return st.focus && !st.focus.has(n.id) ? hexA(b, dark() ? .10 : .16) : b; }
function nodeVal(n){
  if (n.kind === "concept") return 1.6 + 1.2 * Math.sqrt(n.n || 2);
  if (n.kind === "file") return 1.2 + 16 * (n.pr || 0);
  if (n.t === "project") return 16;
  return 2 + 1.1 * (n.imp || 3) + 12 * (n.pr || 0);
}
function late(n){ return !!st.until && (n.cre || n.upd || "") > st.until; }  // chronologie : pas encore créé
function hidden(n){
  if (!n) return true;
  if (n.kind === "concept") return !st.concepts || st.hidden.has("k:concept") || !n.members.some(m => { const x = cur.byId.get(m); return x && !late(x) && !st.hidden.has(legendKey(x)); });
  if (n.kind === "mem" && late(n)) return true;
  return st.hidden.has(legendKey(n));
}
function linkVis(l){
  return (st.inf || !l.inf) && (st.concepts || !l.con) && !hidden(cur.byId.get(idOf(l.source))) && !hidden(cur.byId.get(idOf(l.target)));
}
function pairKey(a, b){ return a < b ? a + "|" + b : b + "|" + a; }
function focal(){ return st.hover || st.sel; }
function hot(l){
  if (st.path && !st.hover) return st.path.links.has(pairKey(idOf(l.source), idOf(l.target)));
  const f = focal(); return !!f && (idOf(l.source) === f.id || idOf(l.target) === f.id);
}
function linkColor(l){
  const d = dark();
  if (st.focus && !(st.focus.has(idOf(l.source)) && st.focus.has(idOf(l.target)))) return d ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.04)";
  if (hot(l)) return d ? "#ffffff" : "#1b2440";
  if (l.inf) return d ? "rgba(150,175,255,.55)" : "rgba(60,90,200,.45)";
  if (l.rel === "part_of") return d ? "rgba(255,255,255,.22)" : "rgba(0,0,0,.18)";
  if (l.con) return d ? "rgba(225,232,245,.26)" : "rgba(60,70,90,.24)";
  if (l.rel === "importe") return d ? "rgba(160,190,255,.35)" : "rgba(40,60,120,.30)";
  return d ? "rgba(255,214,120,.75)" : "rgba(170,110,0,.75)";
}

// ------------------------------------------------------------------ graphe 3D
function makeGraph(el){
  const cfg = {controlType: "orbit", rendererConfig: {antialias: true, alpha: false, preserveDrawingBuffer: true}};
  try { const g = new ForceGraph3D(el, cfg); if (g && typeof g.graphData === "function") return g; } catch (e) {}
  return ForceGraph3D(cfg)(el);
}
function tip(n){
  if (n.kind === "concept") return `<div class="scene-tip"><b>${esc(n.name)}</b><span>Concept · ${esc(n.ck)} · ${n.n} souvenirs</span></div>`;
  if (n.kind === "file") return `<div class="scene-tip"><b>${esc(n.name)}</b><span>${esc(short(n.d || n.title, 160))}</span></div>`;
  const t = TYPES[n.t] || [n.t];
  return `<div class="scene-tip"><b>${esc(n.title)}</b><span>${esc(t[0])}${n.p ? " · " + esc(n.p) : ""}</span></div>`;
}
function initGraph(){
  G = makeGraph(graphEl)
    .backgroundColor(getComputedStyle(root).getPropertyValue("--bg").trim() || "#05070c")
    .showNavInfo(false)
    .nodeId("id")
    .nodeLabel(tip)
    .nodeVal(nodeVal)
    .nodeRelSize(4)
    .nodeOpacity(.95)
    .nodeResolution(18)
    .nodeColor(nodeColor)
    .nodeVisibility(n => !hidden(n))
    .linkVisibility(l => linkVis(l))
    .linkColor(linkColor)
    .linkOpacity(.6)
    .linkWidth(l => hot(l) ? .5 : 0)
    .linkCurvature(l => l.inf ? .22 : 0)
    .linkDirectionalParticles(l => l.inf || l.con || l.rel === "part_of" ? (hot(l) ? 2 : 0) : (cur.map ? 1 : 2))
    .linkDirectionalParticleSpeed(.0045)
    .linkDirectionalParticleWidth(l => hot(l) ? 2.6 : 1.5)
    .linkDirectionalParticleColor(l => hot(l) ? (dark() ? "#ffffff" : "#1b2440") : (l.rel === "importe" ? "#9fb8ff" : "#ffd27a"))
    .d3AlphaDecay(.022).d3VelocityDecay(.32).warmupTicks(30).cooldownTime(8000)
    .onNodeHover(n => { st.hover = n || null; graphEl.style.cursor = n ? "pointer" : ""; computeFocus(); redraw(); })
    .onNodeClick((n, ev) => { if (ev && ev.shiftKey && st.sel && st.sel.id !== n.id) return showPath(st.sel, n); select(n); flyTo(n); })
    .onBackgroundClick(() => { if (st.sel){ st.sel = null; computeFocus(); redraw(); closePanel(); } })
    .onEngineStop(() => autoFit(800));
  const c = G.controls && G.controls();
  if (c && c.addEventListener) c.addEventListener("start", () => { st.userMoved = true; });
  window.addEventListener("resize", () => G.width(innerWidth).height(innerHeight));
  requestAnimationFrame(frame);
}
function forces(){
  const link = G.d3Force("link"), charge = G.d3Force("charge");
  if (cur.map){ if (link) link.distance(28); if (charge){ charge.strength(-45); charge.distanceMax && charge.distanceMax(220); } }
  else { if (link) link.distance(l => l.inf ? 95 : l.con ? 62 : l.rel === "part_of" ? 70 : 55);
         if (charge){ charge.strength(-170); charge.distanceMax && charge.distanceMax(260); } }  // les isolés restent proches
}
let redrawQueued = false;
function redraw(){
  if (redrawQueued || !G) return;
  redrawQueued = true;
  requestAnimationFrame(() => {
    redrawQueued = false;
    G.nodeColor(n => nodeColor(n)).linkColor(l => linkColor(l)).linkWidth(l => hot(l) ? .5 : 0)
     .linkDirectionalParticleWidth(l => hot(l) ? 2.6 : 1.5)
     .nodeVisibility(n => !hidden(n))
     .linkDirectionalParticles(l => l.inf || l.con || l.rel === "part_of" ? (hot(l) ? 2 : 0) : (cur.map ? 1 : 2))
     .linkVisibility(l => linkVis(l));
  });
}
function autoFit(ms){ if (G && !st.userMoved) G.zoomToFit(ms, 70); }  // cadrage tant que l'utilisateur n'a pas bougé la vue
function flyTo(n, ms){
  if (n.x == null) return;
  const d = (n.kind === "file" ? 70 : 90) + 14 * Math.sqrt(nodeVal(n)), r = Math.hypot(n.x, n.y, n.z) || 1, k = 1 + d / r;
  G.cameraPosition({x: n.x * k, y: n.y * k, z: n.z * k}, {x: n.x, y: n.y, z: n.z}, ms == null ? 1100 : ms);
}
function flyToSet(ids){
  const pts = [...ids].map(i => cur.byId.get(i)).filter(n => n && n.x != null);
  if (!pts.length) return;
  if (pts.length === 1) return flyTo(pts[0]);
  G.zoomToFit(900, 90, n => ids.has(n.id));
}

// ------------------------------------------------------------------ étiquettes (calque HTML projeté)
let labelEls = new Map(), baseLabels = new Set();
function labelEl(n){
  let el = labelEls.get(n.id);
  if (!el){
    el = document.createElement("div");
    el.className = "lbl" + (n.t === "project" ? " big" : "");
    el.textContent = short(n.name, n.kind === "file" ? 30 : 38);
    $("#labels").appendChild(el);
    labelEls.set(n.id, el);
  }
  return el;
}
function pickLabels(){
  $("#labels").textContent = "";
  labelEls = new Map();
  const score = n => n.kind === "file" ? (n.pr || 0) : (n.t === "project" ? 10 : 0) + (n.pr || 0) * 3 + (n.imp || 3) * .2;
  const arr = cur.nodes.filter(n => n.kind !== "concept").sort((a, b) => score(b) - score(a));
  const con = cur.nodes.filter(n => n.kind === "concept").sort((a, b) => b.n - a.n);
  baseLabels = new Set([...arr.slice(0, cur.map ? 18 : 11), ...con.slice(0, 7)].map(n => n.id));  // les autres : au survol
}
function frame(){
  if (G && cur){
    const show = st.labels && $("#fallback").style.display !== "flex";
    const cam = G.camera(); const e = cam.matrixWorldInverse.elements;
    const w = innerWidth, h = innerHeight, f = focal();
    const want = new Set(baseLabels);
    if (st.focus && st.focus.size <= 40) st.focus.forEach(i => want.add(i));
    if (f) want.add(f.id);
    labels = [];
    for (const [id, el] of labelEls) if (!want.has(id)) el.style.display = "none";
    for (const id of want){ const n = cur.byId.get(id); if (n) labels.push({n, el: labelEl(n)}); }
    for (const L of labels){
      const n = L.n;
      if (!show || n.x == null || hidden(n)){ L.el.style.display = "none"; continue; }
      const zc = e[2] * n.x + e[6] * n.y + e[10] * n.z + e[14];
      if (zc > -5){ L.el.style.display = "none"; continue; }
      const p = G.graph2ScreenCoords(n.x, n.y, n.z);
      if (p.x < -80 || p.y < -30 || p.x > w + 80 || p.y > h + 30){ L.el.style.display = "none"; continue; }
      let op = Math.max(.28, Math.min(1, 1.5 - (-zc) / 1500));
      if (st.focus) op = st.focus.has(n.id) ? 1 : .08;
      if (f && f.id === n.id) op = 1;
      L.el.style.display = "block";
      L.el.style.opacity = op;
      L.el.style.transform = `translate(${p.x}px,${p.y}px) translate(-50%,-160%)`;
    }
  }
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------------ focus, sélection, recherche
function computeFocus(){
  if (st.hover){ st.focus = new Set([st.hover.id, ...(cur.adj.get(st.hover.id) || [])]); return; }
  if (st.path){ st.focus = st.path.nodes; return; }
  const f = st.sel;
  if (f){ st.focus = new Set([f.id, ...(cur.adj.get(f.id) || [])]); return; }
  if (st.q){ st.focus = matches(st.q); return; }
  st.focus = st.groupFocus || null;
}
function matches(q){
  const t = fold(q), out = new Set();
  for (const n of cur.nodes){
    const hay = fold([n.title, n.name, n.body, (n.tags || []).join(" "), n.id, n.d, n.path, n.p].join(" "));
    if (hay.includes(t)) out.add(n.id);
  }
  return out;
}
function bestMatch(ids, q){  // titre > tags > identifiant > contenu
  const t = fold(q); let best = null, bs = -1;
  for (const id of ids){ const n = cur.byId.get(id); if (!n) continue;
    const s = (fold(n.title || n.name).includes(t) ? 8 : 0) + (fold((n.tags || []).join(" ")).includes(t) ? 3 : 0)
      + (fold(n.id).includes(t) ? 2 : 0) + (n.t === "project" ? -1 : 0) + (n.pr || 0);
    if (s > bs){ bs = s; best = id; } }
  return best;
}
function layoutTop(){ root.style.setProperty("--top", ($("#bar").getBoundingClientRect().bottom + 10) + "px"); }
function showPath(a, b){  // plus court chemin pondéré : liens écrits d'abord, puis concepts et liens déduits
  const cost = l => l.inf ? 1.8 : l.con ? 1.6 : l.rel === "part_of" ? 1.3 : 1;
  const adj = new Map();
  for (const l of cur.links){
    if (!linkVis(l)) continue;
    const s = idOf(l.source), t = idOf(l.target);
    if (!adj.has(s)) adj.set(s, []); if (!adj.has(t)) adj.set(t, []);
    adj.get(s).push([t, cost(l), l]); adj.get(t).push([s, cost(l), l]);
  }
  const dist = new Map([[a.id, 0]]), prev = new Map(), todo = new Set([a.id]);
  while (todo.size){
    let u = null; for (const x of todo) if (u === null || dist.get(x) < dist.get(u)) u = x;
    todo.delete(u); if (u === b.id) break;
    for (const [v, c, l] of (adj.get(u) || [])){
      const nd = dist.get(u) + c;
      if (nd < (dist.has(v) ? dist.get(v) : Infinity)){ dist.set(v, nd); prev.set(v, [u, l]); todo.add(v); }
    }
  }
  if (!prev.has(b.id)) return openPanel(`<h2>Pas de chemin</h2><p class="muted">Aucun lien visible ne relie « ${esc(a.name)} » à « ${esc(b.name)} ». Affiche les liens déduits ou les concepts.</p>`);
  const steps = []; let cur2 = b.id;
  while (cur2 !== a.id){ const [p, l] = prev.get(cur2); steps.unshift([p, cur2, l]); cur2 = p; }
  st.path = {nodes: new Set([a.id, ...steps.map(s => s[1])]), links: new Set(steps.map(([p, q]) => pairKey(p, q)))};
  st.sel = b; st.groupFocus = null; computeFocus(); redraw(); flyToSet(st.path.nodes);
  const rel = l => l.inf ? `≈ déduit (${(l.why || []).join(", ")})` : l.con ? "mentionne" : l.rel;
  openPanel(`<h2>Chemin · ${steps.length} saut(s)</h2><ul class="list">${item(a.id, "départ")}${steps.map(([p, q, l]) => item(q, rel(l))).join("")}</ul>`
    + `<p class="muted" style="font-size:12px;margin-top:10px">Échap pour effacer · Maj+clic sur un autre nœud pour un autre chemin.</p>`);
}
function select(n){ st.path = null; st.userMoved = true; st.sel = n; st.groupFocus = null; computeFocus(); redraw(); showNode(n); }
function selectId(id){ const n = cur.byId.get(id); if (n){ select(n); flyTo(n); } }
function focusGroup(ids, label){ st.sel = null; st.groupFocus = new Set(ids); st.focusLabel = label || ""; computeFocus(); redraw(); flyToSet(st.groupFocus); }

// ------------------------------------------------------------------ panneau
function openPanel(html){ panel.innerHTML = `<button class="x" aria-label="Fermer">×</button>` + html; panel.classList.add("open");
  panel.querySelector(".x").onclick = closePanel;
  panel.querySelectorAll("[data-go]").forEach(b => b.onclick = () => selectId(b.dataset.go));
  panel.querySelectorAll("[data-comm]").forEach(b => b.onclick = () => { const c = commById.get(+b.dataset.comm); if (c) focusGroup(c.members, c.label); });
  panel.querySelectorAll("[data-pair]").forEach(b => b.onclick = () => focusGroup(b.dataset.pair.split("|"), ""));
  panel.querySelectorAll("[data-concept]").forEach(b => b.onclick = () => { const c = cur.byId.get(b.dataset.concept); if (c) focusGroup([c.id, ...c.members], c.name); });
}
function closePanel(){ panel.classList.remove("open"); }
function item(id, sub){
  const n = cur.byId.get(id); if (!n) return "";
  return `<li><button data-go="${esc(id)}"><span class="dot" style="background:${baseColor(n)}"></span><span class="t">${esc(short(n.name, 80))}${sub ? `<small>${esc(sub)}</small>` : ""}</span></button></li>`;
}
function showConcept(n){
  const mem = n.members.map(i => cur.byId.get(i)).filter(Boolean).sort((a, b) => (b.pr || 0) - (a.pr || 0));
  openPanel(`<div class="meta"><span class="chip"><span class="dot" style="background:${baseColor(n)}"></span>Concept · ${esc(n.ck)}</span></div>`
    + `<h2>${esc(n.name)}</h2><div class="meta"><span>${mem.length} souvenirs en parlent</span></div>`
    + `<h3>Souvenirs</h3><ul class="list">${mem.map(m => item(m.id, (TYPES[m.t] || [m.t])[0])).join("")}</ul>`);
}
function showNode(n){
  if (n.kind === "concept") return showConcept(n);
  if (n.kind === "file") return showFile(n);
  const t = TYPES[n.t] || [n.t, "#999"], c = commById.get(n.c);
  const links = [];
  for (const l of cur.links){
    const s = idOf(l.source), d = idOf(l.target);
    if (l.inf) continue;
    if (s === n.id) links.push([d, "→ " + l.rel]); else if (d === n.id) links.push([s, "← " + l.rel]);
  }
  const inf = (DATA.inf || []).filter(e => e.s === n.id || e.t === n.id).sort((a, b) => b.w - a.w).slice(0, 6);
  let h = `<div class="meta"><span class="chip"><span class="dot" style="background:${t[1]}"></span>${esc(t[0])}</span>`
    + (c ? `<button class="chip" data-comm="${c.id}"><span class="dot" style="background:${PALETTE[c.id % PALETTE.length]}"></span>${esc(short(c.label, 34))}</button>` : "")
    + `</div><h2>${esc(n.title)}</h2><div class="meta"><code>${esc(n.id)}</code>`
    + (n.p ? `<span>projet : <a href="#" data-go="${esc(n.p)}">${esc(n.p)}</a></span>` : "")
    + `<span>importance ${n.imp || 3}/5</span><span>rappelé ${n.hits || 0}×</span><span>maj ${esc(n.upd || "?")}</span>`
    + `<span>centralité ${(n.pr || 0).toFixed(2)}</span></div>`;
  if (n.path) h += `<div class="meta" style="margin-top:6px"><code>${esc(n.path)}</code></div>`;
  if (n.tags && n.tags.length) h += `<div class="chips">${n.tags.map(x => `<span class="chip">#${esc(x)}</span>`).join("")}</div>`;
  if (n.body) h += `<div class="body">${esc(n.body)}</div>`;
  if (n.t === "project"){
    const mem = DATA.nodes.filter(m => m.p === n.id).sort((a, b) => (b.pr || 0) - (a.pr || 0)).slice(0, 25);
    if (mem.length) h += `<h3>Souvenirs du projet (${mem.length})</h3><ul class="list">${mem.map(m => item(m.id, (TYPES[m.t] || [m.t])[0])).join("")}</ul>`;
  }
  if (links.length) h += `<h3>Liens (${links.length})</h3><ul class="list">${links.map(([id, r]) => item(id, r)).join("")}</ul>`;
  if (inf.length) h += `<h3>Liens déduits</h3><ul class="list">${inf.map(e => item(e.s === n.id ? e.t : e.s, `confiance ${e.conf} · ${e.why.join(", ")}`)).join("")}</ul>`;
  openPanel(h);
  panel.querySelectorAll("a[data-go]").forEach(a => a.onclick = ev => { ev.preventDefault(); selectId(a.dataset.go); });
}
function showFile(n){
  const out = [], inn = [];
  for (const l of cur.links){ const s = idOf(l.source), d = idOf(l.target); if (s === n.id) out.push(d); else if (d === n.id) inn.push(s); }
  const mod = (cur.map.mods12 || []).find(x => x.key === n.mod);
  let h = `<div class="meta"><span class="chip"><span class="dot" style="background:${baseColor(n)}"></span>${esc(mod ? mod.label : (n.mod || "(racine)"))}</span>`
    + `<span class="chip">${esc(KIND[n.k] || n.k || "")}</span></div><h2>${esc(n.name)}</h2>`
    + `<div class="meta"><code>${esc(n.id)}</code>${n.lines ? `<span>${n.lines} lignes</span>` : ""}<span>centralité ${(n.pr || 0).toFixed(2)}</span></div>`
    + (n.d ? `<div class="body">${esc(n.d)}</div>` : "");
  if (out.length) h += `<h3>Importe (${out.length})</h3><ul class="list">${out.slice(0, 40).map(i => item(i)).join("")}</ul>`;
  if (inn.length) h += `<h3>Importé par (${inn.length})</h3><ul class="list">${inn.slice(0, 40).map(i => item(i)).join("")}</ul>`;
  openPanel(h);
}
function showReport(){
  if (cur.map){
    const m = cur.map;
    const mods = (m.mods12 || []).map((x, i) => `<li><button data-mod="${i}"><span class="dot" style="background:${PALETTE[i % PALETTE.length]}"></span><span class="t">${esc(x.label)}<small>${x.n} fichiers affichés</small></span></button></li>`).join("");
    const top = cur.nodes.slice().sort((a, b) => b.pr - a.pr).slice(0, 10);
    openPanel(`<h2>Carte · ${esc(m.name)}</h2><div class="meta"><span>${m.nodes.length} fichiers affichés sur ${m.total}</span><span>générée le ${esc((m.generated || "").slice(0, 10))}</span></div>`
      + `<h3>Modules (communautés)</h3><ul class="list">${mods}</ul><h3>Fichiers les plus centraux</h3><ul class="list">${top.map(n => item(n.id, n.d)).join("")}</ul>`);
    panel.querySelectorAll("[data-mod]").forEach(b => b.onclick = () => { const i = +b.dataset.mod; focusGroup(cur.nodes.filter(n => n.c === i).map(n => n.id), ""); });
    return;
  }
  const comms = COMMS.filter(c => c.size >= 2);
  const by = id => cur.byId.get(id);
  let h = `<h2>Rapport du cerveau</h2><div class="meta"><span>${DATA.stats.memories} souvenirs</span><span>${DATA.stats.links} liens</span>`
    + `<span>${(DATA.inf || []).length} déduits</span><span>${comms.length} communautés</span></div>`
    + `<h3>Communautés</h3><ul class="list">${comms.map(c => `<li><button data-comm="${c.id}"><span class="dot" style="background:${PALETTE[c.id % PALETTE.length]}"></span><span class="t">${esc(c.label)}<small>${c.size} nœuds · ${esc((c.members || []).slice(0, 3).map(i => by(i) ? by(i).name : i).map(x => short(x, 34)).join(" · "))}</small></span></button></li>`).join("")}</ul>`;
  const cons = cur.nodes.filter(n => n.kind === "concept").sort((a, b) => b.n - a.n);
  if (cons.length) h += `<h3>Concepts</h3><div class="chips">${cons.slice(0, 24).map(c => `<button class="chip" data-concept="${esc(c.id)}">${esc(c.name)} <span class="muted">${c.n}</span></button>`).join("")}</div>`;
  if ((DATA.key || []).length) h += `<h3>Nœuds clés</h3><ul class="list">${DATA.key.slice(0, 6).map(i => item(i, `centralité ${((by(i) || {}).pr || 0).toFixed(2)}`)).join("")}</ul>`;
  if ((DATA.bridges || []).length) h += `<h3>Liens surprenants</h3><ul class="list">${DATA.bridges.slice(0, 6).map(b => by(b.s) && by(b.t) ? `<li><button data-pair="${esc(b.s)}|${esc(b.t)}"><span class="t">${esc(short(by(b.s).name, 40))} ↔ ${esc(short(by(b.t).name, 40))}<small>${esc(b.kind)} · ${esc(b.why.join(", "))}</small></span></button></li>` : "").join("")}</ul>`;
  const sugg = (DATA.inf || []).filter(e => e.conf !== "faible").slice(0, 6);
  if (sugg.length) h += `<h3>Liens suggérés</h3><ul class="list">${sugg.map(e => by(e.s) && by(e.t) ? `<li><button data-pair="${esc(e.s)}|${esc(e.t)}"><span class="t">${esc(short(by(e.s).name, 40))} ↔ ${esc(short(by(e.t).name, 40))}<small>confiance ${esc(e.conf)} · ${esc(e.why.join(", "))} · <code>brain link ${esc(e.s)} ${esc(e.t)}</code></small></span></button></li>` : "").join("")}</ul>`;
  const g = DATA.gaps || {};
  const gl = [];
  if ((DATA.dups || []).length) gl.push(`${DATA.dups.length} doublon(s) possible(s) → <code>brain consolidate</code>`);
  if ((g.isolated || []).length) gl.push(`${g.isolated.length} souvenir(s) isolé(s)`);
  if ((g.old_todos || []).length) gl.push(`${g.old_todos.length} à-faire de plus de 14 jours`);
  if ((g.stale || []).length) gl.push(`${g.stale.length} jamais rappelé(s) depuis 60 jours`);
  if (gl.length) h += `<h3>Entretien</h3><ul class="list">${gl.map(x => `<li class="muted" style="font-size:12.8px">• ${x}</li>`).join("")}</ul>`;
  if ((DATA.questions || []).length) h += `<h3>Questions suggérées</h3><ul class="list">${DATA.questions.map(q => `<li style="font-size:12.8px">• ${esc(q)}</li>`).join("")}</ul>`;
  openPanel(h);
}

// ------------------------------------------------------------------ légende, tableau, vues
function buildLegend(){
  const items = new Map();
  for (const n of cur.nodes){
    const k = legendKey(n);
    if (!items.has(k)) items.set(k, {k, n: 0, color: baseColor(n), label: legendLabel(k)});
    items.get(k).n++;
  }
  const arr = [...items.values()].sort((a, b) => b.n - a.n);
  const hint = cur.map ? "Modules · clic : masquer/afficher" : st.color === "comm" ? "Communautés · clic : masquer/afficher" : st.color === "type" ? "Types · clic : masquer/afficher" : "Projets · clic : masquer/afficher";
  $("#legend").innerHTML = `<div class="hint">${hint}</div><div class="row">` + arr.slice(0, 24).map(x =>
    `<button data-k="${esc(x.k)}" aria-pressed="${!st.hidden.has(x.k)}"><span class="dot" style="background:${x.color}"></span>${esc(short(x.label, 30))} <span class="muted">${x.n}</span></button>`).join("") + `</div>`;
  $("#legend").querySelectorAll("button").forEach(b => b.onclick = () => {
    const k = b.dataset.k; st.hidden.has(k) ? st.hidden.delete(k) : st.hidden.add(k);
    b.setAttribute("aria-pressed", String(!st.hidden.has(k))); redraw();
  });
}
function legendLabel(k){
  const [kind, v] = [k.slice(0, 1), k.slice(2)];
  if (kind === "k") return "concepts";
  if (kind === "t") return (TYPES[v] || [v])[0];
  if (kind === "p") return v === "-" ? "global" : (DATA.nodes.find(n => n.id === v) || {title: v}).title;
  if (kind === "m"){ const m = (cur.map.mods12 || [])[+v]; return m ? m.label : "autres"; }
  if (v === "iso") return "isolés";
  const c = commById.get(+v); return c ? c.label : "autres";
}
function buildTable(){
  const th = $("#thead"), tb = $("#tbody");
  tb.textContent = "";
  if (cur.map){
    th.innerHTML = "<tr><th>Fichier</th><th>Module</th><th>Type</th><th>Lignes</th><th>Centralité</th></tr>";
    for (const n of cur.nodes.slice().sort((a, b) => b.pr - a.pr)){
      const tr = document.createElement("tr"); tr.tabIndex = 0;
      tr.innerHTML = `<td>${esc(n.id)}</td><td>${esc(legendLabel(legendKey(n)))}</td><td>${esc(KIND[n.k] || n.k || "")}</td><td>${n.lines || ""}</td><td>${(n.pr || 0).toFixed(2)}</td>`;
      tr.onclick = tr.onkeydown = ev => { if (ev.type === "click" || ev.key === "Enter"){ toggleTable(false); selectId(n.id); } };
      tb.appendChild(tr);
    }
    return;
  }
  th.innerHTML = "<tr><th>Souvenir</th><th>Type</th><th>Communauté</th><th>Projet</th><th>Imp.</th><th>Rappels</th><th>Maj</th></tr>";
  for (const n of cur.nodes.filter(x => x.kind !== "concept").sort((a, b) => (b.pr || 0) - (a.pr || 0))){
    const c = commById.get(n.c);
    const tr = document.createElement("tr"); tr.tabIndex = 0;
    tr.innerHTML = `<td>${esc(n.title)}</td><td>${esc((TYPES[n.t] || [n.t])[0])}</td><td>${esc(c ? (c.size < 2 ? "isolé" : c.label) : "")}</td><td>${esc(n.p || "")}</td><td>${n.imp || 3}</td><td>${n.hits || 0}</td><td>${esc(n.upd || "")}</td>`;
    tr.onclick = tr.onkeydown = ev => { if (ev.type === "click" || ev.key === "Enter"){ toggleTable(false); selectId(n.id); } };
    tb.appendChild(tr);
  }
}
function toggleTable(on){ const w = $("#tablewrap"); on = on == null ? !w.classList.contains("open") : on;
  w.classList.toggle("open", on); $("#tblBtn").setAttribute("aria-pressed", String(on)); if (on) buildTable(); }
function setStats(){
  if (cur.map){ const m = cur.map; $("#stats").textContent = `${m.nodes.length} / ${m.total} fichiers · ${cur.links.length} imports · carte du ${(m.generated || "").slice(0, 10)}`; return; }
  const s = DATA.stats;
  $("#stats").textContent = `${s.memories} souvenirs · ${s.projects} projets · ${s.links} liens · ${(DATA.inf || []).length} déduits · ${COMMS.filter(c => c.size >= 2).length} communautés`;
}
function setView(v){
  st.view = v; st.sel = null; st.hover = null; st.q = ""; st.groupFocus = null; st.focus = null; st.path = null; st.until = null;
  st.hidden.clear(); $("#q").value = "";
  const m = v === "mem" ? null : (DATA.maps || []).find(x => "map:" + x.pid === v);
  cur = m ? mapData(m) : memData();
  $("#color").disabled = !!m; $("#infBtn").disabled = !!m; $("#conBtn").disabled = !!m;
  initTimeline();
  closePanel();
  if (G){ G.warmupTicks(m ? 120 : 60).cooldownTime(m ? 6000 : 8000);  // disposition pré-calculée : cadrage immédiat
          G.graphData({nodes: cur.nodes, links: cur.links}); forces();
          st.userMoved = false; (setView.ts || []).forEach(clearTimeout);
          setView.ts = [450, 1600, 3500].map(ms => setTimeout(() => autoFit(ms < 1000 ? 500 : 900), ms)); }
  pickLabels(); buildLegend(); setStats();
  if ($("#tablewrap").classList.contains("open")) buildTable();
}
function buildViews(){
  const sel = $("#view");
  sel.innerHTML = `<option value="mem">🧠 Mémoire</option>` + (DATA.maps || []).map(m =>
    `<option value="map:${esc(m.pid)}">🗺️ Carte · ${esc(m.name)} (${m.nodes.length} fichiers)</option>`).join("");
  sel.onchange = () => setView(sel.value);
}

// ------------------------------------------------------------------ thème, contrôles
function applyTheme(t){
  if (t === "light") root.setAttribute("data-theme", "light"); else root.removeAttribute("data-theme");
  $("#themeBtn").textContent = t === "light" ? "☀" : "☾";
  if (G){ G.backgroundColor(getComputedStyle(root).getPropertyValue("--bg").trim()); redraw(); }
}
function initTimeline(){
  const dates = cur.map ? [] : [...new Set(cur.nodes.filter(n => n.kind === "mem").map(n => n.cre || n.upd).filter(Boolean))].sort();
  st.dates = dates; st.until = null;
  const tl = $("#tl"); tl.max = String(Math.max(0, dates.length - 1)); tl.value = tl.max;
  $("#timeline").style.display = dates.length > 1 ? "flex" : "none";
  tlLabel();
}
function tlLabel(){
  const d = st.until || st.dates[st.dates.length - 1];
  if (!d) return;
  const n = cur.nodes.filter(x => x.kind === "mem" && (x.cre || x.upd || "") <= d).length;
  $("#tlLabel").textContent = `${st.until ? "jusqu'au" : "au"} ${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)} · ${n} nœuds`;
}
function setUntil(i){
  const last = st.dates.length - 1;
  st.until = i >= last ? null : st.dates[Math.max(0, i)];
  $("#tl").value = String(Math.max(0, Math.min(i, last))); tlLabel(); redraw();
}
function controls(){
  let theme = store.get("brain3d-theme") || "dark";
  applyTheme(theme);
  $("#themeBtn").onclick = () => { theme = theme === "light" ? "dark" : "light"; store.set("brain3d-theme", theme); applyTheme(theme); };
  $("#color").onchange = e => { st.color = e.target.value; st.hidden.clear(); buildLegend(); redraw(); if (st.sel) showNode(st.sel); };
  $("#infBtn").onclick = e => { st.inf = !st.inf; e.target.setAttribute("aria-pressed", String(st.inf)); redraw(); };
  st.concepts = true;
  $("#conBtn").onclick = e => { st.concepts = !st.concepts; e.target.setAttribute("aria-pressed", String(st.concepts)); redraw(); };
  $("#tl").oninput = e => { stopPlay(); setUntil(+e.target.value); };
  let play = null;
  const stopPlay = () => { if (play){ clearInterval(play); play = null; $("#playBtn").textContent = "▶"; } };
  $("#playBtn").onclick = () => {
    if (play) return stopPlay();
    let i = 0; setUntil(0); $("#playBtn").textContent = "⏸";
    play = setInterval(() => { i++; setUntil(i); if (i >= st.dates.length - 1) stopPlay(); }, 900);
  };
  $("#lblBtn").onclick = e => { st.labels = !st.labels; e.target.setAttribute("aria-pressed", String(st.labels)); };
  $("#rotBtn").onclick = () => toggleRotate();
  $("#fitBtn").onclick = () => G && G.zoomToFit(900, 70);
  $("#repBtn").onclick = () => showReport();
  $("#pngBtn").onclick = () => {
    if (!G) return;
    const a = document.createElement("a");
    a.href = G.renderer().domElement.toDataURL("image/png");
    a.download = "cerveau-" + new Date().toISOString().slice(0, 10) + ".png";
    document.body.appendChild(a); a.click(); a.remove();
  };
  $("#tblBtn").onclick = () => toggleTable();
  $("#fbTable").onclick = () => { $("#fallback").style.display = "none"; toggleTable(true); };
  const q = $("#q");
  q.oninput = () => { st.q = q.value.trim(); st.sel = null; computeFocus(); redraw(); };
  q.onkeydown = ev => { if (ev.key === "Enter" && st.focus && st.focus.size){ const id = bestMatch(st.focus, st.q); if (id) selectId(id); } if (ev.key === "Escape"){ q.value = ""; q.oninput(); q.blur(); } };
  addEventListener("keydown", ev => {
    if (ev.target.matches("input,select,textarea")) return;
    if (ev.key === "/"){ ev.preventDefault(); q.focus(); }
    else if (ev.key === "Escape"){ st.sel = null; st.path = null; st.groupFocus = null; st.q = ""; q.value = ""; computeFocus(); redraw(); closePanel(); toggleTable(false); }
    else if (ev.key === "r" || ev.key === "R") toggleRotate();
    else if (ev.key === "f" || ev.key === "F") G && G.zoomToFit(900, 70);
  });
}
function toggleRotate(){
  st.rotate = !st.rotate; $("#rotBtn").setAttribute("aria-pressed", String(st.rotate));
  const c = G && G.controls(); if (c){ c.autoRotate = st.rotate; c.autoRotateSpeed = .8; }
}
function webgl(){ try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; } }
function fail(msg){ $("#fbmsg").textContent = msg; $("#fallback").style.display = "flex"; }
function loadScript(src){ return new Promise((ok, ko) => { const s = document.createElement("script"); s.src = src; s.async = true; s.onload = ok; s.onerror = ko; document.head.appendChild(s); }); }

(async function main(){
  controls(); buildViews(); layoutTop(); addEventListener("resize", layoutTop);
  cur = memData(); setStats(); buildLegend();
  for (const src of LIBS){ if (typeof window.ForceGraph3D === "function") break; try { await loadScript(src); } catch (e) {} }
  if (typeof window.ForceGraph3D !== "function") return fail("La bibliothèque 3D n'a pas pu être chargée (pas de connexion ?). La vue 2D fonctionne hors ligne.");
  if (!webgl()) return fail("WebGL n'est pas disponible dans ce navigateur.");
  initGraph(); setView("mem");
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash && cur.byId.has(hash)) setTimeout(() => selectId(hash), 1600);
})();
</script>
</body>
</html>
"""
