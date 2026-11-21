"""Les skills du plugin, de 33 à 18 (étape 5 du plan, §4.3 et §7.2) : des aiguillages (design, animation, composants,
web, recherche) qui lisent la bonne fiche, des descriptions courtes, et les phrases-déclencheurs du réflexe rangées
dans l'en-tête `metadata.triggers`, hors de la liste des skills que Claude Code met dans le contexte.

- disposition : les 18 skills attendues, humanizer et vercel retirées, chaque fichier des anciennes skills (fiche,
  références, scripts, licence) sous son groupe, liens des aiguillages et chemins des fiches qui existent ;
- en-têtes : descriptions de 250 caractères au plus et sans phrase « … » (sauf brain, que le réflexe ne souffle pas),
  déclencheurs dans metadata.triggers, spec-kit, rea et automaton sur demande seulement ;
- réflexe : « fais-moi un logo », « scrape ce site », chaque ancien nom de skill ou sa demande type mènent au groupe ;
  les phrases d'humanizer et de vercel mènent aux skills des plugins installés (plugins synchronisés rangés sous un
  identifiant compris) ; chaque déclencheur mène à sa skill ; un mot seul (« logo », « impeccable », « animation »)
  ne déclenche rien ; une skill sur demande est proposée en commande à taper ;
- catalogue gardé d'un message à l'autre : un SKILL.md inchangé n'est pas relu, un aiguillage modifié l'est (lui seul) ;
- corrections de l'audit : chemin du script de scrapegraph, test cité par image-to-code, déclencheurs de logo-design ;
- mode classique : les anciennes skills posées par le cerveau sont retirées, les nouvelles posées avec leurs fiches.

Lancement : python tests/test_skills_regroupees.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-skills-regroupees-test-"))
CODE = Path(__file__).resolve().parent.parent
SKILLS = CODE / "skills"
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK"):
    os.environ.pop(k, None)
os.environ.update(BRAIN_HOME=str(TMP / "brain"), CLAUDE_CONFIG_DIR=str(TMP / "claude"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), PYTHONDONTWRITEBYTECODE="1")
for d in ("brain", "claude/plugins", "home"):
    (TMP / d).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(CODE))

from brainkit import skills  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def section(fn):
    """Une partie qui plante (ancienne disposition, fichier absent) compte comme un échec, sans arrêter les autres."""
    try:
        fn()
    except Exception as exc:
        check(False, f"{fn.__name__} : exception", "".join(traceback.format_exception_only(type(exc), exc)).strip())
    return fn


GROUPS = {"design": ["taste-skill", "impeccable", "design-md", "skillui", "image-to-code"],
          "animation": ["motion-design", "animejs", "emil-kowalski"],
          "composants": ["kokonutui", "uiverse", "bklit-ui"],
          "web": ["agent-browser", "playwright", "scrapegraph", "agent-reach", "reverse-api-engineer"],
          "recherche": ["recherche", "perplexity"]}
KEPT = ["brain", "obsidian", "ecommerce", "fortnite", "carriere-commerciale", "youtube", "replica", "securite",
        "spec-kit", "rea", "automaton", "logo-design", "public-apis"]
MANUAL = {"spec-kit", "rea", "automaton"}
EXPECTED = set(GROUPS) | set(KEPT)
GROUP_OF = {old: g for g, olds in GROUPS.items() for old in olds}
# Fichiers des anciennes skills regroupées (git ls-tree de d695ddb, cerveau 8.27.0) : SKILL.md devient fiche.md.
OLD_FILES = """agent-browser/SKILL.md agent-reach/SKILL.md animejs/SKILL.md bklit-ui/SKILL.md design-md/SKILL.md
emil-kowalski/SKILL.md image-to-code/LICENSE image-to-code/SKILL.md image-to-code/references/01-image-d-abord.md
image-to-code/references/02-mise-en-page.md image-to-code/references/03-extraction-et-code.md
image-to-code/references/04-anti-slop-et-finition.md impeccable/SKILL.md kokonutui/LICENSE kokonutui/SKILL.md
motion-design/SKILL.md perplexity/SKILL.md playwright/SKILL.md recherche/SKILL.md reverse-api-engineer/LICENSE
reverse-api-engineer/SKILL.md reverse-api-engineer/references/depannage.md reverse-api-engineer/references/reglages.md
reverse-api-engineer/references/sessions.md scrapegraph/SKILL.md scrapegraph/scripts/sgai.py skillui/SKILL.md
taste-skill/LICENSE taste-skill/SKILL.md uiverse/SKILL.md uiverse/scripts/galaxy.py""".split()


def head(name) -> dict:
    return skills.frontmatter((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))[0]


# ------------------------------------------------------------------ 1. disposition
@section
def disposition():
    here = {d.name for d in SKILLS.iterdir() if (d / "SKILL.md").is_file()}
    check(here == EXPECTED, "les 18 skills attendues, ni plus ni moins",
          (sorted(here - EXPECTED), sorted(EXPECTED - here)))
    check(not (SKILLS / "humanizer").exists() and not (SKILLS / "vercel").exists(),
          "skills humanizer et vercel retirées (décision E8 : leurs plugins les fournissent)")
    missing = []
    for rel in OLD_FILES:
        old, _, rest = rel.partition("/")
        new = SKILLS / GROUP_OF[old] / old / ("fiche.md" if rest == "SKILL.md" else rest)
        if not new.is_file():
            missing.append(new.relative_to(SKILLS).as_posix())
    check(not missing, f"les {len(OLD_FILES)} fichiers des anciennes skills sont sous leur groupe (fiche, références, "
          "scripts, licence)", missing)
    stray = [p.relative_to(SKILLS).as_posix() for p in SKILLS.glob("*/*/SKILL.md")]
    check(not stray, "aucun SKILL.md dans une fiche : Claude Code ne liste que les 18 skills", stray)
    nolic = [f"{g}/{o}" for o, g in GROUP_OF.items()
             if not re.search(r"licen[cs]e|\bMIT\b|Apache|d'après|officiel",
                              (SKILLS / g / o / "fiche.md").read_text(encoding="utf-8"))]
    check(not nolic, "chaque fiche garde la source et la licence de son outil", nolic)
    noorig = [f"{g}/{o}" for o, g in GROUP_OF.items()
              if "> Quand la suivre :" not in (SKILLS / g / o / "fiche.md").read_text(encoding="utf-8")]
    check(not noorig, "chaque fiche garde la description de l'ancienne skill (quand la suivre)", noorig)


@section
def aiguillages():
    for g, olds in GROUPS.items():
        meta, body = skills.frontmatter((SKILLS / g / "SKILL.md").read_text(encoding="utf-8"))
        links = set(re.findall(r"\]\(([^)\s#]+)\)", body))
        broken = sorted(link for link in links if not (SKILLS / g / link).is_file())
        unlinked = [o for o in olds if f"{o}/fiche.md" not in links]
        check(not broken and not unlinked, f"{g} : chaque fiche du groupe est citée par l'aiguillage, aucun lien cassé",
              (broken, unlinked))
        check(len(body.splitlines()) <= 40, f"{g} : aiguillage court ({len(body.splitlines())} lignes)")
    # chemins cités par les fiches qui ont des fichiers à elles (références, scripts) : ils existent
    for o, g in GROUP_OF.items():
        folder = SKILLS / g / o
        if not any((folder / d).is_dir() for d in ("references", "scripts")):
            continue
        text = (folder / "fiche.md").read_text(encoding="utf-8")
        cited = set(re.findall(r"(?<![\w.-])((?:[\w-]+/)?(?:references|scripts)/[\w.-]+\.(?:md|py))", text))
        bad = sorted(c for c in cited if not ((folder / c).is_file() or (SKILLS / g / c).is_file()))
        check(cited and not bad, f"{g}/{o} : les fichiers que cite la fiche existent ({len(cited)})", bad)


# ------------------------------------------------------------------ 2. en-têtes
LISTING = {}


@section
def entetes():
    for name in sorted(EXPECTED):
        meta = head(name)
        desc = meta.get("description", "")
        LISTING[name] = len(f"- cerveau:{name}: {desc}\n")
        check(0 < len(desc) <= 250, f"{name} : description de 250 caractères au plus ({len(desc)})")
        if name == "brain":  # le réflexe ne souffle jamais la skill du cerveau lui-même
            continue
        check(not skills.quoted(desc), f"{name} : aucune phrase-déclencheur « … » dans la description",
              skills.quoted(desc))
        trig = skills.quoted(skills.split_desc(meta.get("metadata.triggers", ""))[0])
        check(len(trig) >= 3, f"{name} : déclencheurs dans metadata.triggers ({len(trig)})")
        on_demand = meta.get("disable-model-invocation") == "true"
        check(on_demand == (name in MANUAL), f"{name} : " + ("sur demande seulement (disable-model-invocation)"
                                                             if name in MANUAL else "Claude peut la charger seul"))
    total = sum(LISTING.values())
    shown = sum(n for k, n in LISTING.items() if k not in MANUAL)
    print(f"· liste des skills du cerveau : {total} caractères pour 18 skills ({shown} pour les 15 que Claude Code "
          f"montre au modèle ; 29 000 environ pour les 33 d'avant)")
    check(len(LISTING) == 18 and total <= 5000, f"la liste des 18 skills tient en 5 000 caractères ({total})")


@section
def entete_lu():
    text = ("---\nname: essai\ndescription: \"Une phrase\n  sur deux lignes.\"\nmetadata:\n  version: \"1.0\"\n"
            "  triggers: >-\n    « fais-moi un essai » « teste\n    l'essai » Ne pas utiliser pour « essai raté ».\n"
            "allowed-tools: Read\n---\n\n# Essai\n")
    meta, body = skills.frontmatter(text)
    check(meta.get("description") == "Une phrase sur deux lignes." and meta.get("metadata.version") == "1.0"
          and meta.get("allowed-tools") == "Read" and body.startswith("\n# Essai"),
          "en-tête : metadata lue comme un dictionnaire, chaîne entre guillemets sur deux lignes", meta)
    p = TMP / "essai" / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    s = skills.parse(p)
    check([t["text"] for t in s["triggers"]] == ["fais-moi un essai", "teste l'essai"]
          and [t["text"] for t in s["neg_triggers"]] == ["essai raté"],
          "metadata.triggers : phrases et « Ne pas utiliser » lues par le réflexe", (s["triggers"], s["neg_triggers"]))
    msgs = [m for _lvl, _n, m in skills.check([s], routes=False)]
    check(not any("aucun déclencheur" in m or "Ne pas utiliser" in m for m in msgs),
          "brain skill check : déclencheurs et exclusions de metadata.triggers comptés", msgs)
    long = TMP / "longue" / "SKILL.md"
    long.parent.mkdir(parents=True, exist_ok=True)
    long.write_text("---\nname: longue\ndescription: \"À utiliser pour « préparer la tournée » des livraisons. "
                    + "Détail de la méthode. " * 12 + "Ne pas utiliser pour le reste.\"\n---\n\n# Longue\n",
                    encoding="utf-8")
    msgs = [(lvl, m) for lvl, _n, m in skills.check([skills.parse(long)], routes=False)]
    check(any(lvl == "ℹ️" and "250" in m and "metadata.triggers" in m for lvl, m in msgs),
          "brain skill check : une skill perso de plus de 250 caractères est signalée (sans erreur)", msgs)


# ------------------------------------------------------------------ 3. le réflexe
ACC = TMP / "claude" / "plugins" / "synced" / "compte"
HUMANIZER, VERCEL = "8522bbee-a491-445e-9400-615770e76ef5", "833bb33c-76b0-42dd-ac4a-913788404db2"


def installed(skills_root):
    (TMP / "claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"cerveau@cerveau": [{"scope": "user", "installPath": str(skills_root)}]}}),
        encoding="utf-8")


def synced_plugins():
    """Plugins du compte claude.ai tels que Claude Code les range : dossier nommé par un identifiant, nom dans
    .claude-plugin/plugin.json ; humanizer n'a qu'un SKILL.md à sa racine."""
    for uid, name in ((HUMANIZER, "humanizer"), (VERCEL, "vercel")):
        d = ACC / uid
        (d / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        (ACC / f"{uid}.meta.json").write_text("{}", encoding="utf-8")
    (ACC / HUMANIZER / "SKILL.md").write_text(
        "---\nname: humanizer\ndescription: \"Rewrite AI-sounding text so it reads like the writer.\"\nlicense: MIT\n"
        "metadata:\n  version: \"3.1.0\"\n---\n\n# Humanizer\n", encoding="utf-8")
    for s in ("react-best-practices", "vercel-cli", "deployments-cicd"):
        (ACC / VERCEL / "skills" / s).mkdir(parents=True, exist_ok=True)
        (ACC / VERCEL / "skills" / s / "SKILL.md").write_text(f"---\nname: {s}\ndescription: \"Vercel {s} guidance.\"\n---\n",
                                                             encoding="utf-8")
    (ACC / VERCEL / "commands").mkdir(exist_ok=True)
    (ACC / VERCEL / "commands" / "deploy.md").write_text(
        "---\ndescription: Deploy the current project to Vercel.\n---\n\n# Deploy\n", encoding="utf-8")


def top(text, cat):
    got = skills.match(text, cat)
    return (got[0]["name"], got[0]["strong"]) if got else (None, False)


ROUTES = [  # (message, skill attendue) : demandes du plan, anciens noms de skills et leurs demandes types
    ("fais-moi un logo", "cerveau:logo-design"),
    ("fais-moi un logo pour ma boutique de thé", "cerveau:logo-design"),
    ("scrape ce site", "cerveau:web"),
    ("scrape ce site et liste les prix", "cerveau:web"),
    ("ajoute un composant kokonutui sur ma page d'accueil", "cerveau:composants"),
    ("un loader uiverse pour mon thème", "cerveau:composants"),
    ("utilise bklit-ui pour ce tableau de bord", "cerveau:composants"),
    ("ajoute un graphique animé à mon dashboard", "cerveau:composants"),
    ("teste mon site avec playwright", "cerveau:web"),
    ("installe agent-browser", "cerveau:web"),
    ("installe scrapegraph", "cerveau:web"),
    ("installe agent-reach puis lis ce tweet", "cerveau:web"),
    ("reverse-api-engineer sur ce site", "cerveau:web"),
    ("transforme ce site en API", "cerveau:web"),
    ("cherche les derniers chiffres avec perplexity", "cerveau:recherche"),
    ("recherche à fond sur les pompes à chaleur", "cerveau:recherche"),
    ("utilise taste-skill pour refaire mon site", "cerveau:design"),
    ("installe impeccable", "cerveau:design"),
    ("peaufine l'interface de mon appli", "cerveau:design"),
    ("design-md pour mon projet", "cerveau:design"),
    ("je veux un site dans le style de Stripe", "cerveau:design"),
    ("lance skillui sur ce site", "cerveau:design"),
    ("image-to-code : transforme cette image en site", "cerveau:design"),
    ("motion-design : règle la durée de cette animation", "cerveau:animation"),
    ("une timeline d'animation avec anime.js", "cerveau:animation"),
    ("les skills d'emil kowalski pour ce menu", "cerveau:animation"),
    ("anime ce bouton", "cerveau:animation"),
    ("anime le logo de mon site", "cerveau:animation"),
    ("trouve une API gratuite pour la météo", "cerveau:public-apis"),
]


@section
def reflexe():
    installed(CODE)
    synced_plugins()
    cat = skills.index(None, {"plugins": True})
    names = {s["name"] for s in cat}
    check({f"cerveau:{n}" for n in EXPECTED - {"brain"}} <= names and "cerveau:brain" not in names,
          "catalogue : les 17 skills métier du plugin, jamais celle du cerveau lui-même", sorted(names))
    check({"humanizer:humanizer", "vercel:deploy", "vercel:react-best-practices", "vercel:vercel-cli"} <= names
          and not any(n.startswith((HUMANIZER, VERCEL)) for n in names),
          "plugins synchronisés sous un identifiant : nommés comme l'outil Skill, SKILL.md à la racine compris",
          sorted(names))
    for msg, want in ROUTES:
        got = top(msg, cat)
        check(got == (want, True), f"« {msg} » → {want}", got)
    for msg, want in (("humanise ce texte", "humanizer:humanizer"), ("on dirait de l'IA, ce post", "humanizer:humanizer"),
                      ("rends ce texte plus humain", "humanizer:humanizer"), ("déploie sur vercel", "vercel:deploy"),
                      ("bonnes pratiques react pour ce composant", "vercel:react-best-practices"),
                      ("optimise vercel, la facture monte", "vercel:vercel-cli")):
        got = top(msg, cat)
        check(got == (want, True), f"ancienne phrase d'humanizer ou de vercel « {msg} » → {want} (plugin installé)", got)
    for msg, never in (("c'est impeccable, merci", "cerveau:"), ("installe node", "cerveau:"),
                       ("le logo est en haut à gauche", "cerveau:logo-design"),
                       ("ma fille regarde un film d'animation", "cerveau:animation"),
                       ("on fait une animation commerciale en magasin samedi", "cerveau:animation"),
                       ("le design de la facture est simple", "cerveau:design"),
                       ("fais une base de données SQL pour les commandes", "cerveau:obsidian")):
        got = [r["name"] for r in skills.match(msg, cat) if r["name"].startswith(never)]
        check(not got, f"« {msg} » : pas de {never.rstrip(':') if never != 'cerveau:' else 'skill du cerveau'} "
              "(un mot seul ne déclenche rien)", got)
    # chaque déclencheur d'une skill du plugin mène à elle (sauf la rivalité, déjà là avant, de replica et rea)
    known = {("cerveau:replica", "reverse engineer X")}
    wrong = []
    for s in cat:
        if not s["name"].startswith("cerveau:"):
            continue
        for p in s["triggers"]:
            got = top(p["text"], cat)
            if got != (s["name"], True) and (s["name"], p["text"]) not in known:
                wrong.append(f"{s['name']} « {p['text']} » → {got[0]}")
    check(not wrong, "chaque déclencheur d'une skill du plugin mène à elle", wrong)
    # skill sur demande : proposée en commande à taper, jamais en « peut-être »
    got = skills.match("décompile cet APK", cat)
    line = skills.hint_line(got[0]) if got else ""
    check(got and got[0]["name"] == "cerveau:rea" and "`/cerveau:rea`" in line and "outil Skill" not in line,
          "skill sur demande (rea) : la commande /cerveau:rea proposée, pas l'outil Skill", line)
    rea = next(s for s in cat if s["name"] == "cerveau:rea")
    weak = skills.match("rea rea pseudocode ghidra binaire firmware", [rea], min_score=0)
    check(all(r["strong"] for r in weak), "skill sur demande : jamais soufflée en « peut-être »", weak)
    # sans les plugins Humanizer et Vercel : rien n'est soufflé à leur place
    shutil.rmtree(TMP / "claude" / "plugins" / "synced")
    cat2 = skills.index(None, {"plugins": True})
    check(top("humanise ce texte", cat2)[0] is None and top("déploie sur vercel", cat2)[0] is None,
          "sans les plugins Humanizer et Vercel : rien de soufflé", (top("humanise ce texte", cat2),
                                                                     top("déploie sur vercel", cat2)))
    probs = [m for lvl, n, m in skills.check(cat2, only={s["name"] for s in cat2 if s["name"].startswith("cerveau:")})
             if lvl in ("❌", "⚠️") and "reverse engineer X" not in m]
    check(not probs, "brain skill check : aucune skill du plugin à réparer", probs)


@section
def catalogue_garde():
    """Copie du plugin : un aiguillage modifié est relu (lui seul), un SKILL.md inchangé ne l'est pas."""
    copy = TMP / "plugin"
    shutil.copytree(SKILLS, copy / "skills")
    installed(copy)
    kc = {"plugins": ["cerveau"]}
    skills.index(None, kc)
    parsed, real = [], skills.parse

    def counted(path, *a, **k):
        parsed.append(Path(path).parent.name)
        return real(path, *a, **k)

    skills.parse = counted
    try:
        skills.index(None, kc)
        again = list(parsed)
        p = copy / "skills" / "composants" / "SKILL.md"
        text = p.read_text(encoding="utf-8").replace("« kokonut »", "« kokonut » « composant qui brille »", 1)
        p.write_text(text, encoding="utf-8")
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns - 5 * 10 ** 9))  # assez ancien : lu sans précaution
        parsed.clear()
        cat = skills.index(None, kc)
    finally:
        skills.parse = real
    check(not again, "catalogue : aucun SKILL.md relu tant que rien ne change", again)
    check(parsed == ["composants"] and top("un composant qui brille", cat) == ("cerveau:composants", True),
          "catalogue : l'aiguillage modifié est relu, lui seul, et son nouveau déclencheur marche", parsed)


# ------------------------------------------------------------------ 4. corrections de l'audit
@section
def corrections():
    sg = (SKILLS / "web" / "scrapegraph" / "fiche.md").read_text(encoding="utf-8")
    check("venv/Scripts/python.exe scrapegraphai" not in sg and "--python PY scrapegraphai" in sg,
          "scrapegraph : installation qui marche sous Windows, macOS et Linux (Python du venv noté PY)")
    check("PY scripts/sgai.py" not in sg and "scrapegraph/scripts/sgai.py" in sg and "PY SGAI" in sg
          and (SKILLS / "web" / "scrapegraph" / "scripts" / "sgai.py").is_file(),
          "scrapegraph : script lancé par son chemin complet, plus relatif au dossier courant")
    itc = (SKILLS / "design" / "image-to-code" / "fiche.md").read_text(encoding="utf-8")
    cited = re.findall(r"tests/(test_[\w]+\.py)", itc)
    check(cited and all((CODE / "tests" / c).is_file() for c in cited), "image-to-code : le test cité existe", cited)
    refs = SKILLS / "design" / "image-to-code" / "references"
    starts = {"01-image-d-abord.md": "# CORE DIRECTIVE", "02-mise-en-page.md": "## 13.",
              "03-extraction-et-code.md": "## 21.", "04-anti-slop-et-finition.md": "## 29."}
    bad = [f for f, s in starts.items() if not (refs / f).read_text(encoding="utf-8").startswith(s)]
    check(not bad, "image-to-code : chaque fichier de references/ commence au bon titre", bad)
    logo = head("logo-design")
    pos, neg = skills.split_desc(logo.get("metadata.triggers", ""))
    check("logo pour ma boutique" not in skills.quoted(pos) and "charte graphique" not in skills.quoted(pos)
          and "anime le logo" in skills.quoted(neg),
          "logo-design : plus de « logo pour ma boutique » (contraire à sa marche à suivre), animer un logo exclu")


# ------------------------------------------------------------------ 5. mode classique et README
@section
def classique():
    from brainkit import install
    base = TMP / "claude" / "skills"
    for name, mark in (("taste-skill", True), ("humanizer", True), ("ma-skill", False)):
        (base / name).mkdir(parents=True, exist_ok=True)
        (base / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: \"x\"\n---\n", encoding="utf-8")
        if mark:
            (base / name / install.SKILL_MARK).write_text("{}", encoding="utf-8")
    done = install.sync_skills()
    check(not (base / "taste-skill").exists() and not (base / "humanizer").exists() and (base / "ma-skill").exists(),
          "mode classique : les anciennes skills posées par le cerveau sont retirées, celles de l'utilisateur gardées",
          done)
    check((base / "design" / "SKILL.md").is_file() and (base / "design" / "taste-skill" / "fiche.md").is_file()
          and (base / "composants" / "uiverse" / "scripts" / "galaxy.py").is_file(),
          "mode classique : les skills regroupées posées avec leurs fiches et leurs scripts")


@section
def readme():
    from brainkit import publish
    text = publish.readme("destingood", "destingood/cerveau-claude")
    gone = sorted(set(re.findall(r"/cerveau:(" + "|".join(list(GROUP_OF) + ["humanizer", "vercel"]) + r")\b", text))
                  - set(GROUPS))
    check(not gone, "README : plus aucune commande d'une ancienne skill", gone)
    check(all(f"/cerveau:{g}" in text for g in GROUPS) and "plugins (humanizer, vercel)" in text,
          "README : les cinq aiguillages, et humanizer et vercel renvoyés à leurs plugins")
    check((CODE / "README.md").read_text(encoding="utf-8") == text, "README.md = celui que génère brain publish")


if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
