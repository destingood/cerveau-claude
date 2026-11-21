"""PC, rapport : actions chiffrées (Go, cœurs), `brain pc`, `brain pc --clean [--oui]`.

Découpé de pc.py (étape 8 du plan) sans rien changer."""
import time

from .common import load_config, read_json, short, write_json
from .pc import BACKGROUND, BROWSERS, F_BRAIN, F_TERM, GB, MB, NCPU, NO_INHERIT, STATE_FILE, memory
from .pc_analyse import kill_orphans, measure


# ------------------------------------------------------------------------------------------ actions chiffrées
def _gb(b) -> str:
    return f"{b / GB:.1f}".replace(".", ",") + " Go"


def _size(b) -> str:
    return f"{b / MB:.0f} Mo" if b < GB else _gb(b)


def _pct(x) -> str:
    return f"{x:.1f}".replace(".", ",") + " %"


def _cores(pct) -> str:
    return f"{pct / 100 * NCPU:.1f}".replace(".", ",") + " cœur" + ("s" if pct / 100 * NCPU >= 2 else "")


def _dur(s) -> str:
    if s < 3600:
        return f"{s / 60:.0f} min"
    if s < 86400 * 2:
        return f"{s / 3600:.0f} h"
    return f"{s / 86400:.0f} j"


def _name(s) -> str:
    return s["title"] or s["uuid"] or f"pid {s['pid']}"


def idle_sessions(a, pcfg) -> list:
    # seulement les sessions que l'app connaît (app=True) : on ne propose d'archiver que ce qu'elle sait rouvrir
    return [s for s in a["sessions"] if s.get("app") and not s["current"] and not s["archived"]
            and s["idle"] >= pcfg["idle_hours"] * 3600]


def spinning_sessions(a, pcfg) -> list:
    """claude.exe qui brûle du CPU sans aucune activité depuis 15 min (boucle bloquée)."""
    return [s for s in a["sessions"] if s.get("uuid") and s["cpu_self"] / 100 * NCPU >= pcfg["spin_cores"]
            and s["idle"] >= 900]


def actions(a, pcfg) -> list:
    """(Go libérés, % CPU libéré, texte) — du plus gros gain au plus petit."""
    out = []
    idle = idle_sessions(a, pcfg)
    if idle:
        out.append((sum(s["ram"] for s in idle), sum(s["cpu"] for s in idle),
                    f"Archiver {len(idle)} session{'s' * (len(idle) > 1)} Claude inactive{'s' * (len(idle) > 1)} "
                    f"depuis plus de {pcfg['idle_hours']} h : −{_gb(sum(s['ram'] for s in idle))} (l'app arrête leur "
                    "processus et leurs serveurs MCP ; elles restent rouvrables dans « Archivées »)"))
    for s in spinning_sessions(a, pcfg):
        out.append((0 if s in idle else s["ram"], s["cpu_self"],
                    f"Session « {short(_name(s), 50)} » : tourne à vide ({_cores(s['cpu_self'])}, aucune activité "
                    f"depuis {_dur(s['idle'])}) → l'archiver, ou la relancer si elle est bloquée (en attendant : "
                    f"Gestionnaire des tâches, pid {s['pid']} → clic droit → Mode efficacité)"))
    auto = [o for o in a["orphans"] if o.get("auto")]
    man = [o for o in a["orphans"] if not o.get("auto")]
    if auto:
        ram = sum(o["ram"] for o in auto)
        out.append((ram, 0.0, f"{len(auto)} serveur(s) MCP sans session : −{_size(ram)} → `brain pc --clean` "
                              "les liste, `brain pc --clean --oui` les ferme (jamais fait automatiquement)"))
    if man:
        ram = sum(o["ram"] for o in man)
        kinds = ", ".join(sorted({o["kind"] for o in man}))
        out.append((ram, 0.0, f"{len(man)} processus Claude sans utilité ({kinds}) : −{_size(ram)} → "
                              "`brain pc --clean --oui` (jamais fait automatiquement)"))
    for d in a["servers"]:
        if d["copies"] >= 3 and d["uses"] is not None and d["uses"] <= 2 and d.get("plugin"):
            out.append((d["ram_active"], 0.0,
                        f"Plugin « {d['plugin']} » : lancé dans chaque session ({d['copies']} copies, {_gb(d['ram'])}), "
                        f"{d['uses']} appel(s) en {a.get('usage_days', 7)} j → le désactiver dans claude.ai "
                        f"(Paramètres → plugins) libère ≈ {_size(d['ram'] // max(1, d['copies']))} par session ouverte"))
    groups = {g["label"]: g for g in a["groups"]}
    term = groups.get(F_TERM)
    if term and term["ram"] >= 300 * MB:
        out.append((0, 0.0, f"Panneau Terminal : {_size(term['ram'])} ({term['n']} processus) → fermer les onglets "
                            "Terminal qui ne servent plus"))
    for b in sorted(BROWSERS & set(groups), key=lambda x: -groups[x]["ram"]):
        if groups[b]["ram"] >= 3 * GB:
            out.append((0, 0.0, f"{b} : {_gb(groups[b]['ram'])} ({groups[b]['n']} processus) → activer l'Économiseur "
                                "de mémoire (chrome://settings/performance) et fermer les onglets inutiles"))
    bg = sorted((g for g in a["groups"] if g["label"] in BACKGROUND and g["ram"] >= 200 * MB), key=lambda g: -g["ram"])
    if bg:
        out.append((0, 0.0, "Applis en fond, à fermer quand elles ne servent pas : "
                    + " · ".join(f"{g['label']} {_size(g['ram'])}" for g in bg[:6])))
    return out


def report(seconds=2.0, show_all=False, cfg=None) -> str:
    cfg = cfg or load_config()
    pcfg = cfg["pc"]
    a = measure(seconds, cfg)
    m, L = a["mem"], []
    gpu = a.get("gpu") or {}
    head = (f"RAM : {_gb(m['avail'])} libres sur {_gb(m['total'])} ({m['load']} % utilisés) · mémoire validée "
            f"{_gb(m['commit'])} / {_gb(m['commit_limit'])}")
    if a["cpu"] is not None:
        head += f" · CPU {_pct(a['cpu'])} ({NCPU} threads)"
    if gpu.get("total") is not None:
        head += f" · GPU {_pct(gpu['total'])}"
    L += [f"🖥️ PC — {a['procs']} processus, mesuré sur {seconds:g} s", head, "", "Qui consomme (RAM privée · CPU) :"]
    groups = [g for g in a["groups"] if g["ram"] >= 50 * MB or g["cpu"] >= 1]
    for g in groups[: None if show_all else 12]:
        L.append(f"  {g['label'][:44]:<44} {_size(g['ram']):>8} · {_pct(g['cpu']):>7}"
                 + (f" · {g['n']} proc." if g["n"] > 1 else ""))
    brain = next((g for g in a["groups"] if g["label"] == F_BRAIN), None)
    L.append("  Cerveau : " + (f"{brain['n']} tâche(s) de fond en cours ({_size(brain['ram'])}, priorité basse)" if brain
                               else "aucun processus résident (hooks ≈ 0,1 s par message, rien entre deux)"))
    if a["sessions"]:
        L += ["", f"Sessions Claude ouvertes ({len(a['sessions'])}, {_gb(sum(s['ram'] for s in a['sessions']))} · "
              f"validée {_gb(sum(s['commit'] for s in a['sessions']))}) :"]
        spin = {s["pid"] for s in spinning_sessions(a, pcfg)}
        for s in a["sessions"][: None if show_all else 10]:
            flag = " ⚠ tourne à vide" if s["pid"] in spin else (" (cette session)" if s["current"] else "")
            flag += " · archivée !" if s["archived"] else ""
            L.append(f"  {_size(s['ram']):>8} · CPU {_pct(s['cpu']):>6} · inactive {_dur(s['idle']):>6} · "
                     f"« {short(_name(s), 46)} »{flag}" + (f" {s['id']}" if s["id"] else ""))
        if not show_all and len(a["sessions"]) > 10:
            L.append(f"  … +{len(a['sessions']) - 10} (`brain pc --all`)")
    if a["servers"]:
        L += ["", "Serveurs MCP lancés par les sessions :"]
        for d in a["servers"][:6]:
            uses = "" if d["uses"] is None else f" · {d['uses']} appel(s) en {a['usage_days']} j"
            L.append(f"  {d['plugin'] or d['sig']} : {d['copies']} copie(s), {d['procs']} processus, {_size(d['ram'])} "
                     f"(validée {_size(d.get('commit', 0))}){uses}")
    acts = actions(a, pcfg)
    if acts:
        L += ["", "Ce qu'on peut libérer :"]
        for i, (_, _, text) in enumerate(acts, 1):
            L.append(f"  {i}. {text}")
        claude_gain = sum(g for g, _, t in acts if g)
        if claude_gain:
            L.append(f"  → RAM récupérable côté Claude : ≈ {_gb(claude_gain)}")
    if gpu.get("util") or gpu.get("vram"):
        fam = a["fam"]
        top = sorted(set(gpu.get("util", {})) | set(gpu.get("vram", {})),
                     key=lambda pid: (-gpu["util"].get(pid, 0), -gpu["vram"].get(pid, 0)))[:4]
        procs = a["_procs"]

        def who(pid):
            lab = fam.get(pid) or (procs[pid].name if pid in procs else f"pid {pid}")
            return procs[pid].name if lab in NO_INHERIT and pid in procs else lab

        used = f" · VRAM utilisée {_gb(gpu['vram_used'])}" if gpu.get("vram_used") else ""
        L += ["", f"GPU : {_pct(gpu.get('total') or 0)}{used} — " + " · ".join(
            f"{who(pid)} {_pct(gpu['util'].get(pid, 0))}, {_size(gpu['vram'].get(pid, 0))}" for pid in top)]
    last = read_json(STATE_FILE, {}) or {}
    if last.get("killed_total"):
        L.append(f"Orphelins fermés sur ta demande depuis l'installation : {last['killed_total']} "
                 f"({_size(last.get('killed_ram_total', 0))}).")
    return "\n".join(L)


def candidates_text(orphans) -> list:
    """Les lignes de la liste des suspects : PID, nom, âge, mémoire, raison. Pure."""
    rows = []
    for o in orphans:
        rows.append(f"  pid {o['pid']} · {o['name']} · {_dur(o.get('age', 0))} · {_size(o['ram'])} · "
                    f"{o.get('why') or o['kind']}\n      {o['label']}")
    return rows


def clean(cfg=None, oui=False) -> str:
    """Sans `oui` : liste seulement les candidats. Avec `oui` : les ferme (décision de l'utilisateur : jamais sans)."""
    cfg = cfg or load_config()
    a = measure(0.3, cfg, with_gpu=False, usage_days=0)
    if not oui:
        return clean_report(a["orphans"], None, None, None)
    before = memory()["avail"]
    done = kill_orphans(a["orphans"], a["_procs"]) if a["orphans"] else []
    time.sleep(1.5)
    after = memory()["avail"]
    _remember_kills(done)
    return clean_report(a["orphans"], done, before, after)


def clean_report(orphans, done, before, after) -> str:
    """Texte de `brain pc --clean` ; done=None : liste seule, rien n'a été fermé. Pure."""
    if not orphans:
        return "Aucun orphelin : rien à fermer."
    if done is None:
        return "\n".join([f"{len(orphans)} orphelin(s) candidat(s) à la fermeture (rien n'est fermé sans ton accord) :",
                          *candidates_text(orphans), "", "Pour les fermer : `brain pc --clean --oui`"])
    lines = [f"🧹 {len(done)} orphelin(s) fermé(s) sur {len(orphans)} trouvé(s) :"]
    lines += [f"  {o['kind']} · {o['killed']} processus · {_size(o['ram'])} · {o['label']}" for o in done]
    lines.append(f"RAM libre : {_gb(before)} → {_gb(after)} ({'+' if after >= before else ''}{_size(after - before)})")
    return "\n".join(lines)


def _remember_kills(done) -> None:
    if not done:
        return
    st = read_json(STATE_FILE, {}) or {}
    st["killed_total"] = st.get("killed_total", 0) + len(done)
    st["killed_ram_total"] = st.get("killed_ram_total", 0) + sum(o["ram"] for o in done)
    write_json(STATE_FILE, st)
