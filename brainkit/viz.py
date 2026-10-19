"""Visualisations du cerveau (façon graph.html de graphify).

- cerveau.html : vue 3D (3d-force-graph / three.js) — communautés en couleur, taille = centralité, liens explicites
  animés, liens déduits en courbes, panneau de détails, rapport, recherche, tableau ; cartes de projets en 3D.
- cerveau-2d.html : la vue 2D d'origine, 100 % locale (fonctionne hors ligne), mêmes données.
Les cartes de projets (map.json, jusqu'à plusieurs Mo) sont résumées une fois puis mises en cache (state/vizmaps).
Le cerveau montre aussi ce qu'il sait faire et ce qu'il suit : chaque skill métier (cerveau e-commerce…) avec ses
modules et ses outils, et chaque boutique suivie (`brain boutique`), reliée à sa fiche et à son plan."""
from __future__ import annotations

import json
from collections import Counter

from .common import (BRAIN_DIR, GRAPH_FILE, PLUGIN, PROJECTS_DIR, STATE_DIR, VIZ2D_FILE, VIZ_FILE, fold, log,
                     now_iso, read_json, write_json, write_text)
from .store import Brain

VIZMAP_DIR = STATE_DIR / "vizmaps"
VIZMAP_VERSION = 2
SKILL_LABELS = {"ecommerce": "Cerveau e-commerce"}
SKILL_ICONS = {"ecommerce": "🛒"}
VIRTUAL = ("skill", "boutique")  # nœuds de la vue qui ne sont pas des souvenirs


def _first(path, chars=360) -> tuple:
    """(titre, premier paragraphe) d'un module Markdown ou (première ligne de docstring, suite) d'un outil Python."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path.stem, ""
    if path.suffix == ".py":
        import re
        m = re.search(r'"""(.*?)"""', text, re.S)
        doc = (m.group(1) if m else "").strip().splitlines()
        return (doc[0] if doc else path.name), " ".join(x.strip() for x in doc[1:6] if x.strip())[:chars]
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":  # en-tête YAML d'une skill : sauté
        end = next((i for i, x in enumerate(lines[1:], 1) if x.strip() == "---"), 0)
        lines = lines[end + 1:]
    title = next((x[2:].strip() for x in lines if x.startswith("# ")), path.stem)
    para, started = [], False
    for x in lines:
        if x.strip() and not x.startswith("#") and not x.startswith("|"):
            para.append(x.strip())
            started = True
        elif started:
            break
    return title, " ".join(para)[:chars]


def _skills_and_shops(ids: set, comms: list, prs: dict, projects: dict = None) -> tuple:
    """Skills métier (avec modules et outils) et boutiques suivies, en nœuds de la vue ; une boutique est reliée au
    projet qui porte son nom. → (nœuds, liens, groupes, entrées du menu des vues : une par skill, une par boutique)."""
    nodes, edges, groups, views = [], [], [], []
    top = max(prs.values(), default=0.02) or 0.02
    next_id = max((c["id"] for c in comms if isinstance(c.get("id"), int)), default=-1) + 1

    def node(nid, t, title, body, imp=3, pr=0.0, tags=(), c=None):
        nodes.append({"id": nid, "t": t, "title": title, "body": body, "tags": list(tags), "p": None, "imp": imp,
                      "hits": 0, "upd": "", "path": None, "c": c, "pr": pr, "deg": 0, "cre": ""})

    hubs = {}
    try:
        from .install import skill_sources
        sources = skill_sources()
    except Exception as exc:
        log(f"viz (skills) : {exc!r}")
        sources = {}
    for name, src in sources.items():
        cid, next_id = next_id, next_id + 1
        hub = f"skill:{name}"
        hubs[name] = hub
        label = SKILL_LABELS.get(name, name)
        mods = sorted((src / "references").glob("*.md")) if (src / "references").is_dir() else []
        tools = sorted((src / "scripts").glob("*.py")) if (src / "scripts").is_dir() else []
        _, intro = _first(src / "SKILL.md")
        cmd = f"/cerveau:{name}" if PLUGIN else f"/{name}"
        node(hub, "skill", f"{label} ({cmd})",
             f"Skill métier livrée avec le cerveau : {len(mods)} fiches, {len(tools)} outils. {intro}".strip(),
             imp=5, pr=top * 0.9, tags=("skill", name), c=cid)
        members = [hub]
        for path in mods + tools:
            title, para = _first(path)
            nid = f"skill:{name}:{path.name}"
            node(nid, "skill", ("Outil · " if path.suffix == ".py" else "") + title, para, pr=top * 0.15,
                 tags=("skill", name), c=cid)
            edges.append({"s": nid, "t": hub, "r": "part_of"})
            members.append(nid)
        groups.append({"id": cid, "label": label, "size": len(members), "project": None, "words": [name],
                       "members": members})
        views.append({"icon": SKILL_ICONS.get(name, "🧩"), "label": label, "members": members})
    try:
        from . import boutique
        shops = boutique.all_shops() if (BRAIN_DIR / "boutiques").is_dir() else []
    except Exception as exc:
        log(f"viz (boutiques) : {exc!r}")
        shops = []
    if shops:
        cid = next_id
        members = []
        for s in shops:
            bid = f"boutique:{s['slug']}"
            last = (s.get("kpi") or [])[-1:]
            bits = [x for x in (s.get("url"), s.get("plateforme"), s.get("type")) if x]
            if last:
                k = last[0]
                num = lambda v: "?" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}".replace(".", ","))  # noqa: E731
                bits.append(f"semaine du {k.get('semaine')} : {num(k.get('sessions'))} sessions, "
                            f"{num(k.get('commandes'))} commandes"
                            + (f", CA {num(k.get('ca'))} €" if k.get("ca") is not None else ""))
            plan = s.get("plan") or []
            if plan:
                bits.append(f"plan : {len(plan)} étapes datées")
            if s.get("audits"):
                a = s["audits"][-1]
                bits.append(f"audit du {a.get('date')} : ✗ {a.get('x', 0)} · ⚠ {a.get('warn', 0)}")
            node(bid, "boutique", f"🏪 {s['nom']}", " · ".join(bits), imp=5, pr=top * 0.7,
                 tags=("boutique", s["slug"]), c=cid)
            members.append(bid)
            if "ecommerce" in hubs:
                edges.append({"s": bid, "t": hubs["ecommerce"], "r": "relates"})
            if s.get("fiche") in ids:
                edges.append({"s": bid, "t": s["fiche"], "r": "relates"})
            edges += [{"s": p["id"], "t": bid, "r": "part_of"} for p in plan if p.get("id") in ids]
            name = fold(s["nom"]).strip()
            if len(name) >= 4:  # « Atelier Lune » ↔ projet « Boutique Atelier Lune (Shopify…) » (et sa carte)
                edges += [{"s": bid, "t": pid, "r": "relates"} for pid, title in (projects or {}).items()
                          if name in fold(title)]
            near = {e["t"] if e["s"] == bid else e["s"] for e in edges if bid in (e["s"], e["t"])}
            views.append({"icon": "🏪", "label": s["nom"], "members": [bid, *sorted(near)]})
        groups.append({"id": cid, "label": "Boutiques suivies", "size": len(members), "project": None,
                       "words": ["boutique"], "members": members})
    elif "ecommerce" in hubs:  # le menu dit où les boutiques apparaîtront
        views.append({"icon": "🏪", "label": "Aucune boutique suivie pour l'instant", "members": None})
    return nodes, edges, groups, views


def _map_payload(p):
    from .mapper import BACKUP_RX, _kind, _label, _weight, file_desc
    m = read_json(PROJECTS_DIR / p["id"] / "map.json", None)
    if not m or not m.get("files"):
        return None
    files = m["files"]
    pr = {r: f["pr"] for r, f in files.items() if f.get("pr") and not f.get("dup")}
    linked = sorted(pr, key=lambda r: -_weight(r, pr))[:260]  # sauvegardes/exports relégués, copies exclues
    chosen = list(linked)
    if len(chosen) < 120:  # dossiers documentaires : on montre aussi les documents récents
        seen = set(linked)
        extra = sorted((r for r, f in files.items() if r not in seen and not f.get("dup")
                        and _kind(f) in ("doc", "data", "code")), key=lambda r: -files[r].get("mtime", 0))
        chosen += extra[: 120 - len(chosen)]
    keep = set(chosen)
    mods = Counter(files[r].get("mod") for r in chosen if files[r].get("mod") is not None)
    ordered = sorted(mods.items(), key=lambda kv: (bool(BACKUP_RX.search((kv[0] or "") + "/")), -kv[1]))
    top = [k for k, _ in ordered[:3]]
    nodes = [{"id": r, "k": _kind(files[r]), "mod": files[r].get("mod"), "pr": files[r].get("pr", 0),
              "d": file_desc(files[r]), "lines": files[r].get("lines")} for r in chosen]
    edges = [[r, t] for r in chosen for t in files[r].get("out", []) if t in keep]
    return {"pid": p["id"], "name": p["title"], "generated": m.get("meta", {}).get("generated", ""),
            "total": len(files), "nodes": nodes, "edges": edges, "mods": top,
            "mlabels": {str(k): _label(k, 48) for k in top},
            "mods12": [{"key": k, "label": _label(k, 44), "n": n} for k, n in ordered[:12]]}


def _map_payload_cached(p):
    """Résumé d'une carte pour la visualisation, recalculé seulement quand map.json change."""
    src = PROJECTS_DIR / p["id"] / "map.json"
    try:
        st = src.stat()
    except OSError:
        return None
    sig = [VIZMAP_VERSION, st.st_mtime_ns, st.st_size, p["title"]]
    cache = VIZMAP_DIR / f"{p['id']}.json"
    got = read_json(cache, None)
    if isinstance(got, dict) and got.get("sig") == sig:
        return got.get("payload")
    payload = _map_payload(p)
    try:
        write_json(cache, {"sig": sig, "payload": payload}, indent=None)
    except Exception as exc:
        log(f"cache viz {p['id']} : {exc!r}")
    return payload


def is_stale() -> bool:
    """La visualisation est-elle plus ancienne que le graphe ou qu'une carte de projet ?"""
    try:
        t = VIZ_FILE.stat().st_mtime
    except OSError:
        return True
    try:
        if GRAPH_FILE.stat().st_mtime > t:
            return True
        if any(b.stat().st_mtime > t for b in (BRAIN_DIR / "boutiques").glob("*.json")):  # boutique suivie modifiée
            return True
        return any(m.stat().st_mtime > t for m in PROJECTS_DIR.glob("*/map.json"))
    except OSError:
        return True


def render(brain=None):
    from . import graph
    from .viz3d import LIBS, TEMPLATE_3D
    brain = brain or Brain.load()
    an = graph.ensure(brain)
    comm, prs, deg = an.get("comm", {}), an.get("pr", {}), an.get("deg", {})
    nodes = []
    for n in brain.nodes.values():
        if n.get("status", "active") != "active":
            continue
        body = n.get("body", "")
        nodes.append({"id": n["id"], "t": n["type"], "title": n["title"],
                      "body": body if len(body) <= 1500 else body[:1499] + "…",
                      "tags": n.get("tags", []), "p": n.get("project"), "imp": n.get("importance", 3),
                      "hits": n.get("hits", 0), "upd": (n.get("updated") or "")[:10],
                      "path": (n.get("meta") or {}).get("path") if n["type"] == "project" else None,
                      "c": comm.get(n["id"]), "pr": prs.get(n["id"], 0), "deg": deg.get(n["id"], 0),
                      "cre": (n.get("created") or "")[:10]})
    ids = {n["id"] for n in nodes}
    edges = [{"s": e["from"], "t": e["to"], "r": e["rel"]} for e in brain.edges if e["from"] in ids and e["to"] in ids]
    edges += [{"s": n["id"], "t": n["p"], "r": "part_of"} for n in nodes if n["p"] in ids and n["t"] != "project"]
    maps = [m for m in (_map_payload_cached(p) for p in brain.projects()) if m]
    comms = [{"id": c["id"], "label": c["label"], "size": c["size"], "project": c.get("project"), "words": c.get("words", []),
              "members": [i for i in c["members"] if i in ids]} for c in an.get("communities", [])]
    projects = {n["id"]: n["title"] for n in nodes if n["t"] == "project"}
    extra, extra_edges, extra_comms, views = _skills_and_shops(ids, comms, prs, projects)
    nodes += extra
    edges += extra_edges
    comms += extra_comms
    data = {"generated": now_iso(), "nodes": nodes, "edges": edges, "maps": maps, "views": views,
            "inf": [e for e in an.get("inferred", []) if e["s"] in ids and e["t"] in ids],
            "comms": comms, "key": an.get("key", []),
            "concepts": [{"id": c["id"], "label": c["label"], "kind": c["kind"], "members": [i for i in c["members"] if i in ids]}
                         for c in an.get("concepts", [])], "bridges": an.get("bridges", []), "dups": an.get("dups", []),
            "gaps": an.get("gaps", {}), "questions": an.get("questions", []),
            "stats": {"memories": sum(1 for n in nodes if n["t"] != "project" and n["t"] not in VIRTUAL),
                      "projects": sum(1 for n in nodes if n["t"] == "project"), "links": len(edges), "maps": len(maps),
                      "skills": sum(1 for c in extra_comms if c["label"] != "Boutiques suivies"),
                      "shops": sum(1 for n in nodes if n["t"] == "boutique")}}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    write_text(VIZ_FILE, TEMPLATE_3D.replace("__LIBS__", json.dumps(list(LIBS))).replace("__DATA__", payload))
    write_text(VIZ2D_FILE, TEMPLATE_2D.replace("__DATA__", payload))
    return VIZ_FILE


TEMPLATE_2D = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cerveau de Claude</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--hover:rgba(11,11,11,.05);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--other:#898781}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--hover:rgba(255,255,255,.06);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--other:#898781}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--hover:rgba(255,255,255,.06);--s1:#3987e5;--s2:#d95926;
--s3:#199e70;--other:#898781}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:20px 16px 40px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:12px}
h1{font-size:22px;margin:0;font-weight:650}
.stats{color:var(--ink2);font-size:13px}
.spacer{flex:1}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
select,input[type=search],button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:6px 10px}
button{cursor:pointer}button:hover,select:hover{background:var(--hover)}
input[type=search]{min-width:160px;flex:1 1 200px}
.legend{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.leg{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;font-size:13px;color:var(--ink2)}
.leg[aria-pressed=false]{opacity:.45;text-decoration:line-through}
.shapes{font-size:12px;color:var(--muted);display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:12px}
@media (max-width:860px){.layout{grid-template-columns:1fr}}
.card{position:relative;background:var(--surface);border:1px solid var(--ring);border-radius:12px;height:min(72vh,700px);min-height:360px;overflow:hidden}
canvas{display:block;touch-action:none;cursor:grab}
.tools{position:absolute;right:10px;top:10px;display:flex;flex-direction:column;gap:6px}
.tools button{width:34px;height:34px;padding:0;font-size:16px;line-height:1}
.tip{position:absolute;pointer-events:none;max-width:280px;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 16px rgba(0,0,0,.14);display:none;z-index:2}
.tip .sub{color:var(--ink2)}.tip p{margin:4px 0 0;color:var(--ink2)}
.panel{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px;overflow:auto;max-height:min(72vh,700px)}
.panel h2{font-size:16px;margin:0 0 6px;overflow-wrap:anywhere}.panel h3{font-size:13px;margin:14px 0 4px;color:var(--ink2)}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink2)}
.body{white-space:pre-wrap;font-size:13.5px;line-height:1.5;margin-top:10px;overflow-wrap:anywhere}
.muted{color:var(--muted)}.small{font-size:12px}
.links{list-style:none;padding:0;margin:6px 0 0;display:flex;flex-wrap:wrap;gap:6px}
.links button{font-size:12.5px;padding:3px 8px;text-align:left}
.tablewrap{margin-top:12px;background:var(--surface);border:1px solid var(--ring);border-radius:12px;overflow:auto;max-height:60vh}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{position:sticky;top:0;background:var(--surface);color:var(--ink2);font-weight:600}
td{font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
tr[tabindex]{cursor:pointer}tr[tabindex]:hover,tr[tabindex]:focus{background:var(--hover);outline:none}
.foot{margin-top:14px;color:var(--muted);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🧠 Cerveau de Claude</h1>
    <span class="stats" id="stats"></span>
    <span class="spacer"></span>
    <a href="cerveau.html" style="font:inherit;font-size:13px;color:var(--ink);border:1px solid var(--ring);border-radius:8px;padding:6px 10px;text-decoration:none">Vue 3D</a>
    <button id="theme" title="Thème">Thème : auto</button>
  </header>
  <div class="filters">
    <select id="view" aria-label="Vue"></select>
    <input type="search" id="q" placeholder="Rechercher (titre, contenu, tags, fichier)…" aria-label="Rechercher">
    <button id="tableBtn" aria-pressed="false">Vue tableau</button>
  </div>
  <div class="filters"><div class="legend" id="legend"></div><span class="shapes" id="shapes"></span></div>
  <div class="layout">
    <div class="card" id="card">
      <canvas id="cv" aria-label="Graphe interactif (le tableau donne le même contenu)"></canvas>
      <div class="tools">
        <button id="zin" title="Zoomer" aria-label="Zoomer">+</button>
        <button id="zout" title="Dézoomer" aria-label="Dézoomer">−</button>
        <button id="fit" title="Tout afficher" aria-label="Tout afficher">⤢</button>
      </div>
      <div class="tip" id="tip" role="status"></div>
    </div>
    <aside class="panel" id="panel" aria-live="polite"></aside>
  </div>
  <div class="tablewrap" id="tablewrap" hidden><table id="table"></table></div>
  <p class="foot" id="foot"></p>
</div>
<script>
(() => {
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const root = document.documentElement;
const cv = $('#cv'), ctx = cv.getContext('2d'), tip = $('#tip'), panel = $('#panel');
const TYPES = {user:['Profil','s1','circle'], feedback:['Règle','s1','diamond'], project:['Projet','s2','square'],
  decision:['Décision','s3','triangle'], fact:['Fait','s3','diamond'], learning:['Apprentissage','s3','circle'], reference:['Référence','other','square'],
  entity:['Entité','other','circle'], todo:['À faire','other','ring'], source:['Source','other','square'],
  concept:['Concept','s3','circle'], topic:['Sujet','s2','diamond'], analysis:['Analyse','s3','triangle'],
  skill:['Compétence','s2','diamond'], boutique:['Boutique','s2','square']};
const KIND = {code:['code','circle'], doc:['document','square'], data:['données','diamond'], asset:['média','triangle'], other:['autre','ring']};
const SLOTS = ['s1','s2','s3'];
const state = {view:null, hidden:new Set(), q:'', hover:null, sel:null, scale:1, tx:0, ty:0, w:0, h:0, dpr:1};
window.__cerveau = state;
let C = {};
const projTitle = id => { const p = DATA.nodes.find(n => n.id === id); return p ? p.title : (id || ''); };
const fmtDate = s => s ? s.split('-').reverse().join('/') : '';
const trunc = (s, n) => (s || '').length > n ? s.slice(0, n - 1) + '…' : (s || '');
function el(tag, text, cls){ const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
function readColors(){ const cs = getComputedStyle(root); for (const k of ['surface','ink','ink2','muted','grid','axis','s1','s2','s3','other']) C[k] = cs.getPropertyValue('--' + k).trim(); }
function swatch(fam, shape){
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', '14'); svg.setAttribute('height', '14'); svg.setAttribute('viewBox', '0 0 14 14'); svg.setAttribute('aria-hidden', 'true');
  let p;
  if (shape === 'square') { p = document.createElementNS(ns, 'rect'); p.setAttribute('x', '2'); p.setAttribute('y', '2'); p.setAttribute('width', '10'); p.setAttribute('height', '10'); p.setAttribute('rx', '2'); }
  else if (shape === 'diamond') { p = document.createElementNS(ns, 'polygon'); p.setAttribute('points', '7,1 13,7 7,13 1,7'); }
  else if (shape === 'triangle') { p = document.createElementNS(ns, 'polygon'); p.setAttribute('points', '7,1.5 13,12 1,12'); }
  else { p = document.createElementNS(ns, 'circle'); p.setAttribute('cx', '7'); p.setAttribute('cy', '7'); p.setAttribute('r', shape === 'ring' ? '4.5' : '5.5'); }
  if (shape === 'ring') { p.setAttribute('fill', 'none'); p.setAttribute('stroke', `var(--${fam})`); p.setAttribute('stroke-width', '2.5'); }
  else p.setAttribute('fill', `var(--${fam})`);
  svg.append(p); return svg;
}

function memoryView(keep){  // keep : seulement ces nœuds (entrée « Cerveau e-commerce », une boutique…)
  const src = keep ? DATA.nodes.filter(n => keep.has(n.id)) : DATA.nodes;
  const nodes = src.map(n => ({...n, label:n.title, r: n.t === 'project' ? 11 : 5 + (n.imp || 3) * 1.2 + Math.min(n.hits || 0, 10) * 0.3}));
  const legend = Object.entries(TYPES).map(([k, [label, fam, shape]]) => ({key:k, label, fam, shape, count:nodes.filter(n => n.t === k).length})).filter(x => x.count);
  return {nodes, edges:keep ? DATA.edges.filter(e => keep.has(e.s) && keep.has(e.t)) : DATA.edges, legend, shapesNote:'',
    keyOf:n => n.t, famOf:n => TYPES[n.t][1], shapeOf:n => TYPES[n.t][2],
    always:n => n.t === 'project' || (n.imp || 3) >= 4,
    text:n => [n.title, n.body, (n.tags || []).join(' '), n.id].join(' ').toLowerCase(),
    describe:n => ({title:n.title, sub:TYPES[n.t][0] + (n.p ? ' · ' + projTitle(n.p) : ''),
      meta:`importance ${n.imp}/5 · rappelé ${n.hits || 0}× · maj ${fmtDate(n.upd)}` + ((n.tags || []).length ? ' · #' + n.tags.join(' #') : '') + (n.path ? ' · ' + n.path : '') + ' · id ' + n.id,
      body:n.body}),
    columns:['Type','Titre','Projet','Importance','Rappels','Mis à jour'],
    row:n => [TYPES[n.t][0], n.title, n.t === 'project' ? (n.path || '') : projTitle(n.p), n.imp, n.hits || 0, fmtDate(n.upd)],
    sort:(a, b) => Object.keys(TYPES).indexOf(a.t) - Object.keys(TYPES).indexOf(b.t) || (b.imp || 0) - (a.imp || 0)};
}
function mapView(m){
  const top = m.mods || [];
  const keyOf = n => top.includes(n.mod) ? String(n.mod) : '__other';
  const famOf = n => { const i = top.indexOf(n.mod); return i >= 0 ? SLOTS[i] : 'other'; };
  const N = m.nodes.length;
  const nodes = m.nodes.map(f => ({...f, title:f.id, label:f.id.split('/').pop(), r: 4 + Math.min(12, Math.sqrt((f.pr || 0) * N) * 5)}));
  const ranked = [...nodes].sort((a, b) => (b.pr || 0) - (a.pr || 0)).slice(0, 12);
  const legend = top.map((mod, i) => ({key:String(mod), label:'module ' + ((m.mlabels || {})[String(mod)] || mod || '(racine)'), fam:SLOTS[i], shape:'circle', count:nodes.filter(n => keyOf(n) === String(mod)).length}));
  const rest = nodes.filter(n => keyOf(n) === '__other').length;
  if (rest) legend.push({key:'__other', label:'autres modules / hors graphe', fam:'other', shape:'circle', count:rest});
  return {nodes, edges:m.edges.map(([s, t]) => ({s, t, r:'import'})), legend, shapesNote:'formes :',
    keyOf, famOf, shapeOf:n => (KIND[n.k] || KIND.other)[1], always:n => ranked.includes(n),
    text:n => (n.id + ' ' + (n.d || '')).toLowerCase(),
    describe:n => ({title:n.id, sub:(KIND[n.k] || KIND.other)[0] + ' · module ' + (n.mod ?? '(hors graphe)'),
      meta:`centralité ${(n.pr || 0).toFixed(4)}` + (n.lines ? ` · ${n.lines} lignes` : ''), body:n.d}),
    columns:['Fichier','Type','Module','Centralité','Description'],
    row:n => [n.id, (KIND[n.k] || KIND.other)[0], n.mod ?? '—', (n.pr || 0).toFixed(4), n.d],
    sort:(a, b) => (b.pr || 0) - (a.pr || 0)};
}
const views = [['mem', 'Mémoire (' + DATA.stats.memories + ' souvenirs, ' + DATA.stats.projects + ' projets)', () => memoryView()]]
  .concat((DATA.views || []).map((g, i) => g.members
    ? ['v:' + i, `${g.icon} ${g.label} (${g.members.length})`, () => memoryView(new Set(g.members))]
    : ['v:' + i, `${g.icon} ${g.label}`, null, true]))
  .concat(DATA.maps.map(m => ['map:' + m.pid, `Carte · ${m.name} (${m.total} fichiers)`, () => mapView(m)]));

function setView(id){
  const entry = views.find(v => v[0] === id) || views[0];
  const v = entry[2]();
  v.byId = new Map(v.nodes.map(n => [n.id, n]));
  v.links = v.edges.map(e => ({a:v.byId.get(e.s), b:v.byId.get(e.t), r:e.r})).filter(l => l.a && l.b && l.a !== l.b);
  v.adj = new Map(v.nodes.map(n => [n, new Set()]));
  v.links.forEach(l => { v.adj.get(l.a).add(l.b); v.adj.get(l.b).add(l.a); });
  v.nodes.forEach((n, i) => { const a = i * 2.399963, rr = 14 * Math.sqrt(i + 1); n.x = Math.cos(a) * rr; n.y = Math.sin(a) * rr; n.vx = n.vy = 0; });
  state.view = v; state.hidden.clear(); state.sel = null; state.hover = null; state.moved = false;
  simulate(Math.min(320, 120 + 4 * v.nodes.length));
  buildLegend(); buildTable(); fit(); draw(); showPanel(null);
}
function simulate(iters){
  const v = state.view, ns = v.nodes, N = ns.length; if (!N) return;
  const kRep = 320, kSpr = 0.07, grav = 0.014;
  for (let it = 0; it < iters; it++) {
    const alpha = 1 - it / iters;
    for (let i = 0; i < N; i++) { const a = ns[i];
      for (let j = i + 1; j < N; j++) { const b = ns[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 > 160000) continue;
        if (d2 < 0.01) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = .5; }
        const f = kRep * alpha / d2; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f; } }
    for (const l of v.links) { const dx = l.b.x - l.a.x, dy = l.b.y - l.a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - (40 + l.a.r + l.b.r)) / d * kSpr * alpha;
      l.a.vx += dx * f; l.a.vy += dy * f; l.b.vx -= dx * f; l.b.vy -= dy * f; }
    for (const n of ns) { n.vx -= n.x * grav * alpha; n.vy -= n.y * grav * alpha;
      n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy)); n.vx *= .55; n.vy *= .55; }
  }
}
const visible = n => !state.hidden.has(state.view.keyOf(n));
const matches = n => !state.q || state.view.text(n).includes(state.q);
function fit(){
  const ns = state.view ? state.view.nodes.filter(visible) : [];
  if (!ns.length) { state.scale = 1; state.tx = state.w / 2; state.ty = state.h / 2; return; }
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of ns) { x0 = Math.min(x0, n.x - n.r); y0 = Math.min(y0, n.y - n.r); x1 = Math.max(x1, n.x + n.r + 150); y1 = Math.max(y1, n.y + n.r); }
  const pad = 36, s = Math.min((state.w - pad * 2) / Math.max(1, x1 - x0), (state.h - pad * 2) / Math.max(1, y1 - y0));
  state.scale = Math.min(2, Math.max(.15, s));
  state.tx = state.w / 2 - (x0 + x1) / 2 * state.scale; state.ty = state.h / 2 - (y0 + y1) / 2 * state.scale;
}
function resize(){
  const r = $('#card').getBoundingClientRect(); state.w = r.width; state.h = r.height; state.dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * state.dpr); cv.height = Math.round(r.height * state.dpr); cv.style.width = r.width + 'px'; cv.style.height = r.height + 'px';
}
function shapePath(n, kind, r){
  const x = n.x, y = n.y; ctx.beginPath();
  if (kind === 'square') { const k = r * .9; if (ctx.roundRect) ctx.roundRect(x - k, y - k, 2 * k, 2 * k, Math.min(3, k / 3)); else ctx.rect(x - k, y - k, 2 * k, 2 * k); }
  else if (kind === 'diamond') { const k = r * 1.15; ctx.moveTo(x, y - k); ctx.lineTo(x + k, y); ctx.lineTo(x, y + k); ctx.lineTo(x - k, y); ctx.closePath(); }
  else if (kind === 'triangle') { ctx.moveTo(x, y - r * 1.15); ctx.lineTo(x + r * 1.05, y + r * .8); ctx.lineTo(x - r * 1.05, y + r * .8); ctx.closePath(); }
  else ctx.arc(x, y, r, 0, Math.PI * 2);
}
function drawNode(n){
  const v = state.view, s = state.scale, kind = v.shapeOf(n), color = C[v.famOf(n)];
  shapePath(n, kind, n.r);
  if (kind === 'ring') { ctx.fillStyle = C.surface; ctx.fill(); ctx.lineWidth = Math.max(2 / s, n.r * .45); ctx.strokeStyle = color; ctx.stroke(); }
  else { ctx.fillStyle = color; ctx.fill(); ctx.lineWidth = 2 / s; ctx.strokeStyle = C.surface; ctx.stroke(); }
  if (n === state.sel) { ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 5 / s, 0, Math.PI * 2); ctx.lineWidth = 2 / s; ctx.strokeStyle = C.ink; ctx.stroke(); }
}
function draw(){
  const v = state.view, dpr = state.dpr, s = state.scale;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.fillStyle = C.surface; ctx.fillRect(0, 0, state.w, state.h);
  if (!v || !v.nodes.length) { ctx.fillStyle = C.ink2; ctx.font = '14px system-ui,sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Rien à afficher pour l’instant — le cerveau se remplit au fil des sessions.', state.w / 2, state.h / 2); return; }
  ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * state.tx, dpr * state.ty);
  const focus = state.sel || state.hover, near = focus ? v.adj.get(focus) : null;
  for (const l of v.links) {
    if (!visible(l.a) || !visible(l.b)) continue;
    const hot = focus && (l.a === focus || l.b === focus);
    ctx.globalAlpha = (focus && !hot) || (state.q && !(matches(l.a) && matches(l.b))) ? .22 : 1;
    ctx.strokeStyle = hot ? C.ink2 : C.axis; ctx.lineWidth = (hot ? 1.5 : 1) / s;
    ctx.beginPath(); ctx.moveTo(l.a.x, l.a.y); ctx.lineTo(l.b.x, l.b.y); ctx.stroke();
  }
  for (const n of v.nodes) {
    if (!visible(n)) continue;
    ctx.globalAlpha = (focus && n !== focus && !near.has(n)) || !matches(n) ? .18 : 1;
    drawNode(n);
  }
  ctx.globalAlpha = 1; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.font = '12px system-ui,-apple-system,"Segoe UI",sans-serif'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  const cands = v.nodes.filter(n => visible(n) && (n === focus || (near && near.has(n)) || (state.q ? matches(n) : (!focus && (v.always(n) || s > 1.6)))));
  cands.sort((a, b) => (b === focus) - (a === focus) || b.r - a.r);
  const boxes = [];
  for (const n of cands.slice(0, 90)) {
    const text = trunc(n.label, n === focus ? 60 : 32), w = ctx.measureText(text).width;
    const x = n.x * s + state.tx + n.r * s + 5, y = n.y * s + state.ty, box = [x - 2, y - 8, x + w + 2, y + 8];
    if (boxes.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
    boxes.push(box); ctx.lineWidth = 3; ctx.strokeStyle = C.surface; ctx.strokeText(text, x, y);
    ctx.fillStyle = n === focus ? C.ink : C.ink2; ctx.fillText(text, x, y);
  }
}
function hit(px, py){
  const v = state.view; if (!v) return null;
  const x = (px - state.tx) / state.scale, y = (py - state.ty) / state.scale;
  let best = null, bd = Infinity;
  for (const n of v.nodes) { if (!visible(n)) continue; const d = Math.hypot(n.x - x, n.y - y) - n.r; if (d < bd) { bd = d; best = n; } }
  return bd * state.scale <= 12 ? best : null;
}
function showTip(n, p){
  const d = state.view.describe(n); tip.replaceChildren();
  tip.append(el('strong', trunc(d.title, 80)), el('div', d.sub, 'sub'));
  if (d.body) tip.append(el('p', trunc(d.body.replace(/\s+/g, ' '), 160)));
  tip.style.display = 'block';
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.min(state.w - tw - 8, p.x + 14) + 'px'; tip.style.top = Math.min(state.h - th - 8, p.y + 14) + 'px';
}
const hideTip = () => { tip.style.display = 'none'; };
function showPanel(n){
  panel.replaceChildren();
  if (!n) { panel.append(el('h2', 'Mode d’emploi'), el('p', 'Survole un point pour un aperçu, clique pour le détail. Molette ou boutons pour zoomer, glisser pour déplacer le graphe ou un point. Les puces de légende filtrent ; la recherche estompe le reste.', 'muted'), el('p', 'Couleur = famille, forme = type. La vue tableau donne exactement le même contenu.', 'muted small')); return; }
  const v = state.view, d = v.describe(n);
  const chip = el('div', '', 'chip'); chip.append(swatch(v.famOf(n), v.shapeOf(n)), document.createTextNode(d.sub));
  panel.append(el('h2', d.title), chip);
  if (d.meta) panel.append(el('p', d.meta, 'muted small'));
  if (d.body) panel.append(el('div', d.body, 'body'));
  const neigh = [...v.adj.get(n)];
  if (neigh.length) {
    panel.append(el('h3', `Liens (${neigh.length})`));
    const ul = el('ul', '', 'links');
    neigh.slice(0, 50).forEach(m => { const li = el('li'), b = el('button', trunc(m.label, 46)); b.title = m.title || m.label; b.onclick = () => select(m, true); li.append(b); ul.append(li); });
    panel.append(ul);
  }
}
function select(n, center){
  state.sel = n; showPanel(n);
  if (n && center) { state.tx = state.w / 2 - n.x * state.scale; state.ty = state.h / 2 - n.y * state.scale; }
  draw();
}
function buildLegend(){
  const box = $('#legend'); box.replaceChildren();
  for (const item of state.view.legend) {
    const b = el('button', '', 'leg'); b.setAttribute('aria-pressed', String(!state.hidden.has(item.key)));
    b.append(swatch(item.fam, item.shape), document.createTextNode(`${item.label} (${item.count})`));
    b.onclick = () => { state.hidden.has(item.key) ? state.hidden.delete(item.key) : state.hidden.add(item.key);
      b.setAttribute('aria-pressed', String(!state.hidden.has(item.key))); draw(); buildTable(); };
    box.append(b);
  }
  const sh = $('#shapes'); sh.replaceChildren();
  if (state.view.shapesNote) { sh.append(document.createTextNode(state.view.shapesNote));
    for (const [label, shape] of Object.values(KIND)) { const s = el('span'); s.append(swatch('ink2', shape), document.createTextNode(' ' + label)); sh.append(s); } }
}
function buildTable(){
  const v = state.view, t = $('#table'); t.replaceChildren();
  const thead = el('thead'), hr = el('tr'); v.columns.forEach(c => hr.append(el('th', c))); thead.append(hr); t.append(thead);
  const tb = el('tbody');
  v.nodes.filter(n => visible(n) && matches(n)).sort(v.sort).forEach(n => {
    const r = el('tr'); r.tabIndex = 0;
    v.row(n).forEach(c => r.append(el('td', String(c ?? ''))));
    r.onclick = () => select(n, true); r.onkeydown = e => { if (e.key === 'Enter') select(n, true); };
    tb.append(r);
  });
  t.append(tb);
}
function zoomAt(px, py, k){
  state.moved = true;
  const s2 = Math.min(6, Math.max(.12, state.scale * k)); k = s2 / state.scale;
  state.tx = px - (px - state.tx) * k; state.ty = py - (py - state.ty) * k; state.scale = s2; draw();
}
const pos = e => { const r = cv.getBoundingClientRect(); return {x:e.clientX - r.left, y:e.clientY - r.top}; };
let down = null;
cv.addEventListener('pointerdown', e => { const p = pos(e); down = {x:p.x, y:p.y, n:hit(p.x, p.y), tx:state.tx, ty:state.ty, moved:false}; cv.setPointerCapture(e.pointerId); });
cv.addEventListener('pointermove', e => {
  const p = pos(e);
  if (down) { const dx = p.x - down.x, dy = p.y - down.y; if (Math.abs(dx) + Math.abs(dy) > 3) down.moved = true;
    if (!down.moved) return;
    state.moved = true;
    if (down.n) { down.n.x = (p.x - state.tx) / state.scale; down.n.y = (p.y - state.ty) / state.scale; }
    else { state.tx = down.tx + dx; state.ty = down.ty + dy; }
    hideTip(); draw(); return; }
  const n = hit(p.x, p.y); if (n !== state.hover) { state.hover = n; draw(); }
  n ? showTip(n, p) : hideTip(); cv.style.cursor = n ? 'pointer' : 'grab';
});
cv.addEventListener('pointerup', () => { if (down && !down.moved) select(down.n, false); down = null; });
cv.addEventListener('pointerleave', () => { if (!down) { state.hover = null; hideTip(); draw(); } });
cv.addEventListener('wheel', e => { e.preventDefault(); const p = pos(e); zoomAt(p.x, p.y, Math.exp(-e.deltaY * .0015)); }, {passive:false});
$('#zin').onclick = () => zoomAt(state.w / 2, state.h / 2, 1.3);
$('#zout').onclick = () => zoomAt(state.w / 2, state.h / 2, 1 / 1.3);
$('#fit').onclick = () => { state.moved = false; fit(); draw(); };
$('#q').addEventListener('input', e => { state.q = e.target.value.trim().toLowerCase(); draw(); buildTable(); });
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter') { const n = state.view.nodes.find(x => visible(x) && matches(x)); if (n) select(n, true); } });
$('#tableBtn').onclick = e => { const w = $('#tablewrap'); w.hidden = !w.hidden; e.target.setAttribute('aria-pressed', String(!w.hidden)); };
const sel = $('#view'); views.forEach(([id, label, , off]) => { const o = el('option', label); o.value = id; o.disabled = !!off; sel.append(o); });
sel.onchange = () => setView(sel.value);
const themes = ['auto', 'light', 'dark'], tlabel = {auto:'auto', light:'clair', dark:'sombre'};
let theme = 'auto'; try { theme = localStorage.getItem('cerveau-theme') || 'auto'; } catch (e) {}
function applyTheme(){ if (theme === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', theme);
  $('#theme').textContent = 'Thème : ' + tlabel[theme]; readColors(); draw(); }
$('#theme').onclick = () => { theme = themes[(themes.indexOf(theme) + 1) % 3]; try { localStorage.setItem('cerveau-theme', theme); } catch (e) {} applyTheme(); };
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readColors(); draw(); });
window.addEventListener('resize', () => { resize(); if (!state.moved) fit(); draw(); });
new ResizeObserver(() => { const r = $('#card').getBoundingClientRect(); if (Math.abs(r.width - state.w) > 1 || Math.abs(r.height - state.h) > 1) { resize(); if (!state.moved) fit(); draw(); } }).observe($('#card'));
const st = DATA.stats;
$('#stats').textContent = `${st.memories} souvenirs · ${st.projects} projets · ${st.links} liens · ${st.maps} carte(s) de projet`;
$('#foot').textContent = 'Généré le ' + DATA.generated.replace('T', ' à ') + ' par ~/.claude/brain (brain viz). Fichier local, rien n’est envoyé en ligne.';
resize(); if (theme !== 'auto') root.setAttribute('data-theme', theme); applyTheme(); setView('mem');
})();
</script>
</body>
</html>
"""
