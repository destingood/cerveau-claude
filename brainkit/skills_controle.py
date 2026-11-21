"""Skills, contrôle et création : ce qui empêche une skill de se déclencher seule ou de bien marcher (`brain skill
check`, la ligne du démarrage), et le squelette d'une nouvelle skill (`brain skill new`).

Découpé de skills.py (étape 8 du plan) sans rien changer ; chargé au démarrage (notice) et par les commandes, jamais
par un message."""
from __future__ import annotations

import re
from pathlib import Path

from .common import fold
from .skills import NAME_RE, NEG_RE, SKILLS_DIR, TRIGGERS_KEY, index, match, quoted, split_desc


# ------------------------------------------------------------------------------------------ contrôle
def check(skills=None, exclude=(), routes=True, only=None) -> list:
    """Problèmes qui empêchent une skill de se déclencher seule ou de bien marcher → [(niveau, skill, message)]. Skill de
    plugin : seulement ses déclencheurs (son SKILL.md n'est pas à nous ; compte claude.ai : seulement ceux ajoutés) ;
    écartée du réflexe (`exclude`) : rien. `routes` : vérifier aussi que chaque déclencheur mène à sa skill (une
    recherche par déclencheur) ; `only` : noms des skills à contrôler, les autres ne servant que de concurrentes."""
    skills = index() if skills is None else skills
    exclude = set(exclude)
    out = []
    for s in skills:
        name, path, desc = s["name"], Path(s["path"]), s["description"]
        trig = " ".join(str((s.get("meta") or {}).get(TRIGGERS_KEY) or "").split())
        folder = path.parent.name
        if only is not None and name not in only:
            continue
        if s.get("plugin"):
            if name in exclude:
                continue
            ours = not s.get("kind")  # installée ici : ses propres déclencheurs comptent aussi
            if not s["triggers"] and ours:
                out.append(("ℹ️", name, f"skill du plugin {s['plugin']} sans déclencheur : le réflexe ne marche qu'aux "
                                        f"mots de sa description — en ajouter : `brain skill trig {name} \"…\"`"))
            own = set() if ours else set(quoted(split_desc(desc)[0]) + quoted(split_desc(trig)[0]))
            for v in s.get("vague", []):
                if v not in own:
                    out.append(("ℹ️", name, f"déclencheur « {v} » trop vague (un seul mot court) : ignoré par le réflexe"))
            for p in s["triggers"]:
                if not routes or not (ours or p.get("added")):
                    continue
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
        elif len(desc) > 250:
            out.append(("ℹ️", name, f"description de {len(desc)} car. : le mode éco la coupe à 250 dans la liste des skills "
                                    "(skillListingMaxDescChars) ; les phrases « … » peuvent passer dans l'en-tête "
                                    "metadata.triggers, que le réflexe lit aussi"))
        elif len(desc) < 80:
            out.append(("⚠️", name, "description très courte : dire QUAND l'utiliser et avec quels mots"))
        if not s["triggers"]:
            out.append(("⚠️", name, "aucun déclencheur « … » dans la description ni dans metadata.triggers : le réflexe "
                                    "ne marche qu'aux mots-clés"))
        for v in s.get("vague", []):
            if not v.startswith("/"):
                out.append(("ℹ️", name, f"déclencheur « {v} » trop vague (un seul mot court) : ignoré par le réflexe"))
        if not NEG_RE.search(f"{desc} {trig}"):
            out.append(("ℹ️", name, "pas de « Ne pas utiliser… » : utile pour éviter les déclenchements à tort"))
        if s.get("lines", 0) > 500:
            out.append(("⚠️", name, f"SKILL.md de {s['lines']} lignes (> 500) : déplacer le détail dans des fichiers liés"))
        for link in s.get("links", []):
            if re.match(r"^[a-z]+:", link):
                continue
            if not (path.parent / link).exists():
                out.append(("❌", name, f"lien cassé : {link}"))
        for p in s["triggers"] if routes else ():  # chaque déclencheur doit mener à sa propre skill
            got = match(p["text"], skills, exclude=exclude)
            if not got or got[0]["name"] != name:
                other = got[0]["name"] if got else "aucune skill"
                out.append(("⚠️", name, f"le déclencheur « {p['text']} » mène à {other}"))
    seen = {}
    for s in skills:
        if s["name"] in exclude:
            continue
        for p in s["triggers"]:
            if s.get("kind") and not p.get("added"):  # déclencheurs anglais d'un plugin du compte : pas à nous
                continue
            key = fold(p["text"])
            if key in seen and seen[key] != s["name"] and (only is None or s["name"] in only):
                out.append(("⚠️", s["name"], f"déclencheur « {p['text']} » partagé avec {seen[key]}"))
            seen.setdefault(key, s["name"])
    return out


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
