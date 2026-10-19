"""Mode éco — moins de tokens à chaque requête, sans rien perdre (lecture locale, zéro token).

Chaque requête relit tout le contexte (outils, skills, consignes, conversation) : ce qui y est en trop coûte à CHAQUE
message. Leviers officiels de Claude Code posés tout seuls (une fois, puis les nouveaux quand `LEVIERS` augmente), tous
réversibles (`brain eco --annuler`) :
- `bashOutputMaxChars` (Claude Code ≥ 2.1.261) : une sortie de commande trop longue est enregistrée dans un fichier ;
  Claude n'en reçoit qu'un aperçu (2 000 caractères) et le chemin — rien n'est perdu, et la sortie n'est plus relue à
  chaque requête suivante ;
- `autoCompactWindow` : la conversation est résumée plus tôt (avec un modèle à 1 M de tokens, Claude Code n'attend que
  vers 967 k par défaut) ;
- `skillListingBudgetFraction` : la liste des skills est plafonnée à 0,5 % du contexte (1 % par défaut) ; au-delà, Claude
  Code retire d'abord les descriptions des skills les MOINS utilisées — tous les noms restent ;
- `autoMemoryEnabled` false : la mémoire automatique de Claude Code double le cerveau (consignes relues à chaque
  requête) ; coupée seulement quand tout ce qu'elle contient est importé dans le cerveau ;
- `promptCacheTtl` (cache adaptatif, chaque jour en arrière-plan) : 5 min ou 1 h d'après une simulation sur les pauses
  réelles des 7 derniers jours ; posé seulement si le gain est net (≥ 5 % du poids total) ;
- les plugins installés mais jamais utilisés : leurs descriptions sont relues à chaque session. Le cerveau les liste ; il
  ne les désactive que sur demande (`--desactiver`), après accord de l'utilisateur — ou chaque jour tout seul, en arrière-plan,
  si l'utilisateur active la veille (`--plugins-auto`) : avec les skills claude.ai (`syncClaudeAiSkills`) si aucune n'a servi.

Sur accord de l'utilisateur seulement (`--poser ID…`, gains estimés dans `brain eco`, retour : `--retirer ID…`) : outils
intégrés et connecteurs jamais utilisés en 30 jours (règles `permissions.deny` : l'outil sort du contexte), consignes git,
plafond d'effort, lecture de fichier plafonnée, sous-agents sur Sonnet.

Ces réglages vivent dans les réglages UTILISATEUR (`~/.claude/settings.json`) : le settings.json d'un plugin ne peut pas
les poser. Le cerveau n'écrase jamais une valeur posée par l'utilisateur (sans `--forcer`), garde une copie du fichier
(`settings.json.bak-cerveau-eco`) et retient dans sa configuration (`eco.avant`) l'état d'avant, pour le rétablir à
l'identique (clés imbriquées comme `env.X` et règles de refus comprises). Un fichier de réglages illisible n'est jamais
touché."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .common import CHARS_PER_TOKEN, CLAUDE_HOME, CMD, days_since, load_config, log, now_iso, read_json, set_config, \
    update_config, write_json

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
LEVIERS = 2            # version des leviers posés tout seuls : une installation plus ancienne reçoit les nouveaux, une fois
SKILLS_KEY, SKILLS_FRACTION = "skillListingBudgetFraction", 0.005
MEMORY_KEY, MEMORY_ENV = "autoMemoryEnabled", "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
CACHE_KEY, CACHE_CHOICES = "promptCacheTtl", ("5m", "1h")
CACHE_ENVS = ("FORCE_PROMPT_CACHING_5M", "CLAUDE_CODE_PROMPT_CACHE_TTL", "ENABLE_PROMPT_CACHING_1H")
CACHE_DAYS, CACHE_MIN_REQS = 7, 500  # simulation du cache : 7 jours, au moins 500 requêtes de conversation principale
CACHE_GAIN_NEW, CACHE_GAIN_SWITCH = 0.05, 0.02  # gain minimal (part du poids total) pour poser / pour changer
DENY = "permissions.deny"


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
    if key == SKILLS_KEY:
        return f"{v * 100:g} %".replace(".", ",")  # 0.005 → « 0,5 % »
    return _k(v) if key == WIN_KEY else _n(v)


def _same(a, b) -> bool:
    return a == b and isinstance(a, bool) == isinstance(b, bool)


# ------------------------------------------------------------------------------------------ clés imbriquées (« env.X »)
def _get(data, dotted):
    """Valeur d'une clé, imbriquée ou non (« env.X », « permissions.deny ») ; ABSENT si elle manque."""
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ABSENT
        cur = cur[part]
    return cur


def _put(data, dotted, value, crees=None) -> bool:
    """Pose une clé. Les objets parents sont copiés (jamais modifiés sur place : l'état lu au départ reste intact) ; ceux
    qui manquaient sont créés et notés dans `crees` (pour les retirer au retour). False, sans rien toucher, si un parent
    n'est pas un objet JSON."""
    *path, last = dotted.split(".")
    cur = data
    for part in path:
        cur = cur.get(part, {})
        if not isinstance(cur, dict):
            return False
    cur = data
    for i, part in enumerate(path):
        if part not in cur and crees is not None and ".".join(path[:i + 1]) not in crees:
            crees.append(".".join(path[:i + 1]))
        cur[part] = dict(cur.get(part) or {})
        cur = cur[part]
    cur[last] = value
    return True


def _del(data, dotted):
    """Retire une clé (parents copiés comme dans _put)."""
    *path, last = dotted.split(".")
    cur = data
    for part in path:
        if not isinstance(cur.get(part), dict):
            return
        cur[part] = dict(cur[part])
        cur = cur[part]
    cur.pop(last, None)


def _prune(data, crees) -> list:
    """Retire les objets et listes que le cerveau avait créés et qui sont redevenus vides (les plus profonds d'abord).
    → ceux qui restent (encore remplis)."""
    left = []
    for path in sorted(crees, key=lambda p: -p.count(".")):
        v = _get(data, path)
        if isinstance(v, (dict, list)) and not v:
            _del(data, path)
        elif v is not ABSENT:
            left.append(path)
    return left


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
    for env in CACHE_ENVS:
        v = _env_value(settings, env)
        if v:
            out.append(f"⚠ {env}={v} (variable d'environnement) : c'est elle qui décide du cache ({CACHE_KEY} "
                       "et cache adaptatif sans effet)")
    models = settings.get("modelSettings")
    for model, conf in (models.items() if isinstance(models, dict) else ()):
        if isinstance(conf, dict) and WIN_KEY in conf:
            out.append(f"⚠ modelSettings.{model}.{WIN_KEY} = {_val(WIN_KEY, conf[WIN_KEY])} (écrit par /autocompact) "
                       f"l'emporte sur le réglage général pour ce modèle")
    return out


# ------------------------------------------------------------------------------------------ écriture (avec retour)
def _unset(*dotted):
    """Retire des clés de la configuration du cerveau (set_config ne sait qu'écrire)."""
    def change(cfg):
        for key in dotted:
            *path, last = key.split(".")
            cur = cfg
            for part in path:
                cur = cur.get(part) if isinstance(cur, dict) else None
            if isinstance(cur, dict):
                cur.pop(last, None)
    update_config(change)


def _section(cfg, name) -> dict:
    """Copie de eco.<name> (état d'avant / valeurs posées), modifiable sans toucher à la configuration chargée."""
    raw = (cfg.get("eco") or {}).get(name)
    data = json.loads(json.dumps(raw)) if isinstance(raw, dict) else {}
    for bucket in ("cles", "plugins", "refus"):
        if not isinstance(data.get(bucket), dict):
            data[bucket] = {}
    if name == "avant" and not isinstance(data.get("crees"), list):
        data["crees"] = []  # objets et listes créés par le cerveau dans settings.json (« env », « permissions.deny »…)
    return data


def commit(wants, force=False) -> tuple:
    """Écrit dans settings.json : wants = [("cle", nom, valeur) | ("plugin", « nom@marketplace », False)
    | ("refus", règle, True)] ; une clé peut être imbriquée (« env.X »), une règle de refus s'ajoute à permissions.deny
    sans toucher aux autres. Copie de sécurité la 1re fois ; l'état d'avant est retenu (eco.avant) pour `--annuler`. Une
    clé que l'utilisateur avait réglée n'est pas remplacée sans `force`. → (ok, {nom: valeur posée}, lignes)."""
    settings, err = read_settings()
    if err:
        return False, {}, [f"⚠ {err}"]
    path, backup = settings_path(), settings_path().with_name(BACKUP)
    cfg = load_config()
    avant, pose = _section(cfg, "avant"), _section(cfg, "pose")
    fresh = not (avant["cles"] or avant["plugins"] or avant["refus"])  # rien de posé encore : le fichier d'aujourd'hui est le « avant »
    new, posees, lignes, crees = dict(settings), {}, [], avant["crees"]
    if any(w[0] == "plugin" for w in wants) and not isinstance(new.get("enabledPlugins", {}), dict):
        return False, {}, ["⚠ enabledPlugins n'est pas un objet JSON dans settings.json : rien n'a été modifié"]
    for kind, name, value in wants:
        if kind == "refus":
            deny = _get(new, DENY)
            deny = [] if deny is ABSENT else deny
            if not isinstance(deny, list) or not isinstance(new.get("permissions", {}), dict):
                lignes.append(f"⚠ {DENY} n'est pas une liste dans settings.json : {name} gardé")
            elif name in deny:
                lignes.append(f"✓ {name} : déjà retiré (règle de refus)")
            else:
                if _get(new, DENY) is ABSENT and DENY not in crees:
                    crees.append(DENY)
                _put(new, DENY, deny + [name], crees)
                avant["refus"].setdefault(name, {"absent": True})
                pose["refus"][name] = posees[name] = True
                lignes.append(f"✓ {name} retiré du contexte (règle de refus ; avant : disponible)")
            continue
        if kind == "cle":
            bucket, cur = "cles", _get(new, name)
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
        if kind == "cle":
            if not _put(new, name, value, crees):
                lignes.append(f"⚠ {name.partition('.')[0]} n'est pas un objet JSON dans settings.json : {name} non posé")
                continue
        else:
            if "enabledPlugins" not in new and "ep_absent" not in avant:
                avant["ep_absent"] = True
            new["enabledPlugins"] = {**(new.get("enabledPlugins") or {}), name: value}
        if name not in avant[bucket]:
            avant[bucket][name] = {"absent": True} if cur is ABSENT else {"valeur": cur}
        pose[bucket][name] = value
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


def _memory_lever(settings, force=False) -> tuple:
    """Mémoire automatique de Claude Code (consignes et MEMORY.md relus à chaque requête) : coupée seulement quand tout
    ce qu'elle contient est dans le cerveau. → (à poser ?, remarque ou '', import en attente ?)."""
    theirs = _env_value(settings, MEMORY_ENV)
    if theirs and not force:
        return False, f"⚠ {MEMORY_ENV}={theirs} : déjà réglé par toi — {MEMORY_KEY} non posé", False
    try:
        from . import importer
        importer.sync()  # ce qui a changé depuis le dernier import
        left = importer.sync(dry=True)
    except Exception as exc:
        log(f"éco (mémoire auto) : {exc!r}")
        return False, "→ mémoire auto de Claude Code gardée pour l'instant : import dans le cerveau impossible", True
    if left:
        n = sum(int(x[2]) for x in left)
        return False, (f"→ mémoire auto de Claude Code gardée pour l'instant : {n} souvenir(s) pas encore importé(s) "
                       "dans le cerveau"), True
    return True, "", False


def apply_eco(out=None, win=None, force=False, cfg=None, nouveaux=False) -> tuple:
    """Pose les leviers automatiques : bashOutputMaxChars, autoCompactWindow, skillListingBudgetFraction et
    autoMemoryEnabled false (quand tout est importé dans le cerveau). `nouveaux` : seulement ceux venus après la 1re
    version (installation qui avait déjà le mode éco). Une variable d'environnement de l'utilisateur
    (BASH_MAX_OUTPUT_LENGTH, CLAUDE_CODE_AUTO_COMPACT_WINDOW, CLAUDE_CODE_DISABLE_AUTO_MEMORY) compte comme une valeur à
    lui. → (ok, {clé: valeur posée}, lignes)."""
    cfg = cfg or load_config()
    try:
        t_out, t_win = targets(cfg, out, win)
    except ValueError as exc:
        return False, {}, [f"✗ {exc}"]
    settings, err = read_settings()
    if err:
        return False, {}, [f"⚠ {err}"]
    wants, lignes = [], []
    for key, value, env in (() if nouveaux else ((OUT_KEY, t_out, "BASH_MAX_OUTPUT_LENGTH"),
                                                 (WIN_KEY, t_win, "CLAUDE_CODE_AUTO_COMPACT_WINDOW"))):
        theirs = _env_value(settings, env)
        if theirs and not force:
            lignes.append(f"⚠ {env}={theirs} : déjà réglé par toi — {key} non posé ; `--forcer` pour le poser quand même")
        else:
            wants.append(("cle", key, value))
    wants.append(("cle", SKILLS_KEY, SKILLS_FRACTION))
    mem, note, attente = _memory_lever(settings, force)
    if mem:
        wants.append(("cle", MEMORY_KEY, False))
    elif note:
        lignes.append(note)
    ok, posees, more = commit(wants, force)
    if ok:
        if not nouveaux:
            set_config("eco.applique_le", now_iso())
        if not attente:  # import en attente : la mémoire auto sera retentée au prochain démarrage
            set_config("eco.leviers", LEVIERS)
    return ok, posees, lignes + more


def _ttl(v) -> str:
    return {"5m": "5 min", "1h": "1 h"}.get(v, str(v))


def summary(posees) -> str:
    """Ce que le mode éco change, en clair (valeurs réelles)."""
    parts = []
    if OUT_KEY in posees:
        parts.append(f"sorties de commandes > {_n(posees[OUT_KEY])} caractères mises en fichier "
                     "(aperçu seul dans la conversation)")
    if WIN_KEY in posees:
        parts.append(f"conversation résumée vers {_k(posees[WIN_KEY])} tokens")
    if SKILLS_KEY in posees:
        parts.append(f"liste des skills plafonnée à {_val(SKILLS_KEY, posees[SKILLS_KEY])} du contexte "
                     "(descriptions des moins utilisées retirées, noms gardés)")
    if posees.get(MEMORY_KEY) is False:
        parts.append("mémoire auto de Claude Code coupée (le cerveau la remplace, tout y est importé)")
    if CACHE_KEY in posees:
        parts.append(f"cache gardé {_ttl(posees[CACHE_KEY])}")
    return ", ".join(parts)


def notice(posees, titre="Mode éco activé") -> str:
    """La ligne annoncée à l'utilisateur quand des réglages du mode éco viennent d'être posés."""
    return f"⚡ {titre} : {summary(posees)} · `{CMD} eco --annuler` pour revenir" if posees else ""


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def auto_start(cfg=None) -> str:
    """Au démarrage d'une session : pose le mode éco UNE fois (config eco.auto, eco.applique_le), puis, une fois aussi,
    les leviers venus avec une version plus récente (eco.leviers < LEVIERS). → la ligne à annoncer, ou ''."""
    cfg = cfg or load_config()
    eco = cfg.get("eco") or {}
    if not eco.get("auto", True):
        return ""
    if not eco.get("applique_le"):
        titre, nouveaux = "Mode éco activé", False
    elif _int(eco.get("leviers"), 1) < LEVIERS:
        titre, nouveaux = "Mode éco — nouveaux réglages", True
    else:
        return ""
    ok, posees, lignes = apply_eco(cfg=cfg, nouveaux=nouveaux)
    log("éco (démarrage) : " + " | ".join(lignes))
    return notice(posees, titre) if ok else ""


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


def _restore(only=None) -> tuple:
    """Remet l'état d'avant des réglages posés par le cerveau : tous, ou seulement `only` (noms de clés et règles de
    refus). Une valeur changée depuis par l'utilisateur reste telle quelle ; les objets et listes que le cerveau avait
    créés (« env », « permissions.deny »…) disparaissent s'ils sont redevenus vides. → (ok, lignes)."""
    settings, err = read_settings()
    if err:
        return False, [f"⚠ {err}"]
    cfg = load_config()
    avant, pose = _section(cfg, "avant"), _section(cfg, "pose")
    new, lignes, faits = dict(settings), [], []
    for name, rec in avant["cles"].items():
        if only is not None and name not in only:
            continue
        faits.append(("cles", name))
        cur = _get(new, name)
        if cur is ABSENT:
            continue
        if not _same(cur, pose["cles"].get(name, ABSENT)):
            lignes.append(f"⚠ {name} : modifié depuis (valeur {_val(name, cur)}) — laissé tel quel")
        elif rec.get("absent"):
            _del(new, name)
            lignes.append(f"✓ {name} retiré (il n'était pas réglé avant)")
        elif _put(new, name, rec.get("valeur")):
            lignes.append(f"✓ {name} remis à {_val(name, rec.get('valeur'))}")
    rules = [r for r in avant["refus"] if only is None or r in only]
    faits += [("refus", r) for r in rules]
    deny = _get(new, DENY)
    if rules and isinstance(deny, list):
        left = list(deny)
        for rule in rules:
            if rule in left:
                left.remove(rule)
                lignes.append(f"✓ {rule} de nouveau disponible (règle de refus retirée)")
        if left != deny:
            _put(new, DENY, left)
    ep = new.get("enabledPlugins")
    if only is None and avant["plugins"] and isinstance(ep, dict):
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
    avant["crees"] = _prune(new, avant["crees"])
    path = settings_path()
    if new != settings:
        try:
            if only is None and not new and avant.get("fichier_absent"):
                path.unlink()  # le fichier n'existait pas avant le mode éco
            else:
                _write(path, new)
        except OSError as exc:
            return False, [f"⚠ écriture de {path} impossible ({exc}) : rien n'a été modifié"]
    if only is not None:
        for bucket, name in faits:
            avant[bucket].pop(name, None)
            pose[bucket].pop(name, None)
        set_config("eco.avant", avant)
        set_config("eco.pose", pose)
    return True, lignes


def undo() -> tuple:
    """Remet exactement l'état d'avant (clés retirées ou valeurs d'origine rétablies, règles de refus retirées, plugins
    réactivés), efface l'enregistrement et coupe l'application automatique, la veille des plugins et le cache adaptatif.
    → (code, texte)."""
    ok, lignes = _restore()
    if not ok:
        return 1, "\n".join(lignes)
    _unset("eco.avant", "eco.pose", "eco.applique_le", "eco.annonce", "eco.plugins_vus_le", "eco.leviers", "eco.cache",
           "eco.cache_vu_le", "eco.bilan", "eco.propositions")
    set_config("eco.auto", False)
    set_config("eco.plugins_auto", False)  # sinon la veille referait demain ce qui vient d'être défait
    if not lignes:
        lignes.append("✓ rien à restaurer dans settings.json")
    lignes.append(f"✓ mode éco annulé : plus rien n'est posé tout seul (`{CMD} eco --appliquer` pour le remettre)")
    return 0, "\n".join(lignes)


def withdraw(ids) -> tuple:
    """`--retirer ID…` : enlève ce que ces propositions avaient posé (état d'avant rétabli). → (code, texte)."""
    bad = [i for i in ids if i not in PROPOSALS]
    if bad:
        return 1, f"✗ proposition inconnue : {', '.join(bad)} (au choix : {', '.join(PROPOSALS)})"
    known = (load_config().get("eco") or {}).get("propositions")
    known = known if isinstance(known, dict) else {}
    names = {n for i in ids for n in (known.get(i) if isinstance(known.get(i), list) else [])}
    if not names:
        return 0, f"✓ rien à retirer : {', '.join(ids)} pas posé(es)"
    ok, lignes = _restore(only=names)
    if not ok:
        return 1, "\n".join(lignes)
    _unset(*(f"eco.propositions.{i}" for i in ids))
    lignes.append("→ pris en compte au prochain démarrage de Claude Code")
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


_COMMAND = re.compile(rb"<command-name>/?([^<\s\\]+)</command-name>")
_TOOL_USE = re.compile(rb'"type":\s*"tool_use",\s*(?:"id":\s*"[^"]*",\s*)?"name":\s*"([^"]+)"')
_SCANS = {}  # une seule lecture des transcripts par commande (et par nombre de jours)


def _refs_in(raw, refs):
    """Une ligne d'assistant qui appelle Skill ou un agent : ajoute à `refs` la skill (input.skill) ou l'agent
    (input.subagent_type) appelé."""
    try:
        o = json.loads(raw)
    except ValueError:
        return
    msg = o.get("message") if isinstance(o, dict) else None
    blocks = msg.get("content") if isinstance(msg, dict) else None
    for b in blocks if isinstance(blocks, list) else ():
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        name, inp = b.get("name"), b.get("input")
        inp = inp if isinstance(inp, dict) else {}
        ref = inp.get("skill") if name == "Skill" else inp.get("subagent_type") if name in ("Task", "Agent") else None
        if ref:
            refs.add(str(ref))


def _attachment(raw):
    try:
        o = json.loads(raw)
    except ValueError:
        return {}
    a = o.get("attachment") if isinstance(o, dict) else None
    return a if isinstance(a, dict) else {}


def _deferred_in(a, names):
    """Annonce d'outils différés (deferred_tools_delta) : met à jour l'ensemble `names` des outils annoncés."""
    for key in ("removedNames", "addedNames", "readdedNames"):
        vals = a.get(key)
        for n in vals if isinstance(vals, list) else ():
            if isinstance(n, str):
                (names.discard if key == "removedNames" else names.add)(n)


def _scan_all(days=UNUSED_DAYS) -> dict:
    """Une seule lecture des transcripts des `days` derniers jours (gardée pour les appels suivants) → {"tools": outils
    appelés, "refs": skills et agents appelés, "commands": commandes tapées par l'utilisateur, "listing": dernière liste
    de skills de la conversation principale, "deferred": outils différés annoncés dans la dernière session principale}."""
    if days in _SCANS:
        return _SCANS[days]
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
    tools, refs, commands = set(), set(), set()
    listing, deferred = None, None
    for _, f in files:
        main = "subagents" not in f.parts
        try:
            fh = open(f, "rb")
        except OSError:
            continue
        found, names = None, None
        with fh:
            for raw in fh:
                if b'"tool_use"' in raw:
                    tools.update(h.group(1).decode("utf-8", "replace") for h in _TOOL_USE.finditer(raw))
                    if b'"Skill"' in raw or b"subagent_type" in raw:
                        _refs_in(raw, refs)
                if b"<command-name>/" in raw:  # commande tapée par l'utilisateur (« /plugin:commande »)
                    commands.update(h.group(1).decode("utf-8", "replace") for h in _COMMAND.finditer(raw))
                if not main:
                    continue
                if listing is None and b'"skill_listing"' in raw:
                    a = _attachment(raw)
                    if a.get("type") == "skill_listing" and isinstance(a.get("content"), str) \
                            and (a.get("isInitial") is not False or found is None):
                        found = a["content"]
                if deferred is None and b'"deferred_tools_delta"' in raw:
                    a = _attachment(raw)
                    if a.get("type") == "deferred_tools_delta":
                        names = set() if names is None else names
                        _deferred_in(a, names)
        if listing is None and found is not None:
            listing = found
        if deferred is None and names is not None:
            deferred = names
    res = {"tools": tools, "refs": refs, "commands": commands, "listing": listing or "",
           "deferred": sorted(deferred or ())}
    _SCANS[days] = res
    return res


def _scan(names, days=UNUSED_DAYS):
    """→ (plugins utilisés parmi `names` — et « anthropic-skills » si une skill de claude.ai a servi —, dernière liste
    de skills vue). Utilisé : une de ses skills, un de ses agents, une de ses commandes ou un de ses outils MCP a servi."""
    s = _scan_all(days)
    used = set()
    for n in set(names) | {CLAUDE_AI}:
        pre = (f"mcp__plugin_{n}_", f"mcp__plugin_{re.sub('[^A-Za-z0-9_-]', '_', n)}_")
        if any(r.startswith(f"{n}:") for r in s["refs"] | s["commands"]) or any(t.startswith(pre) for t in s["tools"]):
            used.add(n)
    return used, s["listing"]


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
    _announce(line)
    return line


def _announce(line):
    """Garde une annonce pour le prochain démarrage (montrée une fois), à la suite de celles qui attendent déjà."""
    def change(cfg):
        eco = cfg.setdefault("eco", {})
        old = eco.get("annonce") if isinstance(eco.get("annonce"), str) else ""
        if line not in old.split("\n"):
            eco["annonce"] = f"{old}\n{line}" if old else line
    if line:
        update_config(change)


def take_annonce(cfg=None) -> str:
    """Les annonces laissées par les tâches de fond (plugins, cache) : montrées une seule fois, au démarrage suivant."""
    if not ((cfg or load_config()).get("eco") or {}).get("annonce"):
        return ""
    taken = []

    def change(c):  # relue sous verrou : une annonce arrivée entre-temps part avec les autres
        eco = c.get("eco")
        taken.append(eco.pop("annonce", None) if isinstance(eco, dict) else None)
    update_config(change)
    return taken[0] if taken and isinstance(taken[0], str) else ""


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


# ------------------------------------------------------------------------------------------ sur accord : propositions
PROPOSALS = {
    "outils": "outils intégrés jamais utilisés depuis 30 j retirés du contexte (règles de refus)",
    "connecteurs": "connecteurs (serveurs MCP) jamais utilisés depuis 30 j retirés du contexte (règles de refus)",
    "git": "consignes git et instantané git status retirés du contexte (includeGitInstructions false)",
    "effort": "effort plafonné à « high » (maxEffortLevel) : moins de tokens de sortie, les plus chers",
    "lecture": "lecture de fichier plafonnée à 12 000 tokens (au-delà : Read avec offset/limit)",
    "sous-agents": "sous-agents sur Sonnet (CLAUDE_CODE_SUBAGENT_MODEL) : ménage le quota, pas le contexte",
}
# outils chargés d'emblée qu'une règle de refus retire du contexte → tokens de leur description (estimés)
TOOL_WEIGHTS = {"Workflow": 1300, "ScheduleWakeup": 1000, "ReportFindings": 550, "SuggestPluginInstall": 500,
                "SearchPlugins": 400, "SuggestSkills": 350, "mcp__visualize": 700}
KEEP_SERVERS = ("ccd_", "plugin_cerveau", "Claude_Browser", "terminal", "visualize")  # jamais proposés
GIT_TOKENS = 800  # consignes git + instantané git status (0,8 à 1,5 k selon le dépôt)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")


def _server(s) -> str:
    return s[:8] if _UUID.match(s) else s


def proposals(settings=None, days=UNUSED_DAYS) -> list:
    """Leviers posés seulement sur accord de l'utilisateur, avec ce qu'il reste à poser → [(id, wants, tokens de moins
    à chaque requête ou None, détail)]. Rien pour un levier déjà posé ou réglé par l'utilisateur."""
    if settings is None:
        settings, err = read_settings()
        if err:
            return []
    scan = _scan_all(days)
    used = scan["tools"]
    deny = _get(settings, DENY)
    deny = deny if isinstance(deny, list) else []
    out = []
    rules = [r for r in TOOL_WEIGHTS if r not in deny and not any(t == r or t.startswith(f"{r}__") for t in used)]
    if rules:
        out.append(("outils", [("refus", r, True) for r in rules], sum(TOOL_WEIGHTS[r] for r in rules),
                    ", ".join(rules)))
    servers = {}
    for name in scan["deferred"]:
        server = name[5:].partition("__")[0] if name.startswith("mcp__") else ""
        if server and not server.startswith(KEEP_SERVERS) and f"mcp__{server}" not in deny:
            servers.setdefault(server, []).append(name)
    servers = {s: v for s, v in servers.items() if not any(t.startswith(f"mcp__{s}__") for t in used)}
    if servers:
        tok = sum(len(n) + 1 for v in servers.values() for n in v) / CHARS_PER_TOKEN
        detail = ", ".join(f"{_server(s)} ({len(v)} outils)"
                           for s, v in sorted(servers.items(), key=lambda x: (-len(x[1]), x[0])))
        out.append(("connecteurs", [("refus", f"mcp__{s}", True) for s in sorted(servers)], tok, detail))
    for pid, key, value, gain in (("git", "includeGitInstructions", False, GIT_TOKENS),
                                  ("effort", "maxEffortLevel", "high", None),
                                  ("lecture", "env.CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS", "12000", None),
                                  ("sous-agents", "env.CLAUDE_CODE_SUBAGENT_MODEL", "sonnet", None)):
        if _get(settings, key) is ABSENT and not (key.startswith("env.") and os.environ.get(key[4:])):
            out.append((pid, [("cle", key, value)], gain, PROPOSALS[pid]))
    return out


def pose_proposals(ids) -> tuple:
    """`--poser ID…` (après accord de l'utilisateur) : pose ces leviers, avec retour (`--retirer ID…`). → (code, texte)."""
    ids = list(dict.fromkeys(ids))
    bad = [i for i in ids if i not in PROPOSALS]
    if bad:
        return 1, f"✗ proposition inconnue : {', '.join(bad)} (au choix : {', '.join(PROPOSALS)})"
    settings, err = read_settings()
    if err:
        return 1, f"⚠ {err}"
    avail = {pid: wants for pid, wants, _, _ in proposals(settings)}
    wants, owner, lignes = [], {}, []
    for i in ids:
        if i not in avail:
            lignes.append(f"✓ {i} : rien à poser (déjà posé, réglé par toi, ou plus rien d'inutilisé)")
        for w in avail.get(i, ()):
            wants.append(w)
            owner[w[1]] = i
    ok, posees, more = commit(wants)
    lignes += more
    known = (load_config().get("eco") or {}).get("propositions")
    known = known if isinstance(known, dict) else {}
    done = []
    for i in ids:
        names = {n for n in posees if owner.get(n) == i}
        if names:
            old = known.get(i) if isinstance(known.get(i), list) else []
            set_config(f"eco.propositions.{i}", sorted(set(old) | names))
            done.append(i)
    if done:
        lignes.append(f"→ pris en compte au prochain démarrage de Claude Code · retour : `{CMD} eco --retirer {' '.join(done)}`")
    return (0 if ok else 1), "\n".join(lignes)


# ------------------------------------------------------------------------------------------ cache adaptatif
def _pct(x) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def cache_auto() -> str:
    """Cache adaptatif (eco.cache « auto », une fois par jour en arrière-plan) : simule un cache de 5 min et de 1 h sur
    les pauses réelles des 7 derniers jours (`tokens.weigh`) et pose `promptCacheTtl` quand le gain est net (5 % du poids
    total pour le poser, 2 % pour changer une valeur que le cerveau avait posée). Jamais sur une valeur de l'utilisateur,
    ni quand une variable d'environnement du cache est réglée. → l'annonce (gardée pour le prochain démarrage), ou ''."""
    set_config("eco.cache_vu_le", now_iso())
    cfg = load_config()
    eco = cfg.get("eco") or {}
    if not eco.get("auto", True) or (eco.get("cache") or "auto") != "auto":
        return ""
    settings, err = read_settings()
    if err:
        log(f"éco (cache) : {err}")
        return ""
    cur = _get(settings, CACHE_KEY)
    mine = cur is not ABSENT and _same(_section(cfg, "pose")["cles"].get(CACHE_KEY, ABSENT), cur)
    if any(_env_value(settings, e) for e in CACHE_ENVS) or (cur is not ABSENT and not mine):
        return ""
    from . import tokens
    b = tokens.weigh(CACHE_DAYS * 24)
    sim, total = b.get("ttl") or {}, b.get("total") or 0
    if (sim.get("reqs") or 0) < CACHE_MIN_REQS or not total or not all(c in sim for c in CACHE_CHOICES):
        return ""
    ref = cur if cur in CACHE_CHOICES else sim.get("regime") if sim.get("regime") in CACHE_CHOICES else "1h"
    best = min(CACHE_CHOICES, key=lambda c: (sim[c], c != ref))
    gain = (sim[ref] - sim[best]) / total
    set_config("eco.bilan", {"le": now_iso(), "regime": ref, "meilleur": best, "gain": round(gain, 4),
                             "fenetre": b.get("fenetre")})
    if best == ref or gain < (CACHE_GAIN_SWITCH if mine else CACHE_GAIN_NEW):
        return ""
    ok, posees, lignes = commit([("cle", CACHE_KEY, best)])
    if not ok or CACHE_KEY not in posees:
        log("éco (cache) : " + " | ".join(lignes))
        return ""
    line = (f"⚡ Mode éco : cache gardé {_ttl(best)} (simulé sur tes pauses des {CACHE_DAYS} derniers jours : "
            f"−{_pct(gain)} du poids des tokens) · retour : `{CMD} eco --cache off`")
    _announce(line)
    return line


def _cache_line(eco, settings, waiting=False) -> str:
    """La ligne « cache » de `brain eco` ; `waiting` : dire quand la simulation manque encore de requêtes."""
    cur = _get(settings, CACHE_KEY)
    head = f"  {CACHE_KEY} : " + ("non réglé (Claude Code : 1 h pour la conversation, 5 min pour le reste)"
                                 if cur is ABSENT else _ttl(cur))
    mode = eco.get("cache") or "auto"
    envs = [e for e in CACHE_ENVS if _env_value(settings, e)]
    mine = cur is not ABSENT and _same(((eco.get("pose") or {}).get("cles") or {}).get(CACHE_KEY, ABSENT), cur)
    if envs:
        return head + f" · réglé par variable d'environnement ({', '.join(envs)}) : cache adaptatif en pause"
    if mode == "off":
        return head + f" · cache adaptatif coupé (`{CMD} eco --cache auto` pour le reprendre)"
    if mode in CACHE_CHOICES:
        return head + f" · fixé par toi (`{CMD} eco --cache auto` pour le choix automatique)"
    if not eco.get("auto", True):
        return head + " · cache adaptatif en pause (mode éco annulé)"
    if cur is not ABSENT and not mine:
        return head + " · réglé par toi, gardé (cache adaptatif en pause)"
    b = eco.get("bilan") if isinstance(eco.get("bilan"), dict) else None
    if not b:
        return head + f" · cache adaptatif : simulation chaque jour sur tes pauses des {CACHE_DAYS} derniers jours" + (
            f" — pas encore assez de requêtes (≥ {CACHE_MIN_REQS} sur {CACHE_DAYS} jours)" if waiting else "")
    try:
        g = float(b.get("gain") or 0)
    except (TypeError, ValueError):
        g = 0.0
    if b.get("meilleur") == b.get("regime"):
        verdict = f"{_ttl(b.get('regime'))} est le meilleur"
    elif cur is not ABSENT and _same(cur, b.get("meilleur")):
        verdict = f"{_ttl(cur)} posé, −{_pct(g)} du poids des tokens"
    else:
        verdict = f"{_ttl(b.get('meilleur'))} ferait gagner {_pct(g)} (posé à partir de {CACHE_GAIN_NEW * 100:.0f} %)"
    return head + f" · cache adaptatif, simulé le {str(b.get('le'))[:10]} sur {CACHE_DAYS} j : {verdict}"


def set_cache(mode) -> tuple:
    """`--cache auto|5m|1h|off` → (code, texte). auto : cache adaptatif (par défaut) ; 5m / 1h : valeur fixée par
    l'utilisateur ; off : cache adaptatif coupé et état d'avant rétabli."""
    settings, err = read_settings()
    if err:
        return 1, f"⚠ {err}"
    envs = [f"{e}={_env_value(settings, e)}" for e in CACHE_ENVS if _env_value(settings, e)]
    lignes = [f"⚠ {', '.join(envs)} (variable d'environnement) : c'est elle qui décide du cache"] if envs else []
    if mode in CACHE_CHOICES:
        ok, _, more = commit([("cle", CACHE_KEY, mode)], force=True)
        if not ok:
            return 1, "\n".join(lignes + more)
        set_config("eco.cache", mode)
        return 0, "\n".join(lignes + more + [f"✓ cache fixé à {_ttl(mode)} : plus de choix automatique "
                                             f"(`{CMD} eco --cache auto` pour le reprendre)"])
    if mode == "off":
        ok, more = _restore(only={CACHE_KEY})
        if not ok:
            return 1, "\n".join(more)
        set_config("eco.cache", "off")
        _unset("eco.bilan")
        return 0, "\n".join(more + [f"✓ cache adaptatif coupé (`{CMD} eco --cache auto` pour le reprendre)"])
    set_config("eco.cache", "auto")
    eco = load_config().get("eco") or {}
    if not eco.get("auto", True):
        return 0, "\n".join(lignes + [f"⚠ mode éco annulé : le cache adaptatif reprendra avec `{CMD} eco --appliquer`"])
    note = cache_auto()
    settings, _ = read_settings()
    tail = _cache_line(load_config().get("eco") or {}, settings or {}, waiting=not note).strip()
    return 0, "\n".join(lignes + ([note] if note else []) + [f"✓ cache adaptatif actif · {tail}"])


# ------------------------------------------------------------------------------------------ état et commande
def status(cfg=None) -> str:
    """`brain eco` sans option : réglages actuels, ce que le mode éco poserait, ce qui l'emporte, plugins inutilisés,
    leviers sur accord avec leur gain estimé."""
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
            (WIN_KEY, t_win, "fenêtre du modèle, ≈ 967 k pour 1 M", "conversation résumée plus tôt"),
            (SKILLS_KEY, SKILLS_FRACTION, "1 %", "liste des skills plafonnée : au-delà, descriptions des moins "
                                                "utilisées retirées, noms gardés"),
            (MEMORY_KEY, False, "true", "mémoire auto de Claude Code coupée, le cerveau la remplace ; posé quand tout "
                                        "y est importé")):
        cur = _get(settings, key)
        if cur is ABSENT:
            L.append(f"  {key} : non réglé (Claude Code : {default}) → éco : {_val(key, target)} — {what}")
        elif _same(cur, target) or _same(cur, mine.get(key, ABSENT)):
            L.append(f"  {key} : {_val(key, cur)} ✓ ({what})")
        else:
            L.append(f"  {key} : {_val(key, cur)} — réglé par toi, gardé (éco : {_val(key, target)} ; `--forcer` pour le remplacer)")
    L.append(_cache_line(eco, settings))
    win = (eco.get("bilan") or {}).get("fenetre") if isinstance(eco.get("bilan"), dict) else None
    if isinstance(win, int) and not isinstance(win, bool) and abs(win - t_win) >= 20000:
        L.append(f"  → d'après tes compactions, la fenêtre de résumé la moins chère est ≈ {_k(win)} "
                 f"(`{CMD} eco --fenetre {win}`)")
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
    props = proposals(settings)
    posed = eco.get("propositions") if isinstance(eco.get("propositions"), dict) else {}
    if props or posed:
        L.append("Sur accord de l'utilisateur seulement (gains estimés) :")
        for pid, _, gain, detail in props:
            g = f" — ≈ {_tok(gain)} tokens de moins dans chaque requête" if gain else ""
            more = f" : {detail}" if pid in ("outils", "connecteurs") else ""
            L.append(f"  - {pid}{g} · {PROPOSALS[pid]}{more}")
        L += [f"  ✓ {pid} posé · {PROPOSALS[pid]} (`--retirer {pid}`)" for pid in posed if pid in PROPOSALS]
        if props:
            L.append(f"→ `{CMD} eco --poser {' '.join(p[0] for p in props)}` (demande d'abord à l'utilisateur ; "
                     f"retour : `--retirer ID…`)")
    L.append(f"→ `{CMD} eco --annuler` pour revenir" if eco.get("applique_le")
             else f"→ `{CMD} eco --appliquer` pour l'activer (sauvegarde + retour possible)")
    return "\n".join(L)


def run(appliquer=False, annuler=False, forcer=False, sortie=None, fenetre=None, desactiver=None, plugins_auto=None,
        poser=None, retirer=None, cache=None) -> tuple:
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
    for given, fn in ((desactiver, disable), (plugins_auto, watch_plugins), (poser, pose_proposals),
                      (retirer, withdraw), (cache, set_cache)):
        if given:
            c, text = fn(given)
            L.append(text)
            code = code or c
    return code, "\n".join(L) if L else status()
