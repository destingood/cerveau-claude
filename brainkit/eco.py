"""Mode éco — moins de tokens à chaque requête, sans rien perdre (lecture locale, zéro token).

Trois leviers officiels de Claude Code, tous réversibles (`brain eco --annuler`) :
- `bashOutputMaxChars` (Claude Code ≥ 2.1.261) : une sortie de commande trop longue est enregistrée dans un fichier ;
  Claude n'en reçoit qu'un aperçu (2 000 caractères) et le chemin — rien n'est perdu, et la sortie n'est plus relue à
  chaque requête suivante ;
- `autoCompactWindow` : la conversation est résumée plus tôt (avec un modèle à 1 M de tokens, Claude Code n'attend que
  vers 967 k par défaut) ;
- les plugins installés mais jamais utilisés : leurs descriptions sont relues à chaque session. Le cerveau les liste ; il
  ne les désactive que sur demande (`--desactiver`), après accord de l'utilisateur — ou chaque jour tout seul, en arrière-plan,
  si l'utilisateur active la veille (`--plugins-auto`) : avec les skills claude.ai (`syncClaudeAiSkills`) si aucune n'a servi.

Ces réglages vivent dans les réglages UTILISATEUR (`~/.claude/settings.json`) : le settings.json d'un plugin ne peut pas
les poser. Le cerveau n'écrase jamais une valeur posée par l'utilisateur (sans `--forcer`), garde une copie du fichier
(`settings.json.bak-cerveau-eco`) et retient dans sa configuration (`eco.avant`) l'état d'avant, pour le rétablir à
l'identique. Un fichier de réglages illisible n'est jamais touché."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .common import CHARS_PER_TOKEN, CLAUDE_HOME, CMD, CONFIG_FILE, days_since, load_config, log, now_iso, read_json, \
    set_config, write_json

OUT_KEY, WIN_KEY = "bashOutputMaxChars", "autoCompactWindow"
OUT_RANGE, WIN_RANGE = (4000, 128000), (100000, 1000000)
DEFAULT_OUT, DEFAULT_WIN = 10000, 200000
BACKUP = "settings.json.bak-cerveau-eco"
PREVIEW_CHARS = 2000   # ce que Claude garde d'une sortie mise en fichier
UNUSED_DAYS = 30       # un plugin sans aucun usage dans les transcripts de cette période est « inutilisé »
RECENT_DAYS = 14       # installé depuis moins longtemps : pas assez de recul pour le dire inutilisé
OWN_PLUGIN = "cerveau"  # jamais proposé : c'est ce plugin-ci
CLAUDE_AI = "anthropic-skills"  # préfixe des skills de claude.ai synchronisées dans Claude Code
SYNC_KEY = "syncClaudeAiSkills"  # le réglage (documenté) qui coupe cette synchronisation
ABSENT = object()      # « clé absente » (jamais écrit dans un fichier)


# ------------------------------------------------------------------------------------------ formats
def _n(x) -> str:
    return f"{int(x):,}".replace(",", " ")  # 10000 → « 10 000 »


def _k(x) -> str:
    return f"{x / 1000:.0f} k"


def _tok(x) -> str:
    return f"{x / 1000:.1f} k" if round(x) >= 1000 else f"{x:.0f}"


def _val(key, v) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return json.dumps(v, ensure_ascii=False)
    return _k(v) if key == WIN_KEY else _n(v)


def _same(a, b) -> bool:
    return a == b and isinstance(a, bool) == isinstance(b, bool)


# ------------------------------------------------------------------------------------------ réglages de Claude Code
def settings_path():
    return CLAUDE_HOME / "settings.json"


def _write(path, data):
    """Écrit les réglages en suivant un lien symbolique (fichier géré par un outil de dotfiles) : le lien reste un lien."""
    write_json(Path(os.path.realpath(path)), data, indent=2)


def read_settings():
    """(réglages, None) ; ({}, None) s'il n'existe pas ; (None, raison) s'il est illisible — alors on ne touche à rien."""
    path = settings_path()
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text) if text.strip() else {}  # fichier vide : aucun réglage
    except (OSError, ValueError) as exc:
        return None, f"{path} illisible ({type(exc).__name__}) : corrige-le d'abord, rien n'a été modifié"
    if not isinstance(data, dict):
        return None, f"{path} n'est pas un objet JSON : rien n'a été modifié"
    return data, None


def _env_value(settings, name):
    """Variable d'environnement de Claude Code : celle du processus, sinon le bloc « env » des réglages."""
    v = os.environ.get(name)
    if not v:
        env = (settings or {}).get("env")
        v = env.get(name) if isinstance(env, dict) else None
    return str(v) if v not in (None, "") else None


def targets(cfg=None, out=None, win=None) -> tuple:
    """(sortie, fenêtre) à poser : options > configuration (eco.*) > défauts. ValueError si hors limites."""
    eco = (cfg or load_config()).get("eco") or {}
    res = []
    for label, given, key, default, (lo, hi) in (("--sortie", out, "bash_output_max_chars", DEFAULT_OUT, OUT_RANGE),
                                                 ("--fenetre", win, "auto_compact_window", DEFAULT_WIN, WIN_RANGE)):
        v = given if given is not None else eco.get(key, default)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            src = label if given is not None else f"config eco.{key}"
            raise ValueError(f"{src} = {v!r} hors limites (de {_n(lo)} à {_n(hi)})")
        res.append(v)
    return tuple(res)


def current(settings=None) -> dict:
    """Valeurs actuelles dans settings.json ({OUT_KEY, WIN_KEY} : None = non réglé ; {} si illisible)."""
    if settings is None:
        settings, err = read_settings()
        if err:
            return {}
    return {OUT_KEY: settings.get(OUT_KEY), WIN_KEY: settings.get(WIN_KEY)}


def warnings(settings) -> list:
    """Ce qui l'emporte sur les réglages du mode éco (ordre de priorité de Claude Code)."""
    out = []
    v = _env_value(settings, "CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if v:
        out.append(f"⚠ CLAUDE_CODE_AUTO_COMPACT_WINDOW={v} (variable d'environnement) l'emporte sur {WIN_KEY}")
    v = _env_value(settings, "BASH_MAX_OUTPUT_LENGTH")
    if v:
        out.append(f"⚠ BASH_MAX_OUTPUT_LENGTH={v} est ignorée dès que {OUT_KEY} est réglé")
    models = settings.get("modelSettings")
    for model, conf in (models.items() if isinstance(models, dict) else ()):
        if isinstance(conf, dict) and WIN_KEY in conf:
            out.append(f"⚠ modelSettings.{model}.{WIN_KEY} = {_val(WIN_KEY, conf[WIN_KEY])} (écrit par /autocompact) "
                       f"l'emporte sur le réglage général pour ce modèle")
    return out


# ------------------------------------------------------------------------------------------ écriture (avec retour)
def _unset(*dotted):
    """Retire des clés de la configuration du cerveau (set_config ne sait qu'écrire)."""
    cfg = read_json(CONFIG_FILE, {}) or {}
    for key in dotted:
        *path, last = key.split(".")
        cur = cfg
        for part in path:
            cur = cur.get(part) if isinstance(cur, dict) else None
        if isinstance(cur, dict):
            cur.pop(last, None)
    write_json(CONFIG_FILE, cfg)


def _section(cfg, name) -> dict:
    """Copie de eco.<name> (état d'avant / valeurs posées), modifiable sans toucher à la configuration chargée."""
    raw = (cfg.get("eco") or {}).get(name)
    data = json.loads(json.dumps(raw)) if isinstance(raw, dict) else {}
    data.setdefault("cles", {})
    data.setdefault("plugins", {})
    return data


def commit(wants, force=False) -> tuple:
    """Écrit dans settings.json : wants = [("cle", nom, valeur) | ("plugin", « nom@marketplace », False)].
    Copie de sécurité la 1re fois ; l'état d'avant est retenu (eco.avant) pour `--annuler`. Une clé que l'utilisateur
    avait réglée n'est pas remplacée sans `force`. → (ok, {nom: valeur posée}, lignes de compte rendu)."""
    settings, err = read_settings()
    if err:
        return False, {}, [f"⚠ {err}"]
    path, backup = settings_path(), settings_path().with_name(BACKUP)
    cfg = load_config()
    avant, pose = _section(cfg, "avant"), _section(cfg, "pose")
    fresh = not (avant["cles"] or avant["plugins"])  # rien de posé encore : le fichier d'aujourd'hui est le « avant »
    new, posees, lignes = dict(settings), {}, []
    if any(w[0] == "plugin" for w in wants) and not isinstance(new.get("enabledPlugins", {}), dict):
        return False, {}, ["⚠ enabledPlugins n'est pas un objet JSON dans settings.json : rien n'a été modifié"]
    for kind, name, value in wants:
        if kind == "cle":
            bucket, cur = "cles", new.get(name, ABSENT)
            label, show = name, (lambda v, n=name: _val(n, v))
        else:
            bucket, cur = "plugins", (new.get("enabledPlugins") or {}).get(name, ABSENT)
            label, show = f"plugin {name}", (lambda v: "désactivé" if v is False else "actif")
        if cur is not ABSENT and _same(cur, value):
            lignes.append(f"✓ {label} : déjà {show(value)}")
            continue
        mine = cur is not ABSENT and _same(pose[bucket].get(name, ABSENT), cur)
        if kind == "cle" and cur is not ABSENT and not mine and not force:
            lignes.append(f"⚠ {name} : déjà réglé à {show(cur)} (par toi) — gardé ; `--forcer` pour mettre {show(value)}")
            continue
        if name not in avant[bucket]:
            avant[bucket][name] = {"absent": True} if cur is ABSENT else {"valeur": cur}
        pose[bucket][name] = value
        if kind == "cle":
            new[name] = value
        else:
            if "enabledPlugins" not in new and "ep_absent" not in avant:
                avant["ep_absent"] = True
            new["enabledPlugins"] = {**(new.get("enabledPlugins") or {}), name: value}
        posees[name] = value
        before = ("non réglé" if kind == "cle" else "actif") if cur is ABSENT else show(cur)
        lignes.append(f"✓ {label} = {show(value)} (avant : {before})")
    if not posees:
        return True, {}, lignes
    created = not path.exists()
    if created:
        avant.setdefault("fichier_absent", True)
    try:
        if not created and (fresh or not backup.exists()):
            shutil.copy2(path, backup)
            lignes.append(f"→ copie de sécurité : {backup}")
        _write(path, new)
        set_config("eco.avant", avant)
        set_config("eco.pose", pose)
    except OSError as exc:
        _restore_file(path, settings, created)
        return False, {}, lignes + [f"⚠ écriture impossible ({exc}) : rien n'a été modifié"]
    return True, posees, lignes


def _restore_file(path, settings, created):
    """Remet settings.json dans l'état lu au départ (écriture interrompue) ; erreurs ignorées."""
    try:
        if created:
            path.unlink()
        else:
            _write(path, settings)
    except OSError as exc:
        log(f"éco : retour arrière de {path} impossible ({exc!r})")


def apply_eco(out=None, win=None, force=False, cfg=None) -> tuple:
    """Pose bashOutputMaxChars et autoCompactWindow. → (ok, {clé: valeur posée}, lignes). Une variable d'environnement
    de l'utilisateur (BASH_MAX_OUTPUT_LENGTH, CLAUDE_CODE_AUTO_COMPACT_WINDOW) compte comme une valeur à lui."""
    cfg = cfg or load_config()
    try:
        t_out, t_win = targets(cfg, out, win)
    except ValueError as exc:
        return False, {}, [f"✗ {exc}"]
    settings, err = read_settings()
    if err:
        return False, {}, [f"⚠ {err}"]
    wants, lignes = [], []
    for key, value, env in ((OUT_KEY, t_out, "BASH_MAX_OUTPUT_LENGTH"),
                            (WIN_KEY, t_win, "CLAUDE_CODE_AUTO_COMPACT_WINDOW")):
        theirs = _env_value(settings, env)
        if theirs and not force:
            lignes.append(f"⚠ {env}={theirs} : déjà réglé par toi — {key} non posé ; `--forcer` pour le poser quand même")
        else:
            wants.append(("cle", key, value))
    ok, posees, more = commit(wants, force)
    if ok:
        set_config("eco.applique_le", now_iso())
    return ok, posees, lignes + more


def summary(posees) -> str:
    """Ce que le mode éco change, en clair (valeurs réelles)."""
    parts = []
    if OUT_KEY in posees:
        parts.append(f"sorties de commandes > {_n(posees[OUT_KEY])} caractères mises en fichier "
                     "(aperçu seul dans la conversation)")
    if WIN_KEY in posees:
        parts.append(f"conversation résumée vers {_k(posees[WIN_KEY])} tokens")
    return ", ".join(parts)


def notice(posees) -> str:
    """La ligne annoncée à l'utilisateur quand le mode éco vient d'être posé."""
    return f"⚡ Mode éco activé : {summary(posees)} · `{CMD} eco --annuler` pour revenir" if posees else ""


def auto_start(cfg=None) -> str:
    """Au démarrage d'une session : pose le mode éco UNE seule fois (config eco.auto, eco.applique_le).
    → la ligne à ajouter au démarrage, ou ''."""
    cfg = cfg or load_config()
    eco = cfg.get("eco") or {}
    if not eco.get("auto", True) or eco.get("applique_le"):
        return ""
    ok, posees, lignes = apply_eco(cfg=cfg)
    log("éco (démarrage) : " + " | ".join(lignes))
    return notice(posees) if ok else ""


def apply_report(cfg=None) -> tuple:
    """Pour `brain optimize --apply` → ({clé: valeur posée}, remarque courte : « déjà actif », valeurs gardées…)."""
    cfg = cfg or load_config()
    eco = cfg.get("eco") or {}
    if not eco.get("auto", True) and not eco.get("applique_le"):
        return {}, "laissé de côté : tu l'avais annulé (`brain eco --appliquer` pour le remettre)"
    ok, posees, lignes = apply_eco(cfg=cfg)
    kept = [x.lstrip("⚠ ") for x in lignes if x.startswith("⚠")]
    if not ok:
        return {}, "; ".join(kept or ["impossible pour l'instant (`brain eco` pour le détail)"])
    return posees, "; ".join(kept) if kept else ("" if posees else "déjà actif")


def undo() -> tuple:
    """Remet exactement l'état d'avant (clés retirées ou valeurs d'origine rétablies, plugins réactivés), efface
    l'enregistrement et coupe l'application automatique et la veille des plugins. → (code, texte)."""
    settings, err = read_settings()
    if err:
        return 1, f"⚠ {err}"
    cfg = load_config()
    avant, pose = _section(cfg, "avant"), _section(cfg, "pose")
    new, lignes = dict(settings), []
    for name, rec in avant["cles"].items():
        cur = new.get(name, ABSENT)
        if cur is ABSENT:
            continue
        if not _same(cur, pose["cles"].get(name, ABSENT)):
            lignes.append(f"⚠ {name} : modifié depuis (valeur {_val(name, cur)}) — laissé tel quel")
        elif rec.get("absent"):
            del new[name]
            lignes.append(f"✓ {name} retiré (il n'était pas réglé avant)")
        else:
            new[name] = rec.get("valeur")
            lignes.append(f"✓ {name} remis à {_val(name, rec.get('valeur'))}")
    ep = new.get("enabledPlugins")
    if avant["plugins"] and isinstance(ep, dict):
        ep = dict(ep)
        for key, rec in avant["plugins"].items():
            cur = ep.get(key, ABSENT)
            if cur is ABSENT or not _same(cur, pose["plugins"].get(key, ABSENT)):
                continue
            if rec.get("absent"):
                del ep[key]
            else:
                ep[key] = rec.get("valeur")
            lignes.append(f"✓ plugin {key} réactivé")
        if ep or not avant.get("ep_absent"):
            new["enabledPlugins"] = ep
        else:
            del new["enabledPlugins"]
    path = settings_path()
    if new != settings:
        try:
            if not new and avant.get("fichier_absent"):
                path.unlink()  # le fichier n'existait pas avant le mode éco
            else:
                _write(path, new)
        except OSError as exc:
            return 1, f"⚠ écriture de {path} impossible ({exc}) : rien n'a été modifié"
    _unset("eco.avant", "eco.pose", "eco.applique_le", "eco.annonce", "eco.plugins_vus_le")
    set_config("eco.auto", False)
    set_config("eco.plugins_auto", False)  # sinon la veille referait demain ce qui vient d'être défait
    if not lignes:
        lignes.append("✓ rien à restaurer dans settings.json")
    lignes.append(f"✓ mode éco annulé : plus rien n'est posé tout seul (`{CMD} eco --appliquer` pour le remettre)")
    return 0, "\n".join(lignes)


# ------------------------------------------------------------------------------------------ plugins inutilisés
def installed_plugins() -> dict:
    """{« nom@marketplace » : [entrées]} d'après plugins/installed_plugins.json de Claude Code (vide s'il manque)."""
    data = read_json(CLAUDE_HOME / "plugins" / "installed_plugins.json", {}) or {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    out = {}
    for key, entries in (plugins.items() if isinstance(plugins, dict) else ()):
        entries = [entries] if isinstance(entries, dict) else entries
        out[str(key)] = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    return out


def _recent(entries) -> bool:
    return bool(entries) and min(days_since(e.get("installedAt")) for e in entries) < RECENT_DAYS


def _used_in(raw, names, used):
    """Une ligne d'assistant qui appelle un outil : marque les plugins dont une skill, un agent ou un outil MCP sert."""
    try:
        o = json.loads(raw)
    except ValueError:
        return
    msg = o.get("message") if isinstance(o, dict) else None
    blocks = msg.get("content") if isinstance(msg, dict) else None
    for b in blocks if isinstance(blocks, list) else ():
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        name, inp = str(b.get("name") or ""), b.get("input")
        inp = inp if isinstance(inp, dict) else {}
        ref = str(inp.get("skill") or "") if name == "Skill" else \
            str(inp.get("subagent_type") or "") if name in ("Task", "Agent") else ""
        for n in names:
            if (ref and ref.startswith(f"{n}:")) or name.startswith(f"mcp__plugin_{n}_") \
                    or name.startswith(f"mcp__plugin_{re.sub('[^A-Za-z0-9_-]', '_', n)}_"):
                used.add(n)


_COMMAND = re.compile(rb"<command-name>/?([^<\s\\]+)</command-name>")


def _scan(names, days=UNUSED_DAYS):
    """Transcripts des `days` derniers jours → (plugins utilisés parmi `names` — et « anthropic-skills » si une skill de
    claude.ai a servi —, dernière liste de skills vue)."""
    names = set(names) | {CLAUDE_AI}
    root = CLAUDE_HOME / "projects"
    cut = time.time() - days * 86400
    files = []
    for f in root.rglob("*.jsonl") if root.is_dir() else ():
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if m >= cut:
            files.append((m, f))
    files.sort(key=lambda x: x[0], reverse=True)
    used, listing, listed = set(), "", False
    for _, f in files:
        main = "subagents" not in f.parts
        try:
            fh = open(f, "rb")
        except OSError:
            continue
        found = None
        with fh:
            for raw in fh:
                if b'"tool_use"' in raw and (b'"Skill"' in raw or b"mcp__plugin_" in raw or b"subagent_type" in raw):
                    _used_in(raw, names, used)
                elif b"<command-name>/" in raw:  # commande d'un plugin tapée par l'utilisateur
                    for hit in _COMMAND.finditer(raw):
                        used.update(n for n in names if hit.group(1).decode("utf-8", "replace").startswith(f"{n}:"))
                if main and not listed and b'"skill_listing"' in raw:
                    try:
                        a = json.loads(raw).get("attachment") or {}
                    except ValueError:
                        continue
                    if a.get("type") == "skill_listing" and isinstance(a.get("content"), str) \
                            and (a.get("isInitial") is not False or found is None):
                        found = a["content"]
        if found is not None and not listed:
            listing, listed = found, True
    return used, listing


def _weight(listing, name) -> int:
    """Caractères des lignes de la liste de skills qui reviennent à ce plugin (« - nom:skill : description »)."""
    chars, mine = 0, False
    for line in listing.split("\n"):
        if line.startswith("- "):
            mine = line.startswith(f"- {name}:")
        if mine:
            chars += len(line) + 1
    return chars


def _audit(settings, days=UNUSED_DAYS, cpt=CHARS_PER_TOKEN, ai=False) -> tuple:
    """→ ([(« nom@marketplace », tokens)] des plugins actifs sans aucun usage depuis `days` jours, du plus lourd au plus
    léger ; tokens des skills claude.ai listées dont aucune n'a servi, ou None). Jamais le cerveau lui-même ; poids = leurs
    lignes dans la dernière liste de skills. `ai` : chercher aussi les skills claude.ai (sinon, sans plugin candidat, les
    transcripts ne sont pas parcourus)."""
    enabled = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
    cands = {key: key.partition("@")[0] for key, entries in installed_plugins().items()
             if key.partition("@")[0] != OWN_PLUGIN and enabled.get(key) is not False and not _recent(entries)}
    if not cands and not ai:
        return [], None
    used, listing = _scan(set(cands.values()), days)
    rows = [(key, _weight(listing, name) / cpt) for key, name in cands.items() if name not in used]
    rows.sort(key=lambda r: (-r[1], r[0]))
    chars = _weight(listing, CLAUDE_AI)
    return rows, (chars / cpt if ai and chars and CLAUDE_AI not in used else None)


def unused_plugins(settings=None, days=UNUSED_DAYS, cpt=CHARS_PER_TOKEN) -> list:
    """[(« nom@marketplace », tokens estimés par session)] des plugins actifs sans aucun usage depuis `days` jours."""
    if settings is None:
        settings, err = read_settings()
        if err:
            return []
    return _audit(settings, days, cpt)[0]


def _disable(keys) -> tuple:
    """enabledPlugins à false pour ces plugins (avec retour). → (ok, {clé: False posée}, lignes)."""
    installed = installed_plugins()
    wants, lignes = [], []
    for given in keys:
        found = [k for k in installed if k == given] or \
                [k for k in installed if "@" not in given and k.partition("@")[0] == given]
        if len(found) != 1:
            lignes.append(f"✗ {given} : " + ("plugin inconnu" if not found else "plusieurs marketplaces, précise nom@marketplace")
                          + f" (liste : `{CMD} eco`)")
        elif found[0].partition("@")[0] == OWN_PLUGIN:
            lignes.append(f"✗ {found[0]} : c'est le cerveau lui-même, je ne le désactive jamais")
        elif ("plugin", found[0], False) not in wants:
            wants.append(("plugin", found[0], False))
    ok, posees, more = commit(wants)
    return ok and not any(x.startswith("✗") for x in lignes), posees, lignes + more


def disable(keys) -> tuple:
    """`--desactiver nom@marketplace …` : enabledPlugins à false (avec retour). → (code, texte)."""
    ok, posees, lignes = _disable(keys)
    if posees:
        lignes.append(f"→ pris en compte au prochain démarrage de Claude Code · retour : `{CMD} eco --annuler`")
    return (0 if ok else 1), "\n".join(lignes)


def auto_plugins(force=False) -> str:
    """Veille des plugins inutilisés (`eco.plugins_auto`), au plus une fois par jour sauf `force` : désactive ceux dont
    aucune skill n'a servi depuis 30 jours (comme `--desactiver`) et coupe les skills claude.ai (`syncClaudeAiSkills` false)
    si la liste en montre et qu'aucune n'a servi. Seuls les plugins qui listent des skills sont touchés : sans skill, ils
    agissent peut-être par hooks. Copie de sécurité et retour par `--annuler` ; la valeur de l'utilisateur est respectée.
    → l'annonce (gardée dans eco.annonce pour le prochain démarrage), ou ''."""
    if not force and days_since((load_config().get("eco") or {}).get("plugins_vus_le")) < 1:
        return ""
    settings, err = read_settings()
    if err:
        log(f"éco (veille des plugins) : {err}")
        return ""
    rows, ai = _audit(settings, ai=True)
    rows = [r for r in rows if r[1] > 0]
    gone, saved = [], 0.0
    if rows:
        _, posees, _ = _disable([k for k, _ in rows])
        gone = [k for k, t in rows if k in posees]
        saved = sum(t for k, t in rows if k in posees)
    skills = False
    if ai:
        _, posees, _ = commit([("cle", SYNC_KEY, False)])
        skills = SYNC_KEY in posees
        saved += ai if skills else 0
    set_config("eco.plugins_vus_le", now_iso())
    parts = ([f"{len(gone)} plugin(s) inutilisé(s) depuis {UNUSED_DAYS} jours désactivé(s) ({', '.join(gone)})"] if gone else []) \
        + (["skills claude.ai non chargées"] if skills else [])
    if not parts:
        return ""
    if saved:
        parts.append(f"≈{_tok(saved)} tokens de moins par session")
    line = f"⚡ Mode éco : {' · '.join(parts)} · retour : `{CMD} eco --annuler`"
    set_config("eco.annonce", line)
    return line


def take_annonce(cfg=None) -> str:
    """L'annonce laissée par la veille des plugins : montrée une seule fois, au démarrage suivant."""
    note = ((cfg or load_config()).get("eco") or {}).get("annonce")
    if note:
        _unset("eco.annonce")
    return note if isinstance(note, str) else ""


def start(cfg=None) -> str:
    """Les lignes du mode éco pour le démarrage d'une session : réglages posés une fois + annonce de la veille."""
    return "\n".join(x for x in (auto_start(cfg), take_annonce(cfg)) if x)


def watch_plugins(mode) -> tuple:
    """`--plugins-auto [on|off]` → (code, texte) : « on » active la veille et la lance tout de suite."""
    if mode == "off":
        set_config("eco.plugins_auto", False)
        return 0, f"✓ veille quotidienne des plugins coupée (ce qui est déjà désactivé le reste : `{CMD} eco --annuler`)"
    settings, err = read_settings()
    if err:
        return 1, f"⚠ {err}"
    set_config("eco.plugins_auto", True)
    note = auto_plugins(force=True)
    return 0, f"{note}\n→ pris en compte au prochain démarrage de Claude Code" if note else \
        "✓ veille quotidienne des plugins activée : rien à retirer pour l'instant"


# ------------------------------------------------------------------------------------------ état et commande
def status(cfg=None) -> str:
    """`brain eco` sans option : réglages actuels, ce que le mode éco poserait, ce qui l'emporte, plugins inutilisés."""
    cfg = cfg or load_config()
    eco = cfg.get("eco") or {}
    L = ["⚡ Mode éco — moins de tokens à chaque requête, rien de perdu (réglages officiels de Claude Code)"]
    settings, err = read_settings()
    if err:
        return "\n".join(L + [f"⚠ {err}"])
    try:
        t_out, t_win = targets(cfg)
    except ValueError as exc:
        L.append(f"⚠ {exc} → valeurs par défaut")
        t_out, t_win = DEFAULT_OUT, DEFAULT_WIN
    mine = (eco.get("pose") or {}).get("cles") or {}
    for key, target, default, what in (
            (OUT_KEY, t_out, "30 000", "sortie de commande plus longue → fichier, aperçu seul dans la conversation ; "
                                      "Claude Code ≥ 2.1.261"),
            (WIN_KEY, t_win, "fenêtre du modèle, ≈ 967 k pour 1 M", "conversation résumée plus tôt")):
        cur = settings.get(key, ABSENT)
        if cur is ABSENT:
            L.append(f"  {key} : non réglé (Claude Code : {default}) → éco : {_val(key, target)} — {what}")
        elif _same(cur, target) or _same(cur, mine.get(key, ABSENT)):
            L.append(f"  {key} : {_val(key, cur)} ✓ ({what})")
        else:
            L.append(f"  {key} : {_val(key, cur)} — réglé par toi, gardé (éco : {_val(key, target)} ; `--forcer` pour le remplacer)")
    done = f"appliqué le {str(eco['applique_le'])[:10]}" if eco.get("applique_le") else "pas encore appliqué"
    L.append(f"  {done} · automatique au démarrage : {'oui' if eco.get('auto', True) else 'non'}")
    L.append("  veille quotidienne des plugins inutilisés : " + (
        f"oui · `{CMD} eco --plugins-auto off` pour la couper" if eco.get("plugins_auto") else
        f"non · `{CMD} eco --plugins-auto` pour l'activer (désactive tout seul plugins et skills claude.ai jamais utilisés)"))
    L += [f"  {w}" for w in warnings(settings)]
    rows = unused_plugins(settings)
    if rows:
        L.append(f"Plugins actifs jamais utilisés depuis {UNUSED_DAYS} j (leurs descriptions sont relues à chaque session) :")
        L += [f"  - {key} ≈ {_tok(tok)} tokens" if tok else
              f"  - {key} (aucune skill listée : agit peut-être par hooks, agents ou serveur MCP — à vérifier avant)"
              for key, tok in rows[:8]]
        L.append(f"→ `{CMD} eco --desactiver nom@marketplace` (demande d'abord à l'utilisateur)")
    L.append(f"→ `{CMD} eco --annuler` pour revenir" if eco.get("applique_le")
             else f"→ `{CMD} eco --appliquer` pour l'activer (sauvegarde + retour possible)")
    return "\n".join(L)


def run(appliquer=False, annuler=False, forcer=False, sortie=None, fenetre=None, desactiver=None, plugins_auto=None) -> tuple:
    """Point d'entrée de `brain eco` → (code de sortie, texte)."""
    if appliquer and annuler:
        return 1, "✗ --appliquer et --annuler ensemble : choisis l'un des deux"
    if annuler:
        return undo()
    L, code = [], 0
    if appliquer or sortie is not None or fenetre is not None:
        ok, posees, lignes = apply_eco(sortie, fenetre, forcer)
        L += lignes
        code = 0 if ok else 1
        if ok:
            set_config("eco.auto", True)  # demandé en toutes lettres : le mode éco est « voulu »
            for key, given in (("bash_output_max_chars", sortie), ("auto_compact_window", fenetre)):
                if given is not None:
                    set_config(f"eco.{key}", given)  # la valeur choisie devient la cible (optimize, démarrages futurs)
            settings, _ = read_settings()
            L += warnings(settings or {})
            if posees:
                L.append(f"→ pris en compte au plus tard au prochain démarrage de Claude Code · retour : `{CMD} eco --annuler`")
    if desactiver:
        c, text = disable(desactiver)
        L.append(text)
        code = code or c
    if plugins_auto:
        c, text = watch_plugins(plugins_auto)
        L.append(text)
        code = code or c
    return code, "\n".join(L) if L else status()
