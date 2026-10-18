"""Gabarit de la visualisation 3D (cerveau.html) — style futuriste et animé : 3d-force-graph (three.js) chargé depuis
un CDN, données intégrées, effets (bloom, champ d'étoiles scintillant, nébuleuses, grille holographique, influx
neuronaux le long des liens, nœuds qui respirent, réticule de sélection, onde de choc au clic, démarrage où les nœuds
se matérialisent en vague, rotation au repos) — coupables d'un clic (✨), réduits si le système demande moins
d'animations. Sans connexion ou sans WebGL, la page renvoie vers cerveau-2d.html (100 % local) et la vue tableau."""

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#03050b;--bg2:#070b18;--glass:rgba(8,13,28,.72);--glass2:rgba(12,19,40,.86);--ink:#e9f1ff;--ink2:#a7b6d6;--muted:#6c7a9c;
--line:rgba(120,170,255,.16);--line2:rgba(120,170,255,.32);--chip:rgba(120,170,255,.07);--hover:rgba(120,170,255,.14);
--accent:#38e1ff;--accent2:#a78bfa;--glow:0 0 0 1px rgba(56,225,255,.45),0 0 18px rgba(56,225,255,.28);
--shadow:0 18px 50px rgba(0,0,0,.55);--font:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
:root[data-theme="light"]{--bg:#eef2f9;--bg2:#e3e9f5;--glass:rgba(255,255,255,.78);--glass2:rgba(255,255,255,.94);--ink:#0c1324;--ink2:#3a4762;
--muted:#74819e;--line:rgba(30,60,140,.14);--line2:rgba(30,60,140,.28);--chip:rgba(30,60,140,.05);--hover:rgba(30,60,140,.09);
--accent:#0a84c8;--accent2:#6d4fd6;--glow:0 0 0 1px rgba(10,132,200,.5),0 0 12px rgba(10,132,200,.18);--shadow:0 14px 34px rgba(20,40,90,.16)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:radial-gradient(1200px 800px at 50% 45%,var(--bg2),var(--bg));color:var(--ink);
font:14px/1.45 var(--font);overflow:hidden;-webkit-font-smoothing:antialiased}
#graph{position:fixed;inset:0}
#vignette{position:fixed;inset:0;pointer-events:none;z-index:1;background:radial-gradient(ellipse at center,transparent 55%,rgba(0,0,8,.55) 100%)}
:root[data-theme="light"] #vignette{display:none}
#hud{position:fixed;inset:8px;pointer-events:none;z-index:1}
#hud i{position:absolute;width:22px;height:22px;border:1.5px solid var(--accent);opacity:.45}
#hud i:nth-child(1){left:0;top:0;border-right:0;border-bottom:0}#hud i:nth-child(2){right:0;top:0;border-left:0;border-bottom:0}
#hud i:nth-child(3){left:0;bottom:0;border-right:0;border-top:0}#hud i:nth-child(4){right:0;bottom:0;border-left:0;border-top:0}
#labels{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:2}
.lbl{position:absolute;left:0;top:0;white-space:nowrap;font:600 11.5px/1.2 var(--font);letter-spacing:.015em;color:var(--ink);
padding:3px 8px;border-radius:7px;background:rgba(4,8,20,.66);border:1px solid color-mix(in srgb,var(--c) 42%,transparent);
box-shadow:0 0 12px color-mix(in srgb,var(--c) 20%,transparent);will-change:transform,opacity;opacity:0;transition:opacity .22s ease}
.lbl.big{font-size:12.5px;font-weight:700;letter-spacing:.03em;border-color:color-mix(in srgb,var(--c) 70%,transparent)}
:root[data-theme="light"] .lbl{background:rgba(255,255,255,.72);box-shadow:none}
.glass{background:var(--glass);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);
backdrop-filter:blur(14px) saturate(1.3);-webkit-backdrop-filter:blur(14px) saturate(1.3)}
#bar{position:fixed;left:14px;top:14px;z-index:5;display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:9px 14px;
max-width:calc(100vw - var(--toolsw,620px) - 42px);animation:drop .6s cubic-bezier(.2,.8,.2,1) both}
#view{max-width:230px}#color{max-width:190px}
#tools{position:fixed;right:14px;top:14px;z-index:5;display:flex;flex-wrap:nowrap;justify-content:flex-end;gap:6px;align-items:center;
padding:8px;max-width:calc(100vw - 28px);animation:drop .6s .08s cubic-bezier(.2,.8,.2,1) both}
#tools input[type=search]{flex:0 0 210px;min-width:0}
#dock{position:fixed;left:14px;top:var(--topl,84px);z-index:5;display:flex;flex-direction:column;gap:5px;padding:6px;
animation:slide .6s .15s cubic-bezier(.2,.8,.2,1) both}
#dock button,#dock .btn{width:38px;height:38px;padding:0;display:grid;place-items:center;font-size:15px;position:relative}
#dock .btn{font-size:12px;font-weight:700}
#dock .sep{height:1px;background:var(--line2);margin:3px 6px;opacity:.7}
#dock [data-tip]:hover::after,#dock [data-tip]:focus-visible::after{content:attr(data-tip);position:absolute;left:calc(100% + 12px);top:50%;
transform:translateY(-50%);white-space:nowrap;background:var(--glass2);border:1px solid var(--line2);color:var(--ink);font:500 12px var(--font);
padding:6px 10px;border-radius:8px;pointer-events:none;box-shadow:var(--shadow);animation:fade .15s ease both}
.brand{display:flex;align-items:center;gap:10px;margin-right:4px}
.logo{width:30px;height:30px;border-radius:50%;position:relative;flex:none;
background:radial-gradient(circle at 50% 50%,#fff 0 9%,var(--accent) 18%,rgba(56,225,255,.0) 62%);box-shadow:0 0 16px rgba(56,225,255,.55)}
.logo::before,.logo::after{content:"";position:absolute;inset:2px;border-radius:50%;border:1.5px solid transparent;border-top-color:var(--accent);
border-left-color:var(--accent2);animation:spin 3.2s linear infinite}
.logo::after{inset:-3px;border-top-color:var(--accent2);border-left-color:transparent;border-right-color:var(--accent);animation-duration:5s;animation-direction:reverse;opacity:.7}
.brand h1{font-size:15px;margin:0;font-weight:700;letter-spacing:.22em;text-transform:uppercase;line-height:1}
.brand small{display:block;font:500 10.5px/1.2 var(--mono);color:var(--muted);letter-spacing:.08em;margin-top:3px}
#stats{display:flex;flex-wrap:wrap;gap:6px;margin-right:auto}
.stat{font:500 11.5px/1 var(--mono);color:var(--ink2);padding:5px 8px;border-radius:8px;background:var(--chip);border:1px solid var(--line)}
.stat b{color:var(--ink);font-weight:600}
.grp{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
select,input[type=search],button,.btn{font:500 12.5px/1.2 var(--font);color:var(--ink);background:var(--chip);border:1px solid var(--line);
border-radius:9px;padding:6px 10px;text-decoration:none;cursor:pointer;transition:background .15s,box-shadow .2s,border-color .2s,transform .1s}
select{padding-right:6px}select option{background:var(--glass2);color:var(--ink)}
button:hover,select:hover,.btn:hover{background:var(--hover);border-color:var(--line2)}
button:active{transform:translateY(1px)}
button:focus-visible,select:focus-visible,input:focus-visible,.btn:focus-visible{outline:none;box-shadow:var(--glow)}
button[aria-pressed=true]{border-color:transparent;box-shadow:var(--glow);background:rgba(56,225,255,.10)}
:root[data-theme="light"] button[aria-pressed=true]{background:rgba(10,132,200,.08)}
button:disabled{opacity:.35;cursor:default}
input[type=search]{min-width:150px;flex:0 1 220px;cursor:text}
input[type=search]::placeholder{color:var(--muted)}
@keyframes slide{from{opacity:0;transform:translateX(-16px)}to{opacity:1;transform:none}}
#panel{position:fixed;right:14px;top:var(--top,80px);bottom:14px;width:370px;z-index:4;padding:16px 18px;overflow:auto;
transform:translateX(calc(100% + 30px));opacity:0;pointer-events:none;transition:transform .42s cubic-bezier(.2,.8,.2,1),opacity .3s ease}
#panel.open{transform:none;opacity:1;pointer-events:auto}
#panel::before{content:"";position:absolute;left:0;top:18px;bottom:18px;width:2px;border-radius:2px;
background:linear-gradient(var(--accent),var(--accent2));opacity:.7}
#panel h2{font-size:18px;line-height:1.25;margin:4px 0 8px;overflow-wrap:anywhere;font-weight:600}
#panel h3{font:600 10.5px/1 var(--mono);text-transform:uppercase;letter-spacing:.14em;color:var(--accent);margin:18px 0 8px;opacity:.85}
#panel .x{position:absolute;right:10px;top:8px;border:0;background:none;font-size:20px;color:var(--muted);padding:2px 8px}
.meta{color:var(--ink2);font-size:12px;display:flex;flex-wrap:wrap;gap:4px 12px}
.body{white-space:pre-wrap;font-size:13.4px;line-height:1.55;margin-top:12px;overflow-wrap:anywhere;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:11.5px;color:var(--ink2)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none;box-shadow:0 0 8px currentColor}
.list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.list li{animation:rise .38s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(var(--i,0) * 22ms)}
.list button{width:100%;text-align:left;display:flex;gap:9px;align-items:flex-start;padding:7px 9px;font-size:12.8px;line-height:1.35}
.list button small{display:block;color:var(--muted);font-size:11.5px;margin-top:1px}
.list .t{flex:1;min-width:0;overflow-wrap:anywhere}.list .dot{margin-top:4px}
.muted{color:var(--muted)}code{font:12px var(--mono);color:var(--ink2)}
#timeline{position:fixed;left:50%;transform:translateX(-50%);bottom:14px;z-index:4;display:none;gap:10px;align-items:center;
padding:7px 12px;width:min(470px,calc(100vw - 28px))}
#timeline input{flex:1;accent-color:var(--accent)}#timeline span{font:500 11.5px var(--mono);color:var(--ink2);white-space:nowrap}
#timeline button{padding:3px 10px}
@media (max-width:1100px){#timeline{left:auto;right:14px;transform:none;bottom:60px}}
#legend{position:fixed;left:76px;bottom:14px;z-index:4;max-width:min(430px,calc(100vw - 90px));max-height:32vh;overflow:auto;padding:9px 10px}
#legend .row{display:flex;flex-wrap:wrap;gap:3px}
#legend button{display:inline-flex;align-items:center;gap:7px;font-size:11.8px;padding:3px 8px;background:transparent;border-color:transparent}
#legend button:hover{background:var(--hover)}
#legend button[aria-pressed=false]{opacity:.35;text-decoration:line-through}
#legend .hint{font:600 10px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:2px 3px 7px}
#tablewrap{position:fixed;inset:var(--top,80px) 14px 14px 76px;z-index:6;display:none;overflow:auto;padding:0}
#tablewrap.open{display:block;animation:fade .25s ease both}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--glass2);color:var(--accent);font:600 10.5px var(--mono);letter-spacing:.12em;text-transform:uppercase}
tr[tabindex]{cursor:pointer}tr[tabindex]:hover,tr[tabindex]:focus{background:var(--hover);outline:none}
#fallback{position:fixed;inset:0;display:none;align-items:center;justify-content:center;z-index:9;padding:16px}
#fallback .glass{max-width:520px;padding:22px 24px}
#help{position:fixed;right:14px;bottom:14px;z-index:3;font:500 11px var(--mono);color:var(--muted);padding:7px 11px;display:flex;gap:12px;align-items:center}
#fps{color:var(--accent);opacity:.8}
.live{display:inline-flex;align-items:center;gap:6px}.live::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent);
box-shadow:0 0 8px var(--accent);animation:blink 1.6s ease-in-out infinite}
.scene-tip{background:var(--glass2)!important;color:var(--ink)!important;border:1px solid var(--line2);border-left:3px solid var(--c,var(--accent));
border-radius:10px;padding:8px 11px;max-width:310px;font:12.5px/1.4 var(--font);box-shadow:var(--shadow);backdrop-filter:blur(10px)}
.scene-tip b{display:block;margin-bottom:2px;font-weight:600}.scene-tip span{color:var(--ink2);font-size:11.5px}
#boot{position:fixed;inset:0;z-index:8;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;
background:radial-gradient(900px 600px at 50% 50%,#0a1430,#02040a);transition:opacity .8s ease,visibility .8s}
#boot.done{opacity:0;visibility:hidden}
:root[data-theme="light"] #boot{background:radial-gradient(900px 600px at 50% 50%,#ffffff,#e6ecf7)}
.core{width:120px;height:120px;position:relative}
.core i{position:absolute;inset:0;border-radius:50%;border:2px solid transparent;border-top-color:var(--accent);border-right-color:rgba(56,225,255,.25);
animation:spin 1.6s linear infinite}
.core i:nth-child(2){inset:14px;border-top-color:var(--accent2);border-right-color:rgba(167,139,250,.25);animation-duration:2.4s;animation-direction:reverse}
.core i:nth-child(3){inset:30px;border-top-color:#f472b6;border-right-color:rgba(244,114,182,.25);animation-duration:1.1s}
.core b{position:absolute;inset:46px;border-radius:50%;background:radial-gradient(circle,#fff,var(--accent) 45%,transparent 72%);
box-shadow:0 0 30px var(--accent);animation:pulse 1.4s ease-in-out infinite}
#bootTitle{font:700 13px/1 var(--font);letter-spacing:.5em;text-transform:uppercase;color:var(--ink);padding-left:.5em}
#bootMsg{font:500 11.5px/1 var(--mono);color:var(--accent);letter-spacing:.08em;min-height:14px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{transform:scale(.82);opacity:.75}50%{transform:scale(1.06);opacity:1}}
@keyframes blink{0%,100%{opacity:.35}50%{opacity:1}}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes drop{from{opacity:0;transform:translateY(-14px)}to{opacity:1;transform:none}}
#legend,#help,#timeline{animation:rise .7s .25s cubic-bezier(.2,.8,.2,1) both}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
@media (max-width:1100px){#bar{max-width:calc(100vw - 28px)}#tools{top:var(--topl,84px);left:76px;right:14px;justify-content:flex-start;flex-wrap:wrap}
#tools input[type=search]{flex:1 1 180px}}
@media (max-width:820px){#panel{left:14px;right:14px;width:auto;top:auto;height:54vh}#help{display:none}.brand small{display:none}
#dock{flex-direction:row;flex-wrap:nowrap;overflow-x:auto;top:auto;bottom:14px;left:14px;right:14px;scrollbar-width:none}
#dock button,#dock .btn{flex:none;width:36px;height:36px}#dock .sep{width:1px;height:auto;margin:6px 3px;flex:none}
#dock [data-tip]:hover::after{display:none}
#legend{display:none}#timeline{bottom:70px}#timeline span{font-size:10.5px}#tools{left:14px}#tablewrap{left:14px}
#tools select{flex:1 1 40%;max-width:none;min-width:0}}
</style>
</head>
<body>
<div id="graph" aria-label="Graphe 3D interactif du cerveau (la vue tableau donne le même contenu)"></div>
<div id="vignette"></div>
<div id="hud" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
<div id="labels" aria-hidden="true"></div>
<div id="bar" class="glass">
  <div class="brand"><span class="logo" aria-hidden="true"></span><div><h1>Cerveau</h1><small>mémoire de Claude</small></div></div>
  <div id="stats"></div>
</div>
<div id="tools" class="glass">
  <select id="view" aria-label="Vue"></select>
  <select id="color" aria-label="Couleur selon">
    <option value="comm">Couleur : communauté</option>
    <option value="type">Couleur : type</option>
    <option value="proj">Couleur : projet</option>
  </select>
  <input type="search" id="q" placeholder="Rechercher…  ( / )" aria-label="Rechercher">
</div>
<nav id="dock" class="glass" aria-label="Commandes">
  <button class="tog" id="infBtn" aria-pressed="true" data-tip="Liens déduits du contenu" aria-label="Liens déduits">≈</button>
  <button class="tog" id="conBtn" aria-pressed="true" data-tip="Concepts (outils, sujets, sigles)" aria-label="Concepts">◇</button>
  <button class="tog" id="lblBtn" aria-pressed="true" data-tip="Étiquettes" aria-label="Étiquettes">Aa</button>
  <button class="tog" id="rotBtn" aria-pressed="false" data-tip="Rotation continue · R" aria-label="Rotation">⟳</button>
  <button class="tog" id="fxBtn" aria-pressed="true" data-tip="Effets et animations · E" aria-label="Effets">✦</button>
  <span class="sep" aria-hidden="true"></span>
  <button id="fitBtn" data-tip="Recentrer · F" aria-label="Recentrer">⌖</button>
  <button id="repBtn" data-tip="Rapport du cerveau" aria-label="Rapport">▦</button>
  <button id="tblBtn" aria-pressed="false" data-tip="Vue tableau" aria-label="Tableau">☰</button>
  <a class="btn" href="cerveau-2d.html" data-tip="Vue 2D (hors ligne)" aria-label="Vue 2D">2D</a>
  <button id="pngBtn" data-tip="Enregistrer en image" aria-label="Image PNG">⤓</button>
  <button id="themeBtn" data-tip="Thème clair / sombre" aria-label="Thème">☾</button>
</nav>
<aside id="panel" class="glass" aria-live="polite" inert></aside>
<div id="legend" class="glass"></div>
<div id="timeline" class="glass"><button id="playBtn" title="Voir le cerveau grandir jour après jour">▶</button>
<input type="range" id="tl" min="0" max="0" value="0" aria-label="Chronologie : afficher les souvenirs jusqu'à une date"><span id="tlLabel"></span></div>
<div id="tablewrap" class="glass"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<div id="help" class="glass"><span class="live">en direct</span><span id="fps"></span><span>glisser : tourner · molette : zoom · clic : détails · Maj+clic : chemin</span></div>
<div id="boot" aria-live="polite"><div class="core" aria-hidden="true"><i></i><i></i><i></i><b></b></div><div id="bootTitle">Cerveau</div><div id="bootMsg">connexion…</div></div>
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
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const easeOutBack = k => { const c1 = 1.5, c3 = c1 + 1; return 1 + c3 * Math.pow(k - 1, 3) + c1 * Math.pow(k - 1, 2); };
const easeOutCubic = k => 1 - Math.pow(1 - k, 3);
const PALETTE = ["#38e1ff","#a78bfa","#f472b6","#a3e635","#fbbf24","#fb923c","#2dd4bf","#60a5fa","#fb7185","#34d399",
                 "#e879f9","#facc15","#818cf8","#4ade80","#f87171","#67e8f9"];
const TYPES = {user:["Profil","#60a5fa"], feedback:["Règle","#c084fc"], project:["Projet","#fb923c"], decision:["Décision","#fbbf24"],
  fact:["Fait","#34d399"], learning:["Apprentissage","#22d3ee"], reference:["Référence","#a5b4cf"], entity:["Entité","#f472b6"],
  todo:["À faire","#fb7185"], source:["Source","#94a3b8"], concept:["Concept","#a3e635"], topic:["Sujet","#facc15"],
  analysis:["Analyse","#2dd4bf"]};
const KIND = {code:"code", doc:"document", data:"données", asset:"média", other:"autre"};
const REL = 4;
const store = { get(k){ try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v){ try { localStorage.setItem(k, v); } catch (e) {} } };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const st = {view: "mem", color: "comm", inf: true, labels: true, rotate: false, q: "", hidden: new Set(),
            sel: null, hover: null, focus: null, focusLabel: ""};
const FX = {T: null, Bloom: null, on: store.get("brain3d-fx") !== "off", motion: !reduceMotion, bloom: null, stars: null,
            space: null, grid: null, radar: null, reticle: null, waves: [], geo: {}, tex: {}, pool: null, idleSpin: false,
            gridR: 1, gridY: 0};
let G = null, cur = null, viewStart = 0;
const graphEl = $("#graph"), panel = $("#panel");
const COMMS = DATA.comms || [];
const commById = new Map(COMMS.map(c => [c.id, c]));
const PROJECTS = DATA.nodes.filter(n => n.t === "project");
const projIndex = new Map(PROJECTS.map((p, i) => [p.id, i]));

function hexA(hex, a){ const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map(x => x + x).join("") : h, 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }
function idOf(x){ return typeof x === "object" && x ? x.id : x; }
function dark(){ return root.getAttribute("data-theme") !== "light"; }
function motionOn(){ return FX.on && FX.motion; }
function boot(msg){ $("#bootMsg").textContent = msg; }

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
  if (n.kind === "concept") return dark() ? "#cfe8ff" : "#4f5d7a";
  if (n.kind === "file") return n.c >= 0 ? PALETTE[n.c % PALETTE.length] : "#8494b2";
  if (st.color === "type") return (TYPES[n.t] || ["", "#a5b4cf"])[1];
  if (st.color === "proj"){ const p = n.t === "project" ? n.id : n.p; return projIndex.has(p) ? PALETTE[(projIndex.get(p) + 1) % PALETTE.length] : "#8b9ab8"; }
  const c = commById.get(n.c);
  return c && c.size < 2 ? (dark() ? "#a9bde6" : "#6b7a99") : PALETTE[(n.c || 0) % PALETTE.length];
}
function nodeColor(n){ const b = baseColor(n); return st.focus && !st.focus.has(n.id) ? hexA(b, dark() ? .10 : .16) : b; }
function nodeVal(n){
  if (n.kind === "concept") return 1.6 + 1.2 * Math.sqrt(n.n || 2);
  if (n.kind === "file") return 1.2 + 16 * (n.pr || 0);
  if (n.t === "project") return 16;
  return 2 + 1.1 * (n.imp || 3) + 12 * (n.pr || 0);
}
function radius(n){ return Math.cbrt(nodeVal(n)) * REL; }
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
  if (st.focus && !(st.focus.has(idOf(l.source)) && st.focus.has(idOf(l.target)))) return d ? "rgba(140,170,255,.035)" : "rgba(0,0,0,.04)";
  if (hot(l)) return d ? "rgba(170,236,255,.78)" : "#0c1a3a";
  if (l.inf) return d ? "rgba(167,139,250,.42)" : "rgba(90,60,200,.38)";
  if (l.rel === "part_of") return d ? "rgba(56,225,255,.16)" : "rgba(10,90,160,.16)";
  if (l.con) return d ? "rgba(207,232,255,.12)" : "rgba(60,70,90,.16)";
  if (l.rel === "importe") return d ? "rgba(96,165,250,.30)" : "rgba(40,60,120,.28)";
  return d ? "rgba(251,191,36,.62)" : "rgba(170,110,0,.7)";
}
function particleColor(l){
  if (hot(l)) return dark() ? "#ffffff" : "#0c1a3a";
  if (l.rel === "importe") return "#93c5fd";
  if (l.rel === "part_of") return "#67e8f9";
  return "#fcd34d";
}

// ------------------------------------------------------------------ effets three.js (même révision que la bibliothèque 3D)
async function loadFX(){
  const rev = window.__THREE__;
  if (!rev) return false;
  const bases = [`https://cdn.jsdelivr.net/npm/three@0.${rev}.0`, `https://esm.sh/three@0.${rev}.0`];
  try {
    delete window.__THREE__;  // même révision que celle de la bibliothèque : pas d'avertissement « plusieurs three.js »
    for (const base of bases){
      try {
        const jsd = base.includes("jsdelivr");
        FX.T = await import(base + (jsd ? "/+esm" : ""));
        try { FX.Bloom = (await import(base + "/examples/jsm/postprocessing/UnrealBloomPass.js" + (jsd ? "/+esm" : ""))).UnrealBloomPass; } catch (e) {}
        break;
      } catch (e) { FX.T = null; }
    }
  } finally { window.__THREE__ = rev; }
  return !!FX.T;
}
function canvasTex(size, draw){
  const c = document.createElement("canvas"); c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const t = new FX.T.CanvasTexture(c); t.colorSpace = FX.T.SRGBColorSpace; return t;
}
function makeTextures(){
  FX.tex.glow = canvasTex(128, (g, s) => {
    const r = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(.16, "rgba(255,255,255,.62)");
    r.addColorStop(.42, "rgba(255,255,255,.16)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, s, s);
  });
  FX.tex.reticle = canvasTex(256, (g, s) => {
    const c = s / 2; g.strokeStyle = "#fff"; g.lineCap = "round";
    g.lineWidth = 5; for (let k = 0; k < 4; k++){ g.beginPath(); g.arc(c, c, s * .40, k * Math.PI / 2 + .22, (k + 1) * Math.PI / 2 - .22); g.stroke(); }
    g.lineWidth = 2; g.globalAlpha = .55; g.beginPath(); g.arc(c, c, s * .47, 0, Math.PI * 2); g.stroke();
    g.globalAlpha = 1; g.lineWidth = 6;
    for (let k = 0; k < 4; k++){ const a = k * Math.PI / 2; g.beginPath();
      g.moveTo(c + Math.cos(a) * s * .30, c + Math.sin(a) * s * .30); g.lineTo(c + Math.cos(a) * s * .36, c + Math.sin(a) * s * .36); g.stroke(); }
  });
  const neb = col => canvasTex(256, (g, s) => {
    const r = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    r.addColorStop(0, col.replace("A", ".9")); r.addColorStop(.35, col.replace("A", ".35")); r.addColorStop(1, col.replace("A", "0"));
    g.fillStyle = r; g.fillRect(0, 0, s, s);
  });
  FX.tex.neb = [neb("rgba(124,58,237,A)"), neb("rgba(14,165,233,A)"), neb("rgba(219,39,119,A)"), neb("rgba(45,212,191,A)")];
}
function geo(name){
  const T = FX.T;
  if (!FX.geo[name]) FX.geo[name] = {sphere: () => new T.SphereGeometry(1, 28, 20), ico: () => new T.IcosahedronGeometry(1, 0),
    ring: () => new T.TorusGeometry(1, .024, 6, 112), ring2: () => new T.TorusGeometry(1, .013, 6, 112),
    wave: () => new T.RingGeometry(.92, 1, 72), radar: () => new T.RingGeometry(.975, 1, 128)}[name]();
  return FX.geo[name];
}
function nodeObject(n){
  const T = FX.T, r = radius(n), col = new T.Color(baseColor(n));
  const g = new T.Group();
  const fx = n.__fx = {r, phase: Math.random() * Math.PI * 2, op: 0, appear: 0, t0: null, born: false, flare: 1, parts: [], group: g};
  const add = (obj, base, extra) => { obj.userData = Object.assign({base}, extra || {}); g.add(obj); fx.parts.push(obj); return obj; };
  const basic = o => new T.MeshBasicMaterial(Object.assign({color: col, transparent: true, opacity: 0}, o || {}));
  if (n.kind === "concept"){  // les concepts restent discrets : un cristal filaire, pas un astre
    add(new T.Mesh(geo("ico"), basic({wireframe: true, depthWrite: false})), .55, {crystal: true}).scale.setScalar(r * 1.15);
    add(new T.Mesh(geo("sphere"), basic()), .8).scale.setScalar(r * .28);
  } else {
    add(new T.Mesh(geo("sphere"), basic()), 1).scale.setScalar(r);
  }
  fx.halo = add(new T.Sprite(new T.SpriteMaterial({map: FX.tex.glow, color: col, transparent: true, opacity: 0, depthWrite: false,
    blending: dark() ? T.AdditiveBlending : T.NormalBlending})), n.kind === "file" ? .42 : n.kind === "concept" ? .22 : .55, {halo: true});
  fx.haloBase = r * (n.kind === "concept" ? 3 : n.t === "project" ? 4.6 : 3.7);
  fx.halo.scale.setScalar(fx.haloBase);
  if (n.t === "project"){
    [[1.9, 1.15, .55, "ring"], [2.45, -.55, -.32, "ring2"]].forEach(([k, tilt, spin, gname]) => {
      const ring = add(new T.Mesh(geo(gname), basic({depthWrite: false, blending: dark() ? T.AdditiveBlending : T.NormalBlending})), .6, {spin});
      ring.scale.setScalar(r * k); ring.rotation.x = tilt;
    });
  }
  return g;
}
function recolor(){
  if (!FX.T || !cur) return;
  const T = FX.T, blend = dark() ? T.AdditiveBlending : T.NormalBlending;
  for (const n of cur.nodes){
    const fx = n.__fx; if (!fx) continue;
    const col = new T.Color(baseColor(n));
    for (const p of fx.parts){ p.material.color.copy(col); if (p.userData.halo || p.userData.spin != null){ p.material.blending = blend; p.material.needsUpdate = true; } }
  }
}
function dressScene(){
  const T = FX.T, scene = G.scene();
  FX.space = new T.Group(); scene.add(FX.space);
  const N = 2400, pos = new Float32Array(N * 3), ph = new Float32Array(N), sz = new Float32Array(N), tint = new Float32Array(N * 3);
  const tints = [[.62, .74, 1], [.78, .66, 1], [.56, .96, 1], [1, 1, 1], [1, .78, .92]];
  for (let i = 0; i < N; i++){
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, rad = 1700 + Math.random() * 2800, s = Math.sqrt(1 - u * u);
    pos[i * 3] = rad * s * Math.cos(th); pos[i * 3 + 1] = rad * u; pos[i * 3 + 2] = rad * s * Math.sin(th);
    ph[i] = Math.random() * Math.PI * 2; sz[i] = Math.random() < .07 ? 11 + Math.random() * 8 : 3 + Math.random() * 5;
    tint.set(tints[i % tints.length], i * 3);
  }
  const sg = new T.BufferGeometry();
  sg.setAttribute("position", new T.BufferAttribute(pos, 3)); sg.setAttribute("phase", new T.BufferAttribute(ph, 1));
  sg.setAttribute("size", new T.BufferAttribute(sz, 1)); sg.setAttribute("tint", new T.BufferAttribute(tint, 3));
  FX.stars = new T.Points(sg, new T.ShaderMaterial({uniforms: {time: {value: 0}, gain: {value: 1}}, transparent: true, depthWrite: false,
    blending: T.AdditiveBlending,
    vertexShader: `attribute float phase; attribute float size; attribute vec3 tint; uniform float time; varying float vA; varying vec3 vC;
      void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = size * (900.0 / -mv.z);
      gl_Position = projectionMatrix * mv; vA = 0.35 + 0.65 * (0.5 + 0.5 * sin(time * 1.35 + phase)); vC = tint; }`,
    fragmentShader: `uniform float gain; varying float vA; varying vec3 vC;
      void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
      float a = pow(1.0 - d * 2.0, 1.7) * vA * gain; gl_FragColor = vec4(vC * a, a); }`}));
  FX.stars.frustumCulled = false; FX.space.add(FX.stars);
  FX.nebula = [];
  [[-2600, 900, -2200, 3600, 0], [2900, -700, -1500, 3200, 1], [600, 1600, 2800, 3000, 2], [-1800, -1500, 2400, 2800, 3]].forEach(([x, y, z, s, k]) => {
    const sp = new T.Sprite(new T.SpriteMaterial({map: FX.tex.neb[k], transparent: true, opacity: .13, depthWrite: false, blending: T.AdditiveBlending, fog: false}));
    sp.position.set(x, y, z); sp.scale.setScalar(s); FX.space.add(sp); FX.nebula.push(sp);
  });
  FX.grid = new T.Group(); scene.add(FX.grid);
  const pg = new T.PolarGridHelper(1, 12, 6, 128, 0x38e1ff, 0x1d4ed8);
  pg.material.transparent = true; pg.material.opacity = .15; pg.material.depthWrite = false; FX.grid.add(pg); FX.gridLines = pg;
  FX.radar = new T.Mesh(geo("radar"), new T.MeshBasicMaterial({color: 0x38e1ff, transparent: true, opacity: 0, depthWrite: false,
    blending: T.AdditiveBlending, side: T.DoubleSide}));
  FX.radar.rotation.x = -Math.PI / 2; FX.grid.add(FX.radar);
  FX.reticle = new T.Sprite(new T.SpriteMaterial({map: FX.tex.reticle, color: 0x38e1ff, transparent: true, opacity: 0, depthWrite: false,
    blending: T.AdditiveBlending}));
  scene.add(FX.reticle);
  scene.fog = new T.FogExp2(new T.Color(getComputedStyle(root).getPropertyValue("--bg").trim() || "#03050b"), .00042);
  if (FX.Bloom && G.postProcessingComposer){
    try { FX.bloom = new FX.Bloom(new T.Vector2(innerWidth, innerHeight), .8, .5, .22); G.postProcessingComposer().addPass(FX.bloom); }
    catch (e) { FX.bloom = null; }
  }
  applyFX();
}
function applyFX(){
  const on = FX.on, d = dark();
  if (FX.bloom) FX.bloom.enabled = on && d;
  if (FX.space) FX.space.visible = on && d;
  if (FX.grid) FX.grid.visible = on;
  if (FX.gridLines) FX.gridLines.material.opacity = d ? .15 : .22;
  if (G && G.scene() && G.scene().fog){ G.scene().fog.density = on ? (d ? .00042 : .00025) : 0;
    G.scene().fog.color.set(getComputedStyle(root).getPropertyValue("--bg").trim() || "#03050b"); }
  $("#fxBtn").setAttribute("aria-pressed", String(on));
  applySpin();
}
function shockwave(n){
  if (!FX.T || !n.__fx || !FX.on || n.x == null) return;
  const T = FX.T;
  const m = new T.Mesh(geo("wave"), new T.MeshBasicMaterial({color: new T.Color(baseColor(n)), transparent: true, opacity: .9, depthWrite: false,
    blending: dark() ? T.AdditiveBlending : T.NormalBlending, side: T.DoubleSide}));
  m.position.set(n.x, n.y, n.z); G.scene().add(m);
  FX.waves.push({m, t0: performance.now(), r: n.__fx.r});
}

// ------------------------------------------------------------------ graphe 3D
function makeGraph(el){
  const cfg = {controlType: "orbit", rendererConfig: {antialias: true, alpha: false, preserveDrawingBuffer: true}};
  try { const g = new ForceGraph3D(el, cfg); if (g && typeof g.graphData === "function") return g; } catch (e) {}
  return ForceGraph3D(cfg)(el);
}
function tip(n){
  const c = `style="--c:${baseColor(n)}"`;
  if (n.kind === "concept") return `<div class="scene-tip" ${c}><b>${esc(n.name)}</b><span>Concept · ${esc(n.ck)} · ${n.n} souvenirs</span></div>`;
  if (n.kind === "file") return `<div class="scene-tip" ${c}><b>${esc(n.name)}</b><span>${esc(short(n.d || n.title, 160))}</span></div>`;
  const t = TYPES[n.t] || [n.t];
  return `<div class="scene-tip" ${c}><b>${esc(n.title)}</b><span>${esc(t[0])}${n.p ? " · " + esc(n.p) : ""}</span></div>`;
}
function initGraph(){
  G = makeGraph(graphEl)
    .backgroundColor(getComputedStyle(root).getPropertyValue("--bg").trim() || "#03050b")
    .showNavInfo(false)
    .nodeId("id")
    .nodeLabel(tip)
    .nodeVal(nodeVal)
    .nodeRelSize(REL)
    .nodeOpacity(.95)
    .nodeResolution(18)
    .nodeColor(nodeColor)
    .nodeVisibility(n => !hidden(n))
    .linkVisibility(l => linkVis(l))
    .linkColor(linkColor)
    .linkOpacity(.7)
    .linkWidth(l => hot(l) ? .55 : 0)
    .linkCurvature(l => l.inf ? .22 : 0)
    .linkDirectionalParticles(l => hot(l) ? 3 : 0)
    .linkDirectionalParticleSpeed(l => hot(l) ? .007 : .0055)
    .linkDirectionalParticleWidth(l => hot(l) ? 2.4 : 1.7)
    .linkDirectionalParticleResolution(10)
    .linkDirectionalParticleColor(particleColor)
    .d3AlphaDecay(.022).d3VelocityDecay(.32).warmupTicks(40).cooldownTime(8000)
    .onNodeHover(n => { st.hover = n || null; graphEl.style.cursor = n ? "pointer" : ""; computeFocus(); redraw(); })
    .onNodeClick((n, ev) => { if (ev && ev.shiftKey && st.sel && st.sel.id !== n.id) return showPath(st.sel, n); shockwave(n); select(n); flyTo(n); })
    .onBackgroundClick(() => { if (st.sel){ st.sel = null; computeFocus(); redraw(); closePanel(); } })
    .onEngineStop(() => autoFit(900));
  if (FX.T){ G.nodeThreeObject(nodeObject).nodeThreeObjectExtend(false); dressScene(); }
  G.cameraPosition({x: 0, y: 140, z: 2900});  // démarrage : la caméra arrive de loin
  const c = G.controls && G.controls();
  if (c && c.addEventListener) c.addEventListener("start", () => { st.userMoved = true; });
  if (c){ c.enableDamping = true; c.dampingFactor = .08; }
  window.addEventListener("resize", () => { G.width(innerWidth).height(innerHeight); if (FX.bloom) FX.bloom.setSize(innerWidth, innerHeight); });
  requestAnimationFrame(frame);
}
function pullForce(strength){  // rappel doux vers le centre : les souvenirs isolés ne partent plus au loin
  let nodes = [], deg = new Map();
  const f = alpha => { for (const n of nodes){ const k = strength * alpha * ((deg.get(n.id) || 0) ? 1 : 4);
    n.vx -= n.x * k; n.vy -= n.y * k; n.vz -= (n.z || 0) * k; } };
  f.initialize = ns => { nodes = ns; deg = new Map(ns.map(n => [n.id, (cur.adj.get(n.id) || new Set()).size])); };
  return f;
}
function collideForce(pad){  // aucun nœud ne chevauche son voisin
  let nodes = [];
  const f = alpha => {
    for (let i = 0; i < nodes.length; i++){
      const a = nodes[i], ra = radius(a);
      for (let j = i + 1; j < nodes.length; j++){
        const b = nodes[j], min = (ra + radius(b)) * 1.25 + pad;
        let dx = b.x - a.x, dy = b.y - a.y, dz = (b.z || 0) - (a.z || 0), d2 = dx * dx + dy * dy + dz * dz;
        if (d2 >= min * min) continue;
        const d = Math.sqrt(d2) || .01, push = (min - d) / d * .5 * Math.min(1, alpha * 4);
        dx *= push; dy *= push; dz *= push;
        b.vx += dx; b.vy += dy; b.vz += dz; a.vx -= dx; a.vy -= dy; a.vz -= dz;
      }
    }
  };
  f.initialize = ns => { nodes = ns; };
  return f;
}
function forces(){
  const link = G.d3Force("link"), charge = G.d3Force("charge");
  if (cur.map){ if (link) link.distance(30); if (charge){ charge.strength(-55); charge.distanceMax && charge.distanceMax(240); } }
  else { if (link) link.distance(l => l.inf ? 100 : l.con ? 58 : l.rel === "part_of" ? 76 : 60);
         if (charge){ charge.strength(-190); charge.distanceMax && charge.distanceMax(280); } }  // de l'air entre les nœuds
  G.d3Force("pull", pullForce(cur.map ? .02 : .03));
  G.d3Force("collide", collideForce(cur.map ? 2 : 6));
}
let redrawQueued = false;
function redraw(){
  if (redrawQueued || !G) return;
  redrawQueued = true;
  requestAnimationFrame(() => {
    redrawQueued = false;
    G.nodeColor(n => nodeColor(n)).linkColor(l => linkColor(l)).linkWidth(l => hot(l) ? .55 : 0)
     .linkDirectionalParticleWidth(l => hot(l) ? 2.4 : 1.7)
     .linkDirectionalParticleColor(particleColor)
     .nodeVisibility(n => !hidden(n))
     .linkDirectionalParticles(l => hot(l) ? 3 : 0)
     .linkVisibility(l => linkVis(l));
  });
}
function autoFit(ms){ if (G && !st.userMoved) G.zoomToFit(ms, 80); }  // cadrage tant que l'utilisateur n'a pas bougé la vue
function flyTo(n, ms){
  if (n.x == null) return;
  const d = (n.kind === "file" ? 90 : 135) + 16 * Math.sqrt(nodeVal(n)), r = Math.hypot(n.x, n.y, n.z) || 1, k = 1 + d / r;
  G.cameraPosition({x: n.x * k, y: n.y * k, z: n.z * k}, {x: n.x, y: n.y, z: n.z}, ms == null ? 1200 : ms);
}
function flyToSet(ids){
  const pts = [...ids].map(i => cur.byId.get(i)).filter(n => n && n.x != null);
  if (!pts.length) return;
  if (pts.length === 1) return flyTo(pts[0]);
  G.zoomToFit(1000, 90, n => ids.has(n.id));
}
function materialize(){  // les nœuds apparaissent en vague, du centre vers l'extérieur
  const now = performance.now(), pts = cur.nodes.filter(n => n.x != null);
  if (!pts.length) return;
  const cx = pts.reduce((s, n) => s + n.x, 0) / pts.length, cy = pts.reduce((s, n) => s + n.y, 0) / pts.length,
        cz = pts.reduce((s, n) => s + n.z, 0) / pts.length;
  const order = pts.map(n => [Math.hypot(n.x - cx, n.y - cy, n.z - cz), n]).sort((a, b) => a[0] - b[0]);
  const span = motionOn() ? 1100 : 0;
  order.forEach(([d, n], i) => { if (n.__fx){ n.__fx.t0 = now + 120 + span * i / order.length; n.__fx.born = true; } });
}

// ------------------------------------------------------------------ animation (une seule boucle)
let lastT = performance.now(), lastInput = performance.now(), fpsAcc = 0, fpsN = 0, fpsT = 0, impulseAcc = 0, radarT = 0;
["pointerdown", "wheel", "keydown", "touchstart"].forEach(ev => addEventListener(ev, () => {
  lastInput = performance.now(); if (FX.idleSpin){ FX.idleSpin = false; applySpin(); } }, {passive: true}));
function applySpin(){
  const c = G && G.controls && G.controls(); if (!c) return;
  c.autoRotate = st.rotate || (FX.idleSpin && motionOn()); c.autoRotateSpeed = st.rotate ? .8 : .32;
}
function animateNodes(now, dt){
  const f = focal(), mo = motionOn(), d = dark(), k = Math.min(1, dt * 7);
  for (const n of cur.nodes){
    const fx = n.__fx; if (!fx) continue;
    if (!fx.group.visible){ fx.gone = true; continue; }
    if (fx.gone){ fx.gone = false; fx.t0 = now + Math.random() * 160; fx.appear = 0; }  // réapparition (filtre, chronologie)
    if (!fx.born && now - viewStart > 2600){ fx.t0 = now; fx.born = true; }  // filet de sécurité
    if (fx.t0 != null && now >= fx.t0){ const t = Math.min(1, (now - fx.t0) / (mo ? 760 : 1)); fx.appear = mo ? easeOutBack(t) : 1; if (t >= 1){ fx.t0 = null; fx.appear = 1; } }
    const vis = clamp(fx.appear, 0, 1), dim = !!st.focus && !st.focus.has(n.id);
    fx.op += ((dim ? .05 : 1) * vis - fx.op) * k;
    fx.dimk = (fx.dimk == null ? 0 : fx.dimk) + ((dim ? 1 : 0) - (fx.dimk || 0)) * k;  // hors focus : plus petit, sans halo
    const flareT = f && f.id === n.id ? 1.3 : (f && st.focus && st.focus.has(n.id) ? 1.1 : 1);
    fx.flare += (flareT - fx.flare) * Math.min(1, dt * 6);
    const breathe = mo ? 1 + .1 * Math.sin(now * .0022 + fx.phase) * (n.kind === "concept" ? .55 : 1) : 1;
    fx.group.scale.setScalar(Math.max(.001, fx.appear * (1 - .25 * fx.dimk)));
    fx.halo.scale.setScalar(fx.haloBase * breathe * fx.flare);
    for (const p of fx.parts){
      p.material.opacity = fx.op * p.userData.base * (p.userData.halo ? (d ? (FX.on ? 1 : .55) : .38) * (1 - .7 * fx.dimk) : 1);
      if (mo && p.userData.spin) p.rotation.z += p.userData.spin * dt;
      if (mo && p.userData.crystal){ p.rotation.y += .45 * dt; p.rotation.x += .17 * dt; }
    }
  }
}
function animateScene(now, dt){
  const mo = motionOn();
  if (FX.stars){ FX.stars.material.uniforms.time.value = mo ? now / 1000 : 0; if (mo) FX.space.rotation.y += dt * .006; }
  if (FX.grid && FX.grid.visible){  // la grille holographique suit la taille du cerveau
    const pts = cur.nodes.filter(n => n.x != null && n.__fx && n.__fx.group.visible);
    if (pts.length){
      let minY = Infinity, R = 0, cx = 0, cz = 0;
      for (const n of pts){ cx += n.x; cz += n.z; } cx /= pts.length; cz /= pts.length;
      for (const n of pts){ minY = Math.min(minY, n.y); R = Math.max(R, Math.hypot(n.x - cx, n.z - cz)); }
      const k = Math.min(1, dt * 2);
      FX.gridR += (R * 1.2 + 60 - FX.gridR) * k; FX.gridY += (minY - 70 - FX.gridY) * k;
      FX.grid.scale.setScalar(FX.gridR); FX.grid.position.y = FX.gridY;
      FX.grid.position.x += (cx - FX.grid.position.x) * k; FX.grid.position.z += (cz - FX.grid.position.z) * k;
    }
    if (mo) FX.grid.rotation.y += dt * .03;
    radarT = mo ? (radarT + dt / 4.2) % 1 : 0;
    FX.radar.scale.setScalar(.02 + radarT); FX.radar.material.opacity = mo ? Math.sin(Math.PI * radarT) * .22 : 0;
  }
  if (FX.reticle){
    const s = st.sel && st.sel.__fx && st.sel.x != null && st.sel.__fx.group.visible ? st.sel : null;
    const tgt = s && FX.on ? .95 : 0;
    FX.reticle.material.opacity += (tgt - FX.reticle.material.opacity) * Math.min(1, dt * 6);
    if (s){ FX.reticle.position.set(s.x, s.y, s.z); FX.reticle.scale.setScalar(s.__fx.r * 6.2 * (1 + (mo ? .05 * Math.sin(now * .004) : 0)));
      FX.reticle.material.color.set(baseColor(s)); }
    if (mo) FX.reticle.material.rotation += dt * .7;
  }
  const cam = G.camera();
  FX.waves = FX.waves.filter(w => {
    const t = (now - w.t0) / 700;
    if (t >= 1){ G.scene().remove(w.m); w.m.material.dispose(); return false; }
    w.m.quaternion.copy(cam.quaternion); w.m.scale.setScalar(w.r * (1.6 + 8 * easeOutCubic(t))); w.m.material.opacity = .9 * (1 - t);
    return true;
  });
}
function impulses(dt){  // influx neuronaux : des étincelles parcourent les liens au hasard
  if (!motionOn() || st.focus || document.hidden) return;
  impulseAcc += dt;
  const every = cur.map ? .1 : .16;
  if (!FX.pool) FX.pool = cur.links.filter(l => !l.inf && !l.con);
  while (impulseAcc > every){
    impulseAcc -= every;
    if (!FX.pool.length) return;
    const l = FX.pool[(Math.random() * FX.pool.length) | 0];
    if (l.__lineObj && typeof l.source === "object" && typeof l.target === "object" && l.source && l.target && linkVis(l)){
      try { G.emitParticle(l); } catch (e) { FX.pool = []; }  // jamais d'erreur qui casse l'animation
    }
  }
}
function frame(now){
  requestAnimationFrame(frame);  // reprogrammée d'abord : une erreur ponctuelle n'arrête jamais l'animation
  const dt = Math.min(.05, Math.max(0, (now - lastT) / 1000)); lastT = now;
  if (!G || !cur) return;
  try {
    if (FX.T){ animateNodes(now, dt); animateScene(now, dt); impulses(dt); }
    if (!FX.idleSpin && !st.rotate && motionOn() && !st.sel && !st.hover && now - lastInput > 12000){ FX.idleSpin = true; applySpin(); }
    placeLabels();
  } catch (e) { if (!frame.warned){ frame.warned = true; console.warn("animation :", e); } }
  fpsAcc += dt; fpsN++;
  if (now - fpsT > 600){ $("#fps").textContent = Math.round(fpsN / Math.max(fpsAcc, 1e-3)) + " i/s"; fpsAcc = 0; fpsN = 0; fpsT = now; }
}

// ------------------------------------------------------------------ étiquettes (calque HTML projeté, sans chevauchement)
let labelEls = new Map(), baseLabels = [];
function labelEl(n){
  let el = labelEls.get(n.id);
  if (!el){
    el = document.createElement("div");
    el.className = "lbl" + (n.t === "project" ? " big" : "");
    el.textContent = short(n.name, n.kind === "file" ? 30 : 36);
    el.style.setProperty("--c", baseColor(n));
    $("#labels").appendChild(el);
    el._w = el.offsetWidth || 120; el._h = el.offsetHeight || 18;
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
  baseLabels = [...arr.slice(0, cur.map ? 14 : 10), ...con.slice(0, 5)].map(n => n.id);  // les autres : au survol
}
function placeLabels(){
  const show = st.labels && $("#fallback").style.display !== "flex";
  const cam = G.camera(), e = cam.matrixWorldInverse.elements, w = innerWidth, h = innerHeight, f = focal();
  const want = [];
  if (f) want.push(f.id);
  if (st.focus && st.focus.size <= 40) st.focus.forEach(i => want.push(i));
  for (const i of baseLabels) want.push(i);
  const keep = new Set(want), placed = [];
  for (const [id, el] of labelEls) if (!keep.has(id)){ el.style.opacity = 0; }
  const seen = new Set();
  for (const id of want){
    if (seen.has(id)) continue; seen.add(id);
    const n = cur.byId.get(id); if (!n) continue;
    const el = labelEl(n);
    const fx = n.__fx;
    if (!show || n.x == null || hidden(n) || (fx && fx.appear < .6)){ el.style.opacity = 0; continue; }
    const zc = e[2] * n.x + e[6] * n.y + e[10] * n.z + e[14];
    if (zc > -5){ el.style.opacity = 0; continue; }
    const p = G.graph2ScreenCoords(n.x, n.y, n.z);
    const off = 10 + (fx ? fx.r * 900 / Math.max(60, -zc) : 8);
    const x = p.x - el._w / 2, y = p.y - off - el._h;
    if (x < -40 || y < -20 || x > w + 40 || y > h + 20){ el.style.opacity = 0; continue; }
    const box = [x - 3, y - 2, x + el._w + 3, y + el._h + 2];
    const isFocal = f && f.id === id;
    if (!isFocal && placed.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])){ el.style.opacity = 0; continue; }
    placed.push(box);
    let op = Math.max(.35, Math.min(1, 1.6 - (-zc) / 1500));
    if (st.focus) op = st.focus.has(n.id) ? 1 : .1;
    if (isFocal) op = 1;
    el.style.opacity = op;
    el.style.transform = `translate(${x | 0}px,${y | 0}px)`;
  }
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
function layoutTop(){
  if (innerWidth > 1100) root.style.setProperty("--toolsw", $("#tools").getBoundingClientRect().width + "px");
  const bar = $("#bar").getBoundingClientRect().bottom, tools = $("#tools").getBoundingClientRect().bottom;
  root.style.setProperty("--topl", (bar + 12) + "px");
  root.style.setProperty("--top", (Math.max(bar, tools) + 12) + "px");
}
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
  openPanel(`<h3>Chemin</h3><h2>${steps.length} saut${steps.length > 1 ? "s" : ""}</h2><ul class="list">${item(a.id, "départ")}${steps.map(([p, q, l]) => item(q, rel(l))).join("")}</ul>`
    + `<p class="muted" style="font-size:12px;margin-top:10px">Échap pour effacer · Maj+clic sur un autre nœud pour un autre chemin.</p>`);
}
function select(n){ st.path = null; st.userMoved = true; st.sel = n; st.groupFocus = null; computeFocus(); redraw(); showNode(n); }
function selectId(id){ const n = cur.byId.get(id); if (n){ shockwave(n); select(n); flyTo(n); } }
function focusGroup(ids, label){ st.sel = null; st.groupFocus = new Set(ids); st.focusLabel = label || ""; computeFocus(); redraw(); flyToSet(st.groupFocus); }

// ------------------------------------------------------------------ panneau
function openPanel(html){
  panel.innerHTML = `<button class="x" aria-label="Fermer">×</button>` + html;
  panel.classList.add("open"); panel.removeAttribute("inert"); panel.scrollTop = 0;
  panel.querySelectorAll(".list li").forEach((li, i) => li.style.setProperty("--i", Math.min(i, 24)));
  panel.querySelector(".x").onclick = closePanel;
  panel.querySelectorAll("[data-go]").forEach(b => b.onclick = ev => { ev.preventDefault(); selectId(b.dataset.go); });
  panel.querySelectorAll("[data-comm]").forEach(b => b.onclick = () => { const c = commById.get(+b.dataset.comm); if (c) focusGroup(c.members, c.label); });
  panel.querySelectorAll("[data-pair]").forEach(b => b.onclick = () => focusGroup(b.dataset.pair.split("|"), ""));
  panel.querySelectorAll("[data-concept]").forEach(b => b.onclick = () => { const c = cur.byId.get(b.dataset.concept); if (c) focusGroup([c.id, ...c.members], c.name); });
}
function closePanel(){ panel.classList.remove("open"); panel.setAttribute("inert", ""); }
function item(id, sub){
  const n = cur.byId.get(id); if (!n) return "";
  const c = baseColor(n);
  return `<li><button data-go="${esc(id)}"><span class="dot" style="background:${c};color:${c}"></span><span class="t">${esc(short(n.name, 80))}${sub ? `<small>${esc(sub)}</small>` : ""}</span></button></li>`;
}
function md(s){  // Markdown minimal et sûr : gras, code, liens [[id]] cliquables (tout est échappé d'abord)
  return esc(s).replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\[\[([a-z0-9][a-z0-9\-]*)(?:\|([^\]\n]+))?\]\]/g, (m, id, label) => cur.byId.has(id)
      ? `<a href="#" data-go="${id}" style="color:var(--accent)">${label || esc(cur.byId.get(id).name)}</a>` : m);
}
function dotChip(color, text){ return `<span class="chip"><span class="dot" style="background:${color};color:${color}"></span>${text}</span>`; }
function showConcept(n){
  const mem = n.members.map(i => cur.byId.get(i)).filter(Boolean).sort((a, b) => (b.pr || 0) - (a.pr || 0));
  openPanel(`<div class="meta">${dotChip(baseColor(n), "Concept · " + esc(n.ck))}</div>`
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
  let h = `<div class="meta">${dotChip(t[1], esc(t[0]))}`
    + (c ? `<button class="chip" data-comm="${c.id}"><span class="dot" style="background:${PALETTE[c.id % PALETTE.length]};color:${PALETTE[c.id % PALETTE.length]}"></span>${esc(short(c.label, 34))}</button>` : "")
    + `</div><h2>${esc(n.title)}</h2><div class="meta"><code>${esc(n.id)}</code>`
    + (n.p ? `<span>projet : <a href="#" data-go="${esc(n.p)}" style="color:var(--accent)">${esc(n.p)}</a></span>` : "")
    + `<span>importance ${n.imp || 3}/5</span><span>rappelé ${n.hits || 0}×</span><span>maj ${esc(n.upd || "?")}</span>`
    + `<span>centralité ${(n.pr || 0).toFixed(2)}</span></div>`;
  if (n.path) h += `<div class="meta" style="margin-top:6px"><code>${esc(n.path)}</code></div>`;
  if (n.tags && n.tags.length) h += `<div class="chips">${n.tags.map(x => `<span class="chip">#${esc(x)}</span>`).join("")}</div>`;
  if (n.body) h += `<div class="body">${md(n.body)}</div>`;
  if (n.t === "project"){
    const mem = DATA.nodes.filter(m => m.p === n.id).sort((a, b) => (b.pr || 0) - (a.pr || 0)).slice(0, 25);
    if (mem.length) h += `<h3>Souvenirs du projet · ${mem.length}</h3><ul class="list">${mem.map(m => item(m.id, (TYPES[m.t] || [m.t])[0])).join("")}</ul>`;
  }
  if (links.length) h += `<h3>Liens · ${links.length}</h3><ul class="list">${links.map(([id, r]) => item(id, r)).join("")}</ul>`;
  if (inf.length) h += `<h3>Liens déduits</h3><ul class="list">${inf.map(e => item(e.s === n.id ? e.t : e.s, `confiance ${e.conf} · ${e.why.join(", ")}`)).join("")}</ul>`;
  openPanel(h);
}
function showFile(n){
  const out = [], inn = [];
  for (const l of cur.links){ const s = idOf(l.source), d = idOf(l.target); if (s === n.id) out.push(d); else if (d === n.id) inn.push(s); }
  const mod = (cur.map.mods12 || []).find(x => x.key === n.mod);
  let h = `<div class="meta">${dotChip(baseColor(n), esc(mod ? mod.label : (n.mod || "(racine)")))}`
    + `<span class="chip">${esc(KIND[n.k] || n.k || "")}</span></div><h2>${esc(n.name)}</h2>`
    + `<div class="meta"><code>${esc(n.id)}</code>${n.lines ? `<span>${n.lines} lignes</span>` : ""}<span>centralité ${(n.pr || 0).toFixed(2)}</span></div>`
    + (n.d ? `<div class="body">${esc(n.d)}</div>` : "");
  if (out.length) h += `<h3>Importe · ${out.length}</h3><ul class="list">${out.slice(0, 40).map(i => item(i)).join("")}</ul>`;
  if (inn.length) h += `<h3>Importé par · ${inn.length}</h3><ul class="list">${inn.slice(0, 40).map(i => item(i)).join("")}</ul>`;
  openPanel(h);
}
function showReport(){
  if (cur.map){
    const m = cur.map;
    const mods = (m.mods12 || []).map((x, i) => `<li><button data-mod="${i}"><span class="dot" style="background:${PALETTE[i % PALETTE.length]};color:${PALETTE[i % PALETTE.length]}"></span><span class="t">${esc(x.label)}<small>${x.n} fichiers affichés</small></span></button></li>`).join("");
    const top = cur.nodes.slice().sort((a, b) => b.pr - a.pr).slice(0, 10);
    openPanel(`<h3>Carte</h3><h2>${esc(m.name)}</h2><div class="meta"><span>${m.nodes.length} fichiers affichés sur ${m.total}</span><span>générée le ${esc((m.generated || "").slice(0, 10))}</span></div>`
      + `<h3>Modules (communautés)</h3><ul class="list">${mods}</ul><h3>Fichiers les plus centraux</h3><ul class="list">${top.map(n => item(n.id, n.d)).join("")}</ul>`);
    panel.querySelectorAll("[data-mod]").forEach(b => b.onclick = () => { const i = +b.dataset.mod; focusGroup(cur.nodes.filter(n => n.c === i).map(n => n.id), ""); });
    return;
  }
  const comms = COMMS.filter(c => c.size >= 2);
  const by = id => cur.byId.get(id);
  let h = `<h3>Rapport</h3><h2>Le cerveau en un coup d'œil</h2><div class="meta"><span>${DATA.stats.memories} souvenirs</span><span>${DATA.stats.links} liens</span>`
    + `<span>${(DATA.inf || []).length} déduits</span><span>${comms.length} communautés</span></div>`
    + `<h3>Communautés</h3><ul class="list">${comms.map(c => `<li><button data-comm="${c.id}"><span class="dot" style="background:${PALETTE[c.id % PALETTE.length]};color:${PALETTE[c.id % PALETTE.length]}"></span><span class="t">${esc(c.label)}<small>${c.size} nœuds · ${esc((c.members || []).slice(0, 3).map(i => by(i) ? by(i).name : i).map(x => short(x, 34)).join(" · "))}</small></span></button></li>`).join("")}</ul>`;
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
    `<button data-k="${esc(x.k)}" aria-pressed="${!st.hidden.has(x.k)}"><span class="dot" style="background:${x.color};color:${x.color}"></span>${esc(short(x.label, 30))} <span class="muted">${x.n}</span></button>`).join("") + `</div>`;
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
function countUp(){  // compteurs qui défilent jusqu'à leur valeur
  const els = [...document.querySelectorAll("#stats b[data-n]")], t0 = performance.now(), dur = motionOn() ? 1100 : 1;
  const step = now => { const k = Math.min(1, (now - t0) / dur), e = easeOutCubic(k);
    els.forEach(b => b.textContent = Math.round(+b.dataset.n * e)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function setStats(){
  const chip = (n, label) => `<span class="stat"><b data-n="${n}">0</b> ${label}</span>`;
  if (cur.map){ const m = cur.map;
    $("#stats").innerHTML = chip(m.nodes.length, `/ ${m.total} fichiers`) + chip(cur.links.length, "imports") + `<span class="stat">carte du ${esc((m.generated || "").slice(0, 10))}</span>`;
  } else { const s = DATA.stats;
    $("#stats").innerHTML = chip(s.memories, "souvenirs") + chip(s.projects, "projets") + chip(s.links, "liens") + chip((DATA.inf || []).length, "déduits")
      + chip(COMMS.filter(c => c.size >= 2).length, "communautés");
  }
  countUp(); layoutTop();
}
function setView(v){
  st.view = v; st.sel = null; st.hover = null; st.q = ""; st.groupFocus = null; st.focus = null; st.path = null; st.until = null;
  st.hidden.clear(); $("#q").value = ""; FX.pool = null;
  const m = v === "mem" ? null : (DATA.maps || []).find(x => "map:" + x.pid === v);
  cur = m ? mapData(m) : memData();
  $("#color").disabled = !!m; $("#infBtn").disabled = !!m; $("#conBtn").disabled = !!m;
  initTimeline();
  closePanel();
  if (G){ viewStart = performance.now();
          G.warmupTicks(m ? 120 : 70).cooldownTime(m ? 6000 : 8000);  // disposition pré-calculée : cadrage immédiat
          G.graphData({nodes: cur.nodes, links: cur.links}); forces();
          st.userMoved = false; (setView.ts || []).forEach(clearTimeout);
          const first = !setView.done; setView.done = true;
          setView.ts = [setTimeout(materialize, 60), setTimeout(() => autoFit(first && motionOn() ? 2400 : 700), first ? 260 : 120),
                        setTimeout(() => autoFit(900), 3400), setTimeout(() => autoFit(900), 6200)]; }
  pickLabels(); buildLegend(); setStats();
  if ($("#tablewrap").classList.contains("open")) buildTable();
}
function buildViews(){
  const sel = $("#view");
  sel.innerHTML = `<option value="mem">🧠 Mémoire</option>` + (DATA.maps || []).map(m =>
    `<option value="map:${esc(m.pid)}">🗺️ Carte · ${esc(short(m.name, 42))} (${m.nodes.length})</option>`).join("");
  sel.onchange = () => setView(sel.value);
}

// ------------------------------------------------------------------ thème, contrôles
function applyTheme(t){
  if (t === "light") root.setAttribute("data-theme", "light"); else root.removeAttribute("data-theme");
  $("#themeBtn").textContent = t === "light" ? "☀" : "☾";
  if (G){ G.backgroundColor(getComputedStyle(root).getPropertyValue("--bg").trim()); recolor(); applyFX(); redraw(); buildLegend(); pickLabels(); }
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
function toggleFX(){ FX.on = !FX.on; store.set("brain3d-fx", FX.on ? "on" : "off"); applyFX(); }
function controls(){
  let theme = store.get("brain3d-theme") || "dark";
  applyTheme(theme);
  $("#fxBtn").setAttribute("aria-pressed", String(FX.on));
  $("#themeBtn").onclick = () => { theme = theme === "light" ? "dark" : "light"; store.set("brain3d-theme", theme); applyTheme(theme); };
  $("#color").onchange = e => { st.color = e.target.value; st.hidden.clear(); buildLegend(); recolor(); pickLabels(); redraw(); if (st.sel) showNode(st.sel); };
  $("#infBtn").onclick = e => { st.inf = !st.inf; e.currentTarget.setAttribute("aria-pressed", String(st.inf)); redraw(); };
  st.concepts = true;
  $("#conBtn").onclick = e => { st.concepts = !st.concepts; e.currentTarget.setAttribute("aria-pressed", String(st.concepts)); redraw(); };
  $("#tl").oninput = e => { stopPlay(); setUntil(+e.target.value); };
  let play = null;
  const stopPlay = () => { if (play){ clearInterval(play); play = null; $("#playBtn").textContent = "▶"; } };
  $("#playBtn").onclick = () => {
    if (play) return stopPlay();
    let i = 0; setUntil(0); $("#playBtn").textContent = "⏸";
    play = setInterval(() => { i++; setUntil(i); if (i >= st.dates.length - 1) stopPlay(); }, 1000);
  };
  $("#lblBtn").onclick = e => { st.labels = !st.labels; e.currentTarget.setAttribute("aria-pressed", String(st.labels)); };
  $("#rotBtn").onclick = () => toggleRotate();
  $("#fxBtn").onclick = () => toggleFX();
  $("#fitBtn").onclick = () => G && G.zoomToFit(900, 80);
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
    else if (ev.key === "e" || ev.key === "E") toggleFX();
    else if (ev.key === "f" || ev.key === "F") G && G.zoomToFit(900, 80);
  });
}
function toggleRotate(){ st.rotate = !st.rotate; $("#rotBtn").setAttribute("aria-pressed", String(st.rotate)); applySpin(); }
function webgl(){ try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; } }
function fail(msg){ $("#boot").classList.add("done"); $("#fbmsg").textContent = msg; $("#fallback").style.display = "flex"; }
function loadScript(src){ return new Promise((ok, ko) => { const s = document.createElement("script"); s.src = src; s.async = true; s.onload = ok; s.onerror = ko; document.head.appendChild(s); }); }

(async function main(){
  controls(); buildViews(); layoutTop(); addEventListener("resize", layoutTop);
  cur = memData(); buildLegend();
  boot("chargement du moteur 3D…");
  for (const src of LIBS){ if (typeof window.ForceGraph3D === "function") break; try { await loadScript(src); } catch (e) {} }
  if (typeof window.ForceGraph3D !== "function") return fail("La bibliothèque 3D n'a pas pu être chargée (pas de connexion ?). La vue 2D fonctionne hors ligne.");
  if (!webgl()) return fail("WebGL n'est pas disponible dans ce navigateur.");
  boot("activation des effets…");
  try { await loadFX(); } catch (e) { FX.T = null; }
  if (FX.T) makeTextures();
  boot("connexion des synapses…");
  initGraph(); setView("mem");
  setTimeout(() => $("#boot").classList.add("done"), 380);
  setTimeout(() => { $("#boot").style.display = "none"; }, 1400);  // retiré après le fondu (même si l'onglet était en arrière-plan)
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash && cur.byId.has(hash)) setTimeout(() => selectId(hash), 2600);
})();
</script>
</body>
</html>
"""
