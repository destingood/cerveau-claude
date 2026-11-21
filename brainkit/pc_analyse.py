"""PC, analyse : sessions de l'app Claude, arbre des processus, familles, serveurs MCP orphelins, et la mesure complète
(`brain pc`).

Découpé de pc.py (étape 8 du plan) sans rien changer. La fermeture passe par pc.terminate (remplaçable dans pc :
test_pc ne ferme jamais rien)."""
import glob
import os
import re
import time
from pathlib import Path

from . import pc as _pc  # pc.terminate, remplaçable dans pc (test_pc : aucune vraie fermeture)
from .common import CLAUDE_HOME, load_config, log, read_json, short, write_json
from .pc import (CMD_IMAGES, EPOCH_FT, F_APP, F_BRAIN, F_ORPH, F_SESS, F_TERM, FAMILY_OF, MB, META_CACHE, NCPU,
                 NO_INHERIT, NOT_SERVERS, ORPHAN_IMAGES, RX_SESSION, SHELLS, STATE_FILE, TERM_MARK, _gpu_open, _gpu_read,
                 cmdline, gpu_by_pid, memory, snapshot, vm_disk_in_use)
from .privacy import mask


# ------------------------------------------------------------------------------------------ sessions de l'app Claude
def app_sessions() -> dict:
    """cliSessionId → {id local_…, titre, archivée, création, dernière activité} (métadonnées de l'app Claude).
    Cache par taille+date de fichier dans state/pc_meta.json : les fichiers inchangés ne sont pas relus."""
    roots = [Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code-sessions"]
    roots += [Path(p) / "LocalCache" / "Roaming" / "Claude" / "claude-code-sessions"
              for p in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*"))]
    files = {}
    for root in roots:
        for f in glob.glob(str(root / "*" / "*" / "local_*.json")):
            try:
                stt = os.stat(f)
            except OSError:
                continue
            base = os.path.basename(f)
            prev = files.get(base)
            if prev is None or stt.st_mtime_ns > prev[1].st_mtime_ns:  # doublon APPDATA/MSIX : le plus récent gagne
                files[base] = (f, stt)
    cache = read_json(META_CACHE, {}) or {}
    new, out = {}, {}
    for f, stt in files.values():
        key = f"{stt.st_size}:{stt.st_mtime_ns}"
        row = cache.get(key)
        if not isinstance(row, dict):
            m = read_json(f, None)
            if not isinstance(m, dict) or not m.get("cliSessionId"):
                continue
            row = {"cli": str(m["cliSessionId"]).lower(), "id": m.get("sessionId"), "title": m.get("title") or "",
                   "archived": bool(m.get("isArchived")), "created": (m.get("createdAt") or 0) / 1000,
                   "activity": max(m.get("lastActivityAt") or 0, m.get("lastFocusedAt") or 0) / 1000}
        new[key] = row
        out[row["cli"]] = {"id": row["id"], "title": row["title"], "archived": row["archived"],
                           "created": row["created"], "activity": row["activity"]}
    if new != cache:
        write_json(META_CACHE, new)
    return out


def _transcripts() -> dict:
    out = {}
    try:
        for d in os.scandir(CLAUDE_HOME / "projects"):
            if d.is_dir():
                for f in os.scandir(d.path):
                    if f.name.endswith(".jsonl"):
                        out[f.name[:-6].lower()] = f.stat().st_mtime
    except OSError:
        pass
    return out


RX_TOOL_USE = re.compile(rb'"type":"tool_use","id":"[^"]{1,100}","name":"(mcp__[^"]{1,200})"')


def _count_tool_uses(data, counts) -> None:
    for m in RX_TOOL_USE.finditer(data):
        name = m.group(1).decode("utf-8", "replace")
        server = name[5:name.rfind("__")] if name.rfind("__") > 5 else name[5:]
        counts[server] = counts.get(server, 0) + 1


def mcp_usage(days=7) -> dict:
    """Appels d'outils MCP dans les transcripts des `days` derniers jours : serveur (mcp__<serveur>__) → nombre.
    Lecture par blocs de 1 Mo (pic mémoire ≈ la plus grosse ligne, pas le plus gros fichier)."""
    cut, counts = time.time() - days * 86400, {}
    for dirpath, _, files in os.walk(CLAUDE_HOME / "projects"):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                if not fn.endswith(".jsonl") or os.path.getmtime(p) < cut:
                    continue
                with open(p, "rb") as fh:
                    tail = b""
                    for block in iter(lambda fh=fh: fh.read(1 << 20), b""):
                        data = tail + block
                        i = data.rfind(b"\n") + 1  # on ne coupe jamais au milieu d'une ligne (un tool_use y tient)
                        tail = data[i:]
                        _count_tool_uses(data[:i], counts)
                    _count_tool_uses(tail, counts)
            except OSError:
                continue
    return counts


# ------------------------------------------------------------------------------------------ arbre, familles, orphelins
def ft_to_unix(ft) -> float:
    return (ft - EPOCH_FT) / 1e7


def _parent(p, procs):
    par = procs.get(p.ppid)
    return par if par is not None and par.pid != p.pid and par.create <= p.create else None  # sinon PID réutilisé


def children_map(procs) -> dict:
    kids = {}
    for p in procs.values():
        par = _parent(p, procs)
        if par is not None:
            kids.setdefault(par.pid, []).append(p.pid)
    return kids


def subtree(pid, kids, stop=()) -> list:
    out, stack = [], [pid]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(c for c in kids.get(x, ()) if c not in stop)
    return out


RX_NPX = re.compile(r"\b(?:npx|npx-cli\.js|uvx|bunx|dlx)\"?\s+(?:(?:-y|--yes|--quiet|-q)\s+|"
                    r"(?:--python|--from|--with|--package|-p)[= ]\S+\s+)*\"?(@?[\w.-]+(?:/[\w.-]+)?)", re.I)
RX_NODE_MODULES = re.compile(r"node_modules[\\/]+(?:\.bin[\\/]+\.\.[\\/]+)?(@[\w.-]+[\\/]+[\w.-]+|[\w.-]+)", re.I)
RX_SCOPED = re.compile(r"(@[\w.-]+[\\/][\w.-]+)")
RX_SCRIPT = re.compile(r"([\w.-]+\.(?:pyw?|m?js|cjs|ts))\b", re.I)


def server_sig(cmd):
    """Paquet du serveur MCP lancé par une ligne de commande (npx/uvx, node_modules, @scope/nom), sans version."""
    if not cmd:
        return None
    m, name = RX_NPX.search(cmd), None
    if m and m.group(1).lower() not in ("npm", "-y"):
        name = m.group(1)
    else:
        mods = [x for x in RX_NODE_MODULES.findall(cmd) if x.lower() not in ("npm", ".bin")]
        if mods:
            name = mods[-1]
        else:
            m = RX_SCOPED.search(cmd)
            name = m.group(1) if m else None
    if not name:
        return None
    return re.sub(r"(?<=.)@[\w.^~<>=-]*$", "", name.replace("\\", "/")).lower()


# Serveur MCP reconnu à sa ligne de commande (jamais le simple « mcp » d'un nom de dossier : `python C:\dev\mcp-tools\x.py`
# est un script de l'utilisateur). Paquets officiels, `mcp-server…`, `mcp_server`, FastMCP, paquets `…-mcp` / `@scope/mcp`.
RX_MCP = re.compile(
    r"@modelcontextprotocol[\\/]|mcp[-_]server|fastmcp|(?<![\\/])[\w.@-]-mcp(?=$|[\s\"'@=:])|@[\w.-]+/mcp(?=$|[\s\"'@=:])"
    r"|\bmcp-(?:remote|proxy)\b|node_modules[\\/]+(?:@[\w.-]+[\\/]+)?[\w.-]*mcp[\w.-]*|@[\w.-]+[\\/]mcp(?=[\\/])", re.I)
RX_LAUNCHER_MCP = re.compile(r"\b(?:npx|uvx|bunx|dlx)\"?\s+(?:-\S+\s+)*\"?[\w@.-]*mcp[\w@.-]*(?=$|[\s\"'])", re.I)


def mcp_reason(cmd, known=()) -> str:
    """Pourquoi cette ligne de commande est celle d'un serveur MCP (texte court), ou '' si rien ne le prouve."""
    if not cmd:
        return ""
    sig = server_sig(cmd)
    if sig and sig in known:
        return f"serveur MCP « {sig} » connu"
    m = RX_MCP.search(cmd) or RX_LAUNCHER_MCP.search(cmd)
    return f"ligne de commande MCP (« {short(m.group(0).strip(), 40)} »)" if m else ""


def usage_token(sig) -> str:
    base = sig.split("/")[-1]
    return re.sub(r"^(?:mcp-server-|server-|mcp-)|(?:-mcp-server|-mcp|-server)$", "", base)


def is_session(p, c) -> bool:
    """claude.exe qui est une session Code (ni le process principal de l'app, ni un sous-process Electron --type=)."""
    if p.name.lower() != "claude.exe" or not c or "--type=" in c:
        return False
    lc = c.lower()
    return "stream-json" in lc or "\\claude-code\\" in lc or "\\.local\\bin\\" in lc or bool(RX_SESSION.search(c))


def _session_ids(procs, cmds, roots, meta) -> dict:
    """pid de session → uuid local_… : d'abord via --resume/--session-id, puis en appariant les sessions fraîches
    (sans uuid dans la commande) au createdAt de métadonnées le plus proche (lancement 0–30 s après l'écriture)."""
    out = {}
    for pid in roots:
        m = RX_SESSION.search(cmds.get(pid) or "")
        if m:
            out[pid] = m.group(1).lower()
    used, pairs = set(out.values()), []
    for pid in roots:
        if pid in out:
            continue
        t = ft_to_unix(procs[pid].create)
        for uid, md in meta.items():
            if uid not in used and md.get("created") and -3 <= t - md["created"] <= 30:
                pairs.append((abs(t - md["created"]), pid, uid))
    for _, pid, uid in sorted(pairs):
        if pid not in out and uid not in used:
            out[pid] = uid
            used.add(uid)
    return out


def _lineage(procs) -> set:
    """Ce processus et tous ses ancêtres : jamais fermés (on ne scie pas la branche sur laquelle on est assis)."""
    out, p = set(), procs.get(os.getpid())
    while p is not None and p.pid not in out and len(out) < 64:
        out.add(p.pid)
        p = _parent(p, procs)
    return out


def plugin_servers() -> dict:
    """Signature de serveur MCP → nom du plugin qui le fournit (configs des plugins installés)."""
    bases = [Path(os.environ.get("APPDATA", "")) / "Claude" / "rpm"]
    bases += [Path(p) / "LocalCache" / "Roaming" / "Claude" / "rpm"
              for p in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*"))]
    dirs = {}
    for base in bases:
        for d in glob.glob(str(base / "*" / "*" / "plugin_*")):
            dirs.setdefault(os.path.basename(d), d)
    out = {}
    for d in dirs.values():
        pj = read_json(os.path.join(d, ".claude-plugin", "plugin.json"), None)
        if not isinstance(pj, dict):
            continue
        name = pj.get("name") or os.path.basename(d)
        blocks, ms = [], pj.get("mcpServers")
        if isinstance(ms, str):
            ms = read_json(os.path.join(d, ms), None)
        if isinstance(ms, dict):
            blocks.append(ms)
        mj = read_json(os.path.join(d, ".mcp.json"), None)
        if isinstance(mj, dict):
            blocks.append(mj)
        for block in blocks:
            servers = block.get("mcpServers") if isinstance(block.get("mcpServers"), dict) else block
            if not isinstance(servers, dict):
                continue
            for srv in servers.values():
                if not isinstance(srv, dict) or not isinstance(srv.get("command"), str):
                    continue
                sig = server_sig(" ".join([srv["command"], *(str(a) for a in srv.get("args") or [])]))
                if sig and sig not in NOT_SERVERS:
                    out.setdefault(sig, name)
    return out


def find_orphans(procs, cmds, kids, now, pcfg, sessions=(), known=()) -> list:
    """Processus Claude qui ne servent plus à rien (parent mort, assez anciens). Chaque suspect porte son âge et la raison
    (`why`). « serveur sans session » (auto=True) = serveur MCP identifié (signature connue d'une session vivante ou
    d'un plugin, ou ligne de commande MCP précise : voir mcp_reason) : listé par la veille. Rien n'est fermé sans
    `brain pc --clean --oui`."""
    min_age = pcfg.get("orphan_min_minutes", 10) * 60
    pats = [x.lower() for x in pcfg.get("orphan_patterns") or [] if x.strip().lower() != "mcp"]  # « mcp » nu : trop large
    known = {x for x in known if x and x not in NOT_SERVERS}
    mine = _lineage(procs)
    roots, why = [], {}
    for p in procs.values():
        pid = p.pid
        if not pid or pid in mine or p.name.lower() not in ORPHAN_IMAGES:
            continue
        if _parent(p, procs) is not None or now - ft_to_unix(p.create) < min_age:
            continue
        c = cmds.get(pid) or ""
        lc = c.lower()
        if not lc or "brain.py" in lc:  # illisible → on ne touche pas ; tâches du cerveau → finissent seules
            continue
        if p.name.lower() == "claude.exe":
            if "stream-json" in lc and "--type=" not in lc:
                roots.append((pid, "session sans app"))
                why[pid] = "session Claude dont l'application est fermée"
        elif mcp_reason(c, known):
            roots.append((pid, "serveur sans session"))
            why[pid] = mcp_reason(c, known) + ", parent disparu"
        elif any(x in lc for x in pats):
            roots.append((pid, "outil Claude sans parent"))
            why[pid] = "outil Claude dont le parent a disparu"
    for s in sessions:
        if s.get("archived") and s.get("app") and not s.get("current") and s["pid"] not in mine \
                and s.get("idle", 0) >= min_age:
            roots.append((s["pid"], "session archivée encore en vie"))
            why[s["pid"]] = "session archivée dans l'application, encore ouverte"
    out, taken = [], set()
    for pid, kind in roots:
        if pid in taken or pid not in procs:
            continue
        tree = [x for x in subtree(pid, kids) if x not in taken]
        taken.update(tree)
        name = procs[pid].name
        out.append({"pid": pid, "name": name, "kind": kind, "auto": kind == "serveur sans session", "tree": tree,
                    "age": max(0.0, now - ft_to_unix(procs[pid].create)), "since": procs[pid].create, "why": why.get(pid, kind),
                    "ram": sum(procs[x].ws for x in tree), "label": short(mask(cmds.get(pid) or name)[0], 90)})
    return out


def kill_orphans(orphans, procs) -> list:
    mine = _lineage(procs)
    done = []
    for o in orphans:
        if mine & set(o["tree"]):  # garde-fou : jamais un processus dont nous dépendons
            continue
        n = sum(1 for pid in o["tree"] if pid in procs and _pc.terminate(pid, procs[pid].create))
        if n:
            done.append({**o, "killed": n})
            log(f"pc : orphelin fermé ({o['kind']}) pid {o['pid']} · {n} processus · {o['ram'] // MB} Mo · {o['label']}")
    return done


def _own_label(p, cmds) -> str:
    c = cmds.get(p.pid) or ""
    if "brain.py" in c:
        return F_BRAIN
    if p.name.lower() in ("python.exe", "pythonw.exe", "node.exe"):
        m = RX_SCRIPT.search(c.split(None, 1)[1] if " " in c.strip() else "")
        if m:
            return f"{p.name} ({m.group(1)})"
    return p.name


def _session_rows(procs, cmds, kids, now, roots, cur, meta=None):
    meta = app_sessions() if meta is None else meta
    tx = _transcripts()
    ids = _session_ids(procs, cmds, roots, meta)
    rows = []
    for pid in roots:
        p = procs[pid]
        uid = ids.get(pid)
        md = (meta.get(uid) or {}) if uid else {}
        tree = subtree(pid, kids, stop=roots - {pid})
        if uid:
            last = max(md.get("activity") or 0, tx.get(uid, 0), md.get("created") or 0, ft_to_unix(p.create))
            idle = max(0.0, now - last)
        else:
            idle = 0.0  # session trop fraîche pour être appariée : active, jamais proposée à l'archivage
        rows.append({"pid": pid, "uuid": uid, "id": md.get("id"), "title": md.get("title") or "", "current": pid == cur,
                     "archived": bool(md.get("archived")), "app": bool(md), "idle": idle, "tree": tree,
                     "ram": sum(procs[x].ws for x in tree), "commit": sum(procs[x].private for x in tree),
                     "cpu": sum(procs[x].pct for x in tree), "cpu_self": p.pct, "create": p.create})
    rows.sort(key=lambda s: -s["ram"])
    return rows


def _current_session(procs, roots):
    pid = os.getpid()
    for _ in range(40):
        if pid in roots:
            return pid
        p = procs.get(pid)
        par = _parent(p, procs) if p else None
        if par is None:
            return None
        pid = par.pid
    return None


def analyze(procs, cmds, mem, gpu, now, pcfg, cpu_total, usage=None, known=None, plugins=None, meta=None) -> dict:
    """Tout le diagnostic à partir des mesures. Quasi pure : métadonnées (meta), configs plugins (plugins) et
    signatures connues (known) sont injectables → testable sans toucher au disque."""
    kids = children_map(procs)
    roots = {pid for pid, p in procs.items() if is_session(p, cmds.get(pid))}
    cur = _current_session(procs, roots)
    sessions = _session_rows(procs, cmds, kids, now, roots, cur, meta)
    # Serveurs MCP lancés par chaque session (avant les orphelins : leurs signatures protègent ceux encore attachés)
    servers = {}
    for s in sessions:
        seen = set()
        for child in kids.get(s["pid"], ()):
            if child in roots or procs[child].name.lower() in SHELLS:  # un shell enfant = outil Bash, pas un serveur
                continue
            sub = subtree(child, kids, stop=roots)
            sig = None
            for x in sub:
                sig = server_sig(cmds.get(x))
                if sig:
                    break
            if not sig:
                continue
            d = servers.setdefault(sig, {"sig": sig, "copies": 0, "ram": 0, "commit": 0, "ram_active": 0, "procs": 0})
            ram = sum(procs[x].ws for x in sub)
            d["ram"] += ram
            d["commit"] += sum(procs[x].private for x in sub)
            d["procs"] += len(sub)
            if s["idle"] < pcfg.get("idle_hours", 3) * 3600 or s["current"]:
                d["ram_active"] += ram
            if sig not in seen:
                seen.add(sig)
                d["copies"] += 1
    plugins = plugin_servers() if plugins is None else plugins
    orphans = find_orphans(procs, cmds, kids, now, pcfg, sessions, set(servers) | set(known or ()) | set(plugins))
    fam = {}
    for o in orphans:
        for x in o["tree"]:
            fam[x] = F_ORPH
    for s in sessions:
        for x in s["tree"]:
            fam.setdefault(x, F_SESS)
    terms = []
    for pid in list(procs):
        if pid not in fam and TERM_MARK in (cmds.get(pid) or ""):  # shells du panneau Terminal de l'app
            sub = subtree(pid, kids, stop=set(fam))
            for x in sub:
                fam.setdefault(x, F_TERM)
            terms.extend(sub)
    for p in procs.values():
        if p.name.lower() == "claude.exe" and p.pid not in fam:
            for x in subtree(p.pid, kids, stop=set(fam)):
                fam.setdefault(x, F_APP)
    vm = None
    for p in procs.values():
        if p.pid in fam:
            continue
        label = FAMILY_OF.get(p.name.lower())
        if label is None:
            q, label = p, None
            for _ in range(30):  # hérite de l'ancêtre connu le plus proche (pas de Windows : tout en descend)
                q = _parent(q, procs)
                if q is None:
                    break
                up = fam.get(q.pid) or FAMILY_OF.get(q.name.lower())
                if up and up not in NO_INHERIT:
                    label = up
                    break
            label = label or _own_label(p, cmds)
        if label == "Machine virtuelle (vmmem)" and vm is None:
            vm = vm_disk_in_use()
        fam[p.pid] = label
    if vm:
        fam = {pid: ("Machine virtuelle de l'app Claude (vmmem)" if v == "Machine virtuelle (vmmem)" else v)
               for pid, v in fam.items()}
    gutil, gvram = (gpu or {}).get("util", {}), (gpu or {}).get("vram", {})
    groups = {}
    for pid, label in fam.items():
        p = procs[pid]
        g = groups.setdefault(label, {"label": label, "n": 0, "ram": 0, "cpu": 0.0, "gpu": 0.0, "vram": 0})
        g["n"] += 1
        g["ram"] += p.ws
        g["cpu"] += p.pct
        g["gpu"] = max(g["gpu"], gutil.get(pid, 0.0))
        g["vram"] += gvram.get(pid, 0)
    for d in servers.values():
        plug = plugins.get(d["sig"])
        if plug:
            keys = [k for k in (usage or {}) if k.startswith(f"plugin_{plug}_")]
        else:
            tok = usage_token(d["sig"])
            keys = [k for k in (usage or {}) if len(tok) >= 3 and tok in k.lower()]
        d["uses"] = sum(usage[k] for k in keys) if usage is not None else None
        d["plugin"] = plug
    return {"now": now, "mem": mem, "cpu": cpu_total, "gpu": gpu, "procs": len(procs), "sessions": sessions,
            "orphans": orphans, "groups": sorted(groups.values(), key=lambda g: -g["ram"]),
            "servers": sorted(servers.values(), key=lambda d: -d["ram"]), "fam": fam, "terminals": len(terms)}


def measure(seconds=2.0, cfg=None, with_gpu=True, usage_days=7) -> dict:
    cfg = cfg or load_config()
    g = _gpu_open() if with_gpu else None
    t1, p1 = time.perf_counter(), snapshot()
    time.sleep(max(0.2, seconds))
    t2, procs = time.perf_counter(), snapshot()
    graw = _gpu_read(g) if g else {}
    dt = t2 - t1
    for pid, p in procs.items():
        q = p1.get(pid)
        if pid and q is not None and q.create == p.create:
            p.pct = max(0.0, (p.cpu - q.cpu) / 1e7 / dt / NCPU * 100)
    idle = procs.get(0)
    cpu_total = max(0.0, 100 - (idle.cpu - p1[0].cpu) / 1e7 / dt / NCPU * 100) if idle and 0 in p1 else None
    cmds = {pid: cmdline(pid) for pid, p in procs.items() if p.name.lower() in CMD_IMAGES}
    usage = mcp_usage(usage_days) if usage_days else None
    known = set((read_json(STATE_FILE, {}) or {}).get("sigs") or ())
    a = analyze(procs, cmds, memory(), gpu_by_pid(graw) if graw else None, time.time(), cfg["pc"], cpu_total, usage,
                known=known)
    a["seconds"], a["usage_days"], a["_procs"], a["_cmds"] = seconds, usage_days, procs, cmds
    return a
