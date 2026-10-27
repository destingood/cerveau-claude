"""Réflexes de skills : le cerveau connaît les skills personnelles (~/.claude/skills/*/SKILL.md) et celles des plugins
actifs (installés par Claude Code : « plugin:skill »), et souffle la bonne au bon moment.

Pourquoi : Claude Code tronque la liste des skills quand il y en a beaucoup (la plupart n'y figurent plus que par leur
nom) → une skill perso risque de ne jamais se déclencher seule. Ici : index des déclencheurs (phrases « … » de la
description, nom, mots distinctifs), reconnaissance tolérante aux fautes et à l'écriture phonétique, partie « Ne pas
utiliser » respectée, au plus une ligne « 🧩 » par skill et par session. Une skill de plugin (souvent décrite en anglais,
SKILL.md réécrit à chaque mise à jour) reçoit ses déclencheurs dans la config : `brain skill trig <nom> "…"`.
Aussi : une méthode ou un prompt collé (long texte structuré) → en faire une skill, ou mettre à jour celle qui lui
ressemble. Suivi soufflée / réellement chargée (outil Skill) dans state/skills.json → `brain skill ls`."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .common import (CLAUDE_HOME, STATE_DIR, FileLock, fold, load_config, now_iso, read_json, short, tokenize,
                     write_json)
from .lexicon import phon, root, within_one

SKILLS_DIR = CLAUDE_HOME / "skills"
PLUGINS_FILE = CLAUDE_HOME / "plugins" / "installed_plugins.json"
OWN_PLUGIN = "cerveau"  # ses skills (/cerveau:brain…) servent le cerveau lui-même : jamais soufflées
CACHE_FILE = STATE_DIR / "skills_index.json"
STATS_FILE = STATE_DIR / "skills.json"
CACHE_V = 3

FM_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
NEG_RE = re.compile(r"\b(?:ne (?:pas |jamais )(?:l')?utiliser|ne l'utilise[rz]? pas|do not use|don't use|not for|never use)\b",
                    re.I)
QUOTE_RE = re.compile(r"«\s*([^»]{2,140}?)\s*»|“([^”]{2,140})”|\"([^\"\n]{2,140})\"")
SLASH_RE = re.compile(r"(?<![\w/.])/([a-z0-9][a-z0-9:_-]{1,40})")
FILE_RE = re.compile(r"\b([A-Za-z][\w-]*)\.(md|txt|json|toml|ya?ml|py|js|ts|html|csv)\b")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(([^)\s#]+)\)")
CAP_RE = re.compile(r"(?<![.!?:]\s)(?<!^)\b([A-Z][A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*|[A-Z]{3,})\b")
# Mots de description qui ne disent rien du sujet (« À utiliser quand Lucas demande… »).
DESC_STOP = {fold(w) for w in """utiliser utilise utilisez utilisation quand lorsque demande demandes demander veut veulent
lucas personne skill skills tape tapes taper toute toutes question questions chaque partir pour ici exemple etc
use used when user asks want wants any every""".split()} | {"luca"}
GENERIC_NAME = {"projet", "project", "expert", "contexte", "context", "agent", "assistant", "helper", "outil", "tool",
                "general", "generateur", "generator", "manager", "gestion", "creer", "create", "faire"}

PASTE_TAG = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content>", re.S)
MARKERS = re.compile(r"\b(you are|tu es (?:un|une|le|la)|act as|agis comme|roles?|tasks?|taches?|contexte?|objecti(?:ve|f)s?|"
                     r"goals?|steps?|etapes?|instructions?|output|sortie|formats?|deliverables?|livrables?|rules?|regles?|"
                     r"guidelines?|consignes?|constraints?|contraintes?|process(?:us)?|prompts?|persona|examples?|"
                     r"exemples?|workflow|template|modele)\b")
STRUCT_RE = re.compile(r"^\s*(?:#{1,4}\s|[-*•]\s|\d+[.)]\s|\*\*|[A-Z][A-Z0-9 &'/()-]{3,}:?\s*$|[A-Z][A-Za-z ]{2,30}:\s)")
CODE_RE = re.compile(r"^\s*(?:def |class |import |from \S+ import|function |const |let |var |public |private |#include|"
                     r"[{}]\s*$|\w+\s*=\s*[\w\[{(\"']|.*[;{]\s*$|at \S+\(|File \")")
FP_STOP = {fold(w) for w in """the you your this that these those each when then step steps section sections role task
context output format example examples rule rules note notes important use using for not and but with from into always
never only all any make create write give provide include ensure follow based now here there what how why who which
les des une pour avec dans sur par chaque etape section role tache contexte sortie format exemple regle note toujours
jamais ensuite puis voici""".split()}


# ------------------------------------------------------------------------------------------ lecture des SKILL.md
def _unquote(val: str) -> str:
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        q, val = val[0], val[1:-1]
        val = val.replace("''", "'") if q == "'" else val.replace('\\"', '"').replace("\\\\", "\\")
    return val


def frontmatter(text) -> tuple:
    """En-tête YAML minimal (clé: valeur, valeurs sur plusieurs lignes, > et |) → (dict, corps)."""
    m = FM_RE.match(text or "")
    if not m:
        return {}, text or ""
    meta, key = {}, None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if kv and not line[0].isspace():
            key, val = kv.group(1).lower(), kv.group(2).strip()
            meta[key] = "" if val in (">", "|", ">-", "|-", ">+", "|+") else _unquote(val)
        elif key:
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, text[m.end():]


def _norm(text) -> str:
    """« AGENT.md » → « agentmd » : un nom de fichier reste un seul mot des deux côtés (déclencheur et message)."""
    return FILE_RE.sub(lambda m: (m.group(1) + m.group(2)).lower(), str(text or ""))


def split_desc(desc) -> tuple:
    """Description → (partie « à utiliser », partie « ne pas utiliser »)."""
    m = NEG_RE.search(desc or "")
    return (desc, "") if not m else (desc[:m.start()], desc[m.start():])


def quoted(text) -> list:
    out = []
    for m in QUOTE_RE.finditer(text or ""):
        p = next(g for g in m.groups() if g).strip()
        if p and p not in out:
            out.append(p)
    return out


def _tok3(t) -> list:
    return [t, root(t), phon(t)]


def phrase_groups(phrase) -> list:
    """« je passe sur ChatGPT / Gemini / une autre IA » → [[passe], [chatgpt | gemini | ia]] : il faut un mot de chaque
    groupe ; « / » sépare des variantes (le dernier mot avant, le premier mot après)."""
    parts = [tokenize(_norm(p)) for p in re.split(r"\s*/\s*", phrase)]
    parts = [p for p in parts if p]
    if not parts:
        return []
    if len(parts) == 1:
        return [[_tok3(t)] for t in parts[0]]
    groups = [[_tok3(t)] for t in parts[0][:-1]]
    alt = [parts[0][-1]] + [t for p in parts[1:-1] for t in p] + [parts[-1][0]]
    groups.append([_tok3(t) for t in dict.fromkeys(alt)])
    groups += [[_tok3(t)] for t in parts[-1][1:]]
    return groups


def _entities(text) -> set:
    """Noms propres et sigles en milieu de phrase (Pinterest, Shopify, SEO…), sans le mot qui ouvre une phrase."""
    out = set()
    for m in CAP_RE.finditer(text or ""):
        out.update(tokenize(_norm(m.group(1))))
    return out


def parse(path, plugin="") -> dict | None:
    """SKILL.md → fiche de la skill ; `plugin` : nom du plugin qui la fournit (la skill s'appelle alors « plugin:nom »,
    comme dans l'outil Skill)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta, body = frontmatter(text)
    base = (meta.get("name") or path.parent.name).strip()
    name = f"{plugin}:{base}" if plugin else base
    desc = " ".join((meta.get("description") or "").split())
    pos, neg = split_desc(desc)
    triggers = quoted(pos)
    name_toks = tokenize(base.replace("-", " ").replace("_", " ").replace(":", " "))
    trig_toks = {t for p in triggers for t in tokenize(_norm(p))}
    ents = _entities(pos)
    kw = {}
    for t in tokenize(_norm(pos)):
        kw[t] = max(kw.get(t, 0), 1)
    for t in ents:
        kw[t] = max(kw.get(t, 0), 2)
    for t in trig_toks:
        kw[t] = max(kw.get(t, 0), 2)
    for t in name_toks:
        kw[t] = 3
    kw = {t: w for t, w in kw.items() if t not in DESC_STOP and not t.isdigit()
          and (len(t) >= 3 or t in name_toks or t in trig_toks)}
    pos_set = set(kw) | set(tokenize(_norm(pos)))
    neg_only = sorted({t for t in tokenize(_norm(neg)) if len(t) >= 4 and t not in pos_set and t not in DESC_STOP})
    return {"name": name, "plugin": plugin, "path": str(path), "description": desc,
            "meta": {k: v for k, v in meta.items() if k not in ("name", "description")},
            "triggers": [{"text": p, "groups": g} for p in triggers for g in [phrase_groups(p)] if usable(g)],
            "vague": [p for p in triggers if not usable(phrase_groups(p))],
            "neg_triggers": [{"text": p, "groups": g} for p in quoted(neg) for g in [phrase_groups(p)] if usable(g)],
            "slash": sorted(set(SLASH_RE.findall(desc))),
            "kw": [[*_tok3(t), w, "name" if t in name_toks else "trigger" if t in trig_toks else
                    "entity" if t in ents else "desc"] for t, w in sorted(kw.items())],
            "neg_kw": [_tok3(t) for t in neg_only], "lines": body.count("\n") + 1,
            "links": sorted(set(LINK_RE.findall(body)))}


def _enabled(cwd=None) -> dict:
    """enabledPlugins de Claude Code : réglages de l'utilisateur, puis ceux du projet (le projet l'emporte)."""
    out = {}
    paths = [CLAUDE_HOME / "settings.json"]
    if cwd:
        paths += [Path(cwd) / ".claude" / "settings.json", Path(cwd) / ".claude" / "settings.local.json"]
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig") or "{}")
        except (OSError, ValueError):
            continue
        ep = data.get("enabledPlugins") if isinstance(data, dict) else None
        if isinstance(ep, dict):
            out.update(ep)
    return out


def _inside(cwd, project) -> bool:
    try:
        here, proj = Path(cwd).resolve(), Path(project).resolve()
    except (OSError, TypeError, ValueError):
        return False
    return here == proj or proj in here.parents


def plugin_roots(cwd=None, want=True) -> list:
    """[(plugin, dossier skills/)] des plugins installés par Claude Code (plugins/installed_plugins.json) et actifs ici :
    pas à false dans enabledPlugins, portée « user » ou projet qui contient `cwd`. Jamais le cerveau lui-même ni les
    plugins synchronisés depuis claude.ai (absents de ce registre). `want` : True = tous, liste = seulement ceux-là."""
    if not want or want == "off":
        return []
    data = read_json(PLUGINS_FILE, {}) or {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return []
    enabled, out = _enabled(cwd), []
    for key, entries in sorted(plugins.items()):
        name = str(key).partition("@")[0]
        if name == OWN_PLUGIN or enabled.get(key) is False or (isinstance(want, list) and name not in want):
            continue
        entries = [entries] if isinstance(entries, dict) else entries if isinstance(entries, list) else []
        for e in entries:
            if not isinstance(e, dict) or not e.get("installPath"):
                continue
            if e.get("scope", "user") != "user" and not (cwd and e.get("projectPath") and _inside(cwd, e["projectPath"])):
                continue
            out.append((name, Path(e["installPath"]) / "skills"))
            break
    return out


def _files(cwd=None, plugins=True) -> list:
    roots = [("", SKILLS_DIR)]
    if cwd:
        local = Path(cwd) / ".claude" / "skills"
        try:
            if local.is_dir() and local.resolve() != SKILLS_DIR.resolve():
                roots.append(("", local))
        except OSError:
            pass
    roots += plugin_roots(cwd, plugins)
    out = []
    for plugin, r in roots:
        try:
            entries = sorted(r.iterdir())
        except OSError:
            continue
        for d in entries:
            f = d / "SKILL.md"
            try:
                s = f.stat()
            except OSError:
                continue
            out.append([str(f), s.st_mtime_ns, s.st_size, plugin])
    return out


def with_triggers(skills, extra) -> list:
    """Greffe les déclencheurs ajoutés dans la config (skills.triggers : {nom: [phrases]}) : le seul moyen d'en donner à
    une skill de plugin, dont le SKILL.md est réécrit à chaque mise à jour (ou d'en ajouter sans toucher une skill)."""
    if not isinstance(extra, dict) or not extra:
        return skills
    out = []
    for s in skills:
        add = [p.strip() for p in dict.fromkeys(extra.get(s["name"]) or []) if isinstance(p, str) and p.strip()]
        if add:
            have = {fold(p["text"]) for p in s["triggers"]}
            s = {**s, "triggers": s["triggers"] + [{"text": p, "groups": g, "added": True} for p in add
                                                   for g in [phrase_groups(p)] if usable(g) and fold(p) not in have],
                 "vague": s.get("vague", []) + [p for p in add if not usable(phrase_groups(p))]}
        out.append(s)
    return out


def index(cwd=None, kc=None) -> list:
    """Skills perso et skills des plugins actifs, analysées ; en cache tant qu'aucun SKILL.md n'a bougé (relu en ~1 ms
    sinon). `kc` : config « skills » (relue si absente) — `plugins` (True, liste de noms ou False) et `triggers`."""
    kc = (load_config().get("skills") or {}) if kc is None else kc
    sig = _files(cwd, kc.get("plugins", True))
    cache = read_json(CACHE_FILE, {}) or {}
    if cache.get("v") == CACHE_V and cache.get("sig") == sig:
        return with_triggers(cache.get("skills", []), kc.get("triggers"))
    skills = [s for s in (parse(f, plugin) for f, _, _, plugin in sig) if s]
    sources = {}
    for s in skills:
        sources.setdefault(s["plugin"], []).append(s)
    for group in sources.values():  # rareté comptée par source (skills perso, chaque plugin) : un plugin ajouté ne
        n = len(group)              # change pas le poids des mots des skills perso
        df = Counter(k[0] for s in group for k in s["kw"])
        for s in group:  # poids = importance du mot × rareté parmi les skills (un mot présent partout ne départage rien)
            for k in s["kw"]:
                k[3] = round(k[3] * math.log((n + 1) / (df[k[0]] + 0.5)), 3) if n > 1 else float(k[3])
    try:
        write_json(CACHE_FILE, {"v": CACHE_V, "sig": sig, "skills": skills})
    except OSError:
        pass
    return with_triggers(skills, kc.get("triggers"))


# ------------------------------------------------------------------------------------------ reconnaissance
class Query:
    """Message découpé une fois : mots, racines, clés phonétiques et positions. Tolérance réglée sur de vrais messages :
    racine commune d'au moins 5 lettres, même clé phonétique d'au moins 4, une faute seulement sur les mots de 6+
    (« paste » ≠ « passe », « passer » ≠ « passation »)."""

    def __init__(self, text):
        self.text = fold(_norm(text))
        self.toks = tokenize(_norm(text))
        self.set = set(self.toks)
        self.roots = {root(t) for t in self.toks if len(root(t)) >= 5}
        self.phons = {phon(t) for t in self.toks if len(t) >= 4 and len(phon(t)) >= 4}

    @staticmethod
    def same(t, k) -> bool:
        tok, kr, kp = k
        if t == tok:
            return True
        if len(t) < 4 or len(tok) < 4:
            return False
        if len(kr) >= 5 and root(t) == kr:
            return True
        if len(kp) >= 4 and phon(t) == kp:
            return True
        return min(len(t), len(tok)) >= 6 and within_one(t, tok)

    def has(self, k) -> bool:
        tok, kr, kp = k
        if tok in self.set:
            return True
        if len(tok) < 4:
            return False
        if (len(kr) >= 5 and kr in self.roots) or (len(kp) >= 4 and kp in self.phons):
            return True
        return len(tok) >= 6 and any(len(t) >= 6 and abs(len(t) - len(tok)) <= 1 and within_one(t, tok) for t in self.set)

    def positions(self, group) -> list:
        return [i for i, t in enumerate(self.toks) if any(self.same(t, k) for k in group)]


def _covered(hits, need, window) -> bool:
    """Au moins `need` groupes différents trouvés dans une fenêtre de `window` mots (fenêtre glissante)."""
    cnt, left = Counter(), 0
    for pos, g in hits:
        cnt[g] += 1
        while len(cnt) >= need:
            if pos - hits[left][0] <= window:
                return True
            lg = hits[left][1]
            cnt[lg] -= 1
            if not cnt[lg]:
                del cnt[lg]
            left += 1
    return False


def usable(groups) -> bool:
    """Un déclencheur d'un seul mot doit être distinctif (6 lettres et plus : « kickstart », « naming », pas « lance »)."""
    return len(groups) > 1 or (len(groups) == 1 and any(len(k[0]) >= 6 for k in groups[0]))


def phrase_hit(groups, q) -> bool:
    """Un déclencheur est reconnu si tous ses mots-clés sont là, rapprochés (fenêtre de n + 3 mots)."""
    if not usable(groups):
        return False
    n = len(groups)
    hits = sorted((p, gi) for gi, g in enumerate(groups) for p in q.positions(g))
    return _covered(hits, n, n + 3)


def match(text, skills, exclude=(), min_score=4.0, long_chars=500) -> list:
    """Skills qui collent au message, la plus sûre d'abord. « Sûre » : un déclencheur reconnu ou le nom cité.
    « Peut-être » : un mot distinctif du nom de la skill + un autre mot-clé, score ≥ min_score, aucun mot de la partie
    « Ne pas utiliser » — jamais sur un long texte (> long_chars), où des mots épars se croisent par hasard."""
    q = Query(text)
    if not q.toks:
        return []
    weak_ok = len(q.text) <= long_chars
    out = []
    for s in skills:
        if s["name"] in exclude:
            continue
        if any(phrase_hit(p["groups"], q) for p in s.get("neg_triggers", [])):
            continue
        why = None
        cited = s["name"].partition(":")[2] if s.get("plugin") else s["name"]  # « brainstorming » suffit pour plugin:…
        if len(cited) >= 5 and re.search(rf"(?<![\w-]){re.escape(fold(cited))}(?![\w-])", q.text):
            why = "nom cité"
        for p in s["triggers"]:
            if why:
                break
            if phrase_hit(p["groups"], q):
                why = f"« {p['text']} »"
        matched = {k[0]: (k[3], k[4]) for k in s["kw"] if q.has(k[:3])}
        score = round(sum(w for w, _ in matched.values()), 2)
        neg = [k[0] for k in s.get("neg_kw", []) if q.has(k)]
        if why:  # déclencheur reconnu, mais un mot de « Ne pas utiliser… » dans le message → seulement « peut-être »
            strong = why == "nom cité" or not neg
            out.append({"name": s["name"], "strong": strong, "score": round(10 + score, 2),
                        "why": why if strong else f"{why}, mais « {neg[0]} » est exclu", "skill": s})
            continue
        named = [t for t, (_, kind) in matched.items() if kind == "name" and len(t) >= 5 and t not in GENERIC_NAME]
        if not weak_ok or not named or len(matched) < 2 or score < min_score:
            continue
        if neg:
            continue
        out.append({"name": s["name"], "strong": False, "score": score,
                    "why": "mots " + ", ".join(sorted(matched, key=lambda t: -matched[t][0])[:4]), "skill": s})
    out.sort(key=lambda r: (not r["strong"], -r["score"]))
    return out


def hint_line(r) -> str:
    s = r["skill"]
    what = short(re.sub(r"^À utiliser\s+", "", split_desc(s["description"])[0]).strip(" .—-"), 110)
    if r["strong"]:
        return f"🧩 Skill à charger d'abord (outil Skill) : `{s['name']}` — {r['why']} · {what}"
    return f"🧩 Skill peut-être utile : `{s['name']}` ({r['why']}) — {what}. La charger si la demande colle."


# ------------------------------------------------------------------------------------------ méthode collée
def pasted_method(raw, min_chars=500) -> str | None:
    """Le texte collé (ou très long message) ressemble-t-il à un prompt / une méthode réutilisable ? Rôle, tâche,
    étapes, format de sortie… et une structure (titres, listes) ; pas du code ni un journal d'erreurs."""
    raw = raw or ""
    blocks = [m.group(1) for m in PASTE_TAG.finditer(raw)]
    if not blocks and len(raw) >= 3 * min_chars:
        blocks = [raw]
    for b in blocks:
        if len(b) < min_chars:
            continue
        lines = [ln for ln in b.splitlines() if ln.strip()]
        if len(lines) < 5 or sum(1 for ln in lines if CODE_RE.search(ln)) > 0.3 * len(lines):
            continue
        kinds = {m.group(1).rstrip("s") for m in MARKERS.finditer(fold(b))}
        if len(kinds) >= 4 and sum(1 for ln in lines if STRUCT_RE.search(ln)) >= 3:
            return b
    return None


def fingerprint(text) -> set:
    """Mots qui survivent à une traduction : noms propres, sigles, numéros de version (« Scott Malin », « v1.7.1 »)."""
    out = set()
    for w in re.findall(r"\b(?:[A-Z][A-Za-z]{2,}|[A-Z]{2,}\d*|v?\d+(?:\.\d+)+)\b", text or ""):
        f = fold(w)
        if f not in FP_STOP and len(f) >= 3:
            out.add(f)
    return out


def similar_skill(text, skills) -> tuple:
    """Skill existante qui reprend probablement cette méthode (même prompt recollé, autre version…)."""
    fp = fingerprint(text)
    best, best_n = None, 0
    for s in skills:
        try:
            body = Path(s["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        shared = fp & fingerprint(body)
        n = len(shared) + 2 * sum(1 for w in shared if any(c.isdigit() for c in w))
        if n > best_n:
            best, best_n = s, n
    return (best, best_n) if best_n >= 4 else (None, 0)


def paste_line(raw, cfg, skills) -> str | None:
    mode = (cfg or {}).get("paste", "propose")
    if mode not in ("auto", "propose"):
        return None
    block = pasted_method(raw, (cfg or {}).get("paste_min_chars", 500))
    if not block:
        return None
    sim, _ = similar_skill(block, skills)
    if sim:
        return (f"🧩 Méthode collée qui ressemble à la skill `{sim['name']}` ({sim['path']}) : la mettre à jour (version, "
                "étapes, déclencheurs) plutôt qu'en créer une nouvelle, puis `brain skill check`.")
    how = ("`brain skill new <nom> -d \"À utiliser quand… « déclencheur » … Ne pas utiliser pour…\" --body-file <fichier>` "
           "(crée la skill et sa fiche dans le cerveau), puis `brain skill check`")
    if mode == "auto":
        return ("🧩 Méthode / prompt collé — règle de l'utilisateur : tout ce qu'il donne doit s'activer tout seul → en "
                f"faire une skill personnelle sans attendre : {how} ; l'exécuter aussi s'il le demande.")
    return f"🧩 Méthode / prompt collé : proposer d'en faire une skill personnelle qui se déclenchera seule ({how})."


# ------------------------------------------------------------------------------------------ suivi
def load_stats() -> dict:
    return read_json(STATS_FILE, {}) or {}


def bump(names, field) -> None:
    if not names:
        return
    with FileLock(STATS_FILE.with_suffix(".lock")):
        st = load_stats()
        for n in names:
            s = st.setdefault(n, {})
            s[field] = s.get(field, 0) + 1
            s[f"{field}_at"] = now_iso()
        write_json(STATS_FILE, st)


def record_usage(st, tx) -> list:
    """Skills chargées pendant la session (outil Skill, lu dans le transcript) → compteurs « chargée » et
    « chargée après avoir été soufflée »."""
    seen = set(st.get("skills_counted", []))
    new = [s for s in tx.get("skills", []) if s not in seen]
    if not new:
        return []
    hinted = set(st.get("skills_hinted", []))
    bump(new, "used")
    bump([s for s in new if s in hinted], "used_after_hint")
    st["skills_counted"] = sorted(seen | set(new))
    return new


# ------------------------------------------------------------------------------------------ contrôle
def check(skills=None, exclude=()) -> list:
    """Problèmes qui empêchent une skill de se déclencher seule ou de bien marcher → [(niveau, skill, message)]. Skill de
    plugin : seulement ses déclencheurs (son SKILL.md n'est pas à nous) ; écartée du réflexe (`exclude`) : rien."""
    skills = index() if skills is None else skills
    exclude = set(exclude)
    out = []
    for s in skills:
        name, path, desc = s["name"], Path(s["path"]), s["description"]
        folder = path.parent.name
        if s.get("plugin"):
            if name in exclude:
                continue
            if not s["triggers"]:
                out.append(("ℹ️", name, f"skill du plugin {s['plugin']} sans déclencheur : le réflexe ne marche qu'aux "
                                        f"mots de sa description — en ajouter : `brain skill trig {name} \"…\"`"))
            for v in s.get("vague", []):
                out.append(("ℹ️", name, f"déclencheur « {v} » trop vague (un seul mot court) : ignoré par le réflexe"))
            for p in s["triggers"]:
                got = match(p["text"], skills, exclude=exclude)
                if not got or got[0]["name"] != name:
                    out.append(("⚠️", name, f"le déclencheur « {p['text']} » mène à "
                                            f"{got[0]['name'] if got else 'aucune skill'}"))
            continue
        if not desc:
            out.append(("❌", name, "pas de description : Claude ne saura jamais quand la charger"))
            continue
        if not NAME_RE.match(name) or len(name) > 64:
            out.append(("❌", name, "nom invalide (minuscules, chiffres et tirets, 64 car. max)"))
        if name != folder:
            out.append(("⚠️", name, f"le nom diffère du dossier « {folder} »"))
        if len(desc) > 1024:
            out.append(("❌", name, f"description de {len(desc)} car. (> 1024 : coupée par Claude Code)"))
        elif len(desc) < 80:
            out.append(("⚠️", name, "description très courte : dire QUAND l'utiliser et avec quels mots"))
        if not s["triggers"]:
            out.append(("⚠️", name, "aucun déclencheur « … » dans la description : le réflexe ne marche qu'aux mots-clés"))
        for v in s.get("vague", []):
            if not v.startswith("/"):
                out.append(("ℹ️", name, f"déclencheur « {v} » trop vague (un seul mot court) : ignoré par le réflexe"))
        if not NEG_RE.search(desc):
            out.append(("ℹ️", name, "pas de « Ne pas utiliser… » : utile pour éviter les déclenchements à tort"))
        if s.get("lines", 0) > 500:
            out.append(("⚠️", name, f"SKILL.md de {s['lines']} lignes (> 500) : déplacer le détail dans des fichiers liés"))
        for link in s.get("links", []):
            if re.match(r"^[a-z]+:", link):
                continue
            if not (path.parent / link).exists():
                out.append(("❌", name, f"lien cassé : {link}"))
        for p in s["triggers"]:  # chaque déclencheur doit mener à sa propre skill
            got = match(p["text"], skills, exclude=exclude)
            if not got or got[0]["name"] != name:
                other = got[0]["name"] if got else "aucune skill"
                out.append(("⚠️", name, f"le déclencheur « {p['text']} » mène à {other}"))
    seen = {}
    for s in skills:
        if s["name"] in exclude:
            continue
        for p in s["triggers"]:
            key = fold(p["text"])
            if key in seen and seen[key] != s["name"]:
                out.append(("⚠️", s["name"], f"déclencheur « {p['text']} » partagé avec {seen[key]}"))
            seen.setdefault(key, s["name"])
    return out


def notice(skills=None) -> str:
    """Ligne de démarrage seulement s'il y a un vrai problème (❌) : sinon rien, zéro token."""
    try:
        errs = [(n, m) for lvl, n, m in check(skills) if lvl == "❌"]
    except Exception:
        return ""
    if not errs:
        return ""
    head = " · ".join(f"`{n}` : {m}" for n, m in errs[:3])
    return f"🧩 Skills perso à réparer ({len(errs)}) — {head}. Détail : `brain skill check`."


# ------------------------------------------------------------------------------------------ création
def scaffold(name, description, body="", force=False) -> Path:
    """Crée ~/.claude/skills/<name>/SKILL.md (en-tête valide) ; refuse d'écraser sans force."""
    name = name.strip().lower()
    if not NAME_RE.match(name) or len(name) > 64:
        raise ValueError("nom invalide : minuscules, chiffres et tirets (ex. « article-seo »), 64 car. max")
    description = " ".join((description or "").split())
    if not description:
        raise ValueError("description obligatoire : quand l'utiliser, avec quels mots « … », et quand ne pas l'utiliser")
    if len(description) > 1024:
        raise ValueError(f"description de {len(description)} car. : 1024 max")
    path = SKILLS_DIR / name / "SKILL.md"
    if path.exists() and not force:
        raise FileExistsError(f"{path} existe déjà (--force pour remplacer, ou modifier le fichier)")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (body or "").strip() or f"# {name}\n\n(Étapes de la méthode à suivre.)"
    desc_yaml = description.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(f"---\nname: {name}\ndescription: \"{desc_yaml}\"\n---\n\n{body}\n", encoding="utf-8")
    return path
