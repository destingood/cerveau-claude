"""Réglages du cerveau (`brain config clé valeur`) : la clé doit exister et la valeur convenir, avant toute écriture.

Une valeur fausse (« abc » pour un nombre, une faute dans la clé) n'est plus écrite : avant, elle cassait l'injection du
démarrage à la session suivante. Les clés connues : celles de common.DEFAULT_CONFIG (leur type est celui du défaut,
leurs bornes dans common.CONFIG_RANGES), quelques réglages documentés hors des défauts (EXTRA), et des sections libres
(OPEN : déclencheurs ajoutés, modèles par agent, état tenu par le cerveau lui-même). Chargé seulement par `brain config`
et `brain doctor` : aucun hook ne le lit."""
from __future__ import annotations

import difflib
import json

from .common import CONFIG_FORMS, DEFAULT_CONFIG, config_kind, config_value

# Réglages documentés hors des défauts → une valeur qui donne leur type (comme dans DEFAULT_CONFIG).
EXTRA = {
    "auto.enabled": True,  # veille automatique (`brain auto`)
    "commun.repo": "",  # dépôt du cerveau commun, « proprietaire/depot » ou adresse
    "publish.owner": "", "publish.repo": "", "publish.dir": None,  # `brain publish` (réglages locaux)
    "plugin.garder_classique": False,  # garder le cerveau classique aux commandes
    "selfupdate.source": None,  # arbre de développement de `brain self-update`
    "compact.filtres": [], "compact.oublies": [],  # filtres de sorties appris / commandes oubliées
    # anciens budgets en caractères (prioritaires s'ils sont là) : common.budget_chars
    "inject.max_chars": 0, "inject.index_chars": 0, "inject.index_chars_project": 0, "inject.project_chars": 0,
    "inject.digest_chars": 0, "inject.compact_recall_chars": 0,
}
EXTRA_FORMS = {"inject.habit_tip": (bool, str), "sujets": (list, str)}  # rappel d'habitude : off, ou son texte
# Sections libres : n'importe quelle clé dessous (déclencheurs, modèles par agent, empreintes, état du cerveau).
OPEN = ("skills.triggers", "outils.triggers", "delegation.modeles", "echange.scripts", "echange.acceptees",
        "eco.propositions", "garde", "plugin", "selfupdate", "commun", "publish", "auto")
# État tenu par le cerveau dans des sections réglables (dates du dernier passage, ce que le mode éco a posé…).
STATE = ("eco.avant", "eco.pose", "eco.applique_le", "eco.leviers", "eco.propose", "eco.plugins_vus_le",
         "eco.cache_vu_le", "eco.bilan", "eco.annonce")
CHOICES = {"recall.neurone": ("auto", "off"), "skills.paste": ("auto", "propose", "off"),
           "eco.cache": ("auto", "5m", "1h", "off"), "delegation.mode": ("auto", "max", "conseil", "off"),
           "echange.envoi": (None, "oui", "non"), "echange.reception": ("oui", "non"),
           "echange.declencheurs": ("oui", "non")}
GROUPES = ("memoire", "wiki", "boutique", "tout", "tous", "all")
EXAMPLES = {"mcp.groupes": '\'["wiki", "boutique"]\'', "skills.auto": '\'["ma-skill"]\'', "style": "off",
            "skills.plugins": "false", "sujets": '\'["thé", "boutique"]\'', "wiki.path": '"D:\\\\Wiki"',
            "backup.dir": '"D:\\\\Sauvegardes"', "vault.path": '"D:\\\\Coffre"', "commun.repo": "proprietaire/depot"}


def _flat(d, prefix=""):
    for key, val in d.items():
        if isinstance(val, dict) and val:
            yield from _flat(val, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", val


def known_keys() -> list:
    return sorted({k for k, _ in _flat(DEFAULT_CONFIG)} | set(EXTRA) | set(EXTRA_FORMS)
                  | {k for k in DEFAULT_CONFIG if isinstance(DEFAULT_CONFIG[k], dict) and DEFAULT_CONFIG[k]})


def _default(key):
    """→ (trouvé, défaut) d'une clé à points dans DEFAULT_CONFIG."""
    cur = DEFAULT_CONFIG
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _open(key) -> bool:
    return any(key == o or key.startswith(o + ".") for o in OPEN) or key in STATE


def known(key) -> bool:
    return _default(key)[0] or key in EXTRA or key in EXTRA_FORMS or _open(key)


def example(key, default) -> str:
    if key in EXAMPLES:
        return EXAMPLES[key]
    if key in CHOICES:
        return str(next(c for c in CHOICES[key] if c is not None))
    if isinstance(default, bool):
        return "false" if default else "true"
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        return json.dumps(default)
    if isinstance(default, list):
        return "'" + json.dumps(default or ["…"], ensure_ascii=False) + "'"
    if isinstance(default, dict):
        return "'{…}'"
    return '"…"'


def unknown(key) -> str:
    section = key.split(".")[0]
    if section in DEFAULT_CONFIG and isinstance(DEFAULT_CONFIG[section], dict) and DEFAULT_CONFIG[section]:
        near = difflib.get_close_matches(key, [k for k in known_keys() if k.startswith(section + ".")], n=3, cutoff=0.7)
        hint = (f" — voulais-tu : {', '.join(near)} ?" if near else
                f" — clés de « {section} » : " + ", ".join(k.split(".", 1)[1] for k in known_keys()
                                                         if k.startswith(section + ".")))
    else:
        near = difflib.get_close_matches(key, known_keys(), n=3, cutoff=0.6)
        hint = f" — voulais-tu : {', '.join(near)} ?" if near else ""
    return f"clé inconnue : {key}{hint} (toutes les clés et leurs valeurs : `brain config`) ; rien n'est écrit"


def _refuse(key, value, want, default) -> str:
    shown = json.dumps(value, ensure_ascii=False)
    return (f"valeur refusée pour {key} : {shown[:60]} — {want} attendu, ex. `brain config {key} {example(key, default)}` "
            "; rien n'est écrit")


def _split(raw, value):
    """Texte simple (pas du JSON) pour une liste : « a, b » → ["a", "b"]."""
    if isinstance(value, str) and raw is not None and value == raw and "," in value:
        return [x.strip() for x in value.split(",") if x.strip()]
    return value


def check(key, value, raw=None):
    """→ (valeur à écrire, None) si la clé existe et que la valeur lui convient, sinon (None, message en français).
    `raw` : le texte tapé, quand la valeur n'était pas du JSON (pour découper une liste « a, b »)."""
    key = str(key or "").strip()
    if not key or any(not part for part in key.split(".")):
        return None, f"clé illisible : « {key} » (ex. recall.enabled, mcp.groupes)"
    found, default = _default(key)
    if found and isinstance(default, dict) and default:  # une section entière : chaque clé donnée est vérifiée
        if not isinstance(value, dict):
            return None, _refuse(key, value, "objet JSON (section)", default)
        out = {}
        for sub, val in value.items():
            good, err = check(f"{key}.{sub}", val)
            if err:
                return None, err
            out[sub] = good
        return out, None
    if found:
        if isinstance(default, list) and key not in CONFIG_FORMS:
            value = _split(raw, value)
        good, want = config_value(key, default, value)
        if want:
            return None, _refuse(key, value, want, default)
        if key in CHOICES and good not in CHOICES[key]:
            opts = ", ".join("null" if c is None else c for c in CHOICES[key])
            return None, _refuse(key, value, f"une de ces valeurs ({opts})", default)
        if key == "mcp.groupes":
            names = good.replace(";", ",").split(",") if isinstance(good, str) else good
            bad = [n for n in names if str(n).strip().lower() not in GROUPES]
            if bad:
                return None, _refuse(key, value, f"liste de groupes parmi {', '.join(GROUPES[:3])} ou tout", default)
        return good, None
    if key in EXTRA_FORMS:
        if not isinstance(value, EXTRA_FORMS[key]):
            return None, _refuse(key, value, "texte ou liste" if key == "sujets" else "oui/non ou texte", None)
        return value, None
    if key in EXTRA:
        good, want = config_value(key, EXTRA[key], _split(raw, value) if isinstance(EXTRA[key], list) else value)
        if want:
            return None, _refuse(key, value, want, EXTRA[key])
        return good, None
    if _open(key):
        if key.startswith(("skills.triggers.", "outils.triggers.")):  # déclencheurs : des phrases
            value = [value] if isinstance(value, str) else value
            if not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
                return None, _refuse(key, value, "liste de phrases", ["…"])
        return value, None
    return None, unknown(key)


def kind(key) -> str:
    found, default = _default(key)
    return config_kind(key, default if found else EXTRA.get(key))
