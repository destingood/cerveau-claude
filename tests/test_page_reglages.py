"""La page des réglages (étape 9 du plan : « chaque réglage expliqué »).

Chaque clé de common.DEFAULT_CONFIG et chaque réglage documenté hors des défauts a son explication dans
brainkit/reglages_doc.py ; aucune explication ne parle d'une clé qui n'existe plus ; chaque exemple de la page passe la
vérification de `brain config` ; chaque commande citée existe ; la page du dépôt (skills/brain/references/reglages.md)
est celle que le code produit (`brain publish` la tient à jour) ; `brain config --page [clé]` l'affiche ; une clé
inconnue est toujours refusée (étape 6) ; la page ne coûte rien au démarrage d'une session (jamais injectée, module
jamais chargé par les hooks).

Lancement : python tests/test_page_reglages.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-page-reglages-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_DEBUG"):
    os.environ.pop(k, None)
BR, CFG, HOME = TMP / "brain", TMP / "claude", TMP / "home"
for d in (BR, CFG, HOME):
    d.mkdir(parents=True)
now = time.strftime("%Y-%m-%dT%H:%M:%S")
(BR / "config.json").write_text(json.dumps({  # rien en arrière-plan pendant le test
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "journal": {"rattrapage_le": now}, "garde": {"le": now}}), encoding="utf-8")
os.environ.update(CLAUDE_CONFIG_DIR=str(CFG), BRAIN_HOME=str(BR), HOME=str(HOME), USERPROFILE=str(HOME),
                  PYTHONIOENCODING="utf-8")
sys.path.insert(0, str(CODE))
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


from brainkit import cli, common, install, reglages, reglages_doc as doc  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def brain(*args, extra=()):
    r = subprocess.run([sys.executable, *extra, str(CODE / "brain.py"), *args], capture_output=True, cwd=str(TMP),
                       env=os.environ.copy(), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ 1. une explication par réglage, pas une de trop
leaves = [k for k, _ in reglages._flat(common.DEFAULT_CONFIG)]
documented = set(doc.TEXTES) | set(doc.ETAT)
check(len(leaves) >= 100, f"common.DEFAULT_CONFIG : {len(leaves)} réglages", len(leaves))
check(not [k for k in leaves if k not in documented], "chaque clé de DEFAULT_CONFIG a son explication",
      [k for k in leaves if k not in documented])
extra = list(reglages.EXTRA) + list(reglages.EXTRA_FORMS)
check(not [k for k in extra if k not in doc.TEXTES], "chaque réglage documenté hors des défauts a son explication",
      [k for k in extra if k not in doc.TEXTES])
check(not [k for k in doc.TEXTES if not reglages.known(k)], "aucune explication pour une clé qui n'existe plus",
      [k for k in doc.TEXTES if not reglages.known(k)])
check(set(doc.keys()) == set(doc.TEXTES), "la page montre exactement les réglages expliqués",
      sorted(set(doc.keys()) ^ set(doc.TEXTES)))
check(not set(doc.TEXTES) & set(doc.ETAT), "un réglage n'est pas aussi de l'état tenu par le cerveau",
      sorted(set(doc.TEXTES) & set(doc.ETAT)))
inner = [k for k in doc.ETAT if not (k in reglages.STATE or k in reglages.OPEN or k in leaves)]
check(not inner, "chaque entrée d'état est une clé que le cerveau tient (reglages.STATE, sections libres)", inner)
loose = [k for k in list(reglages.STATE) + list(reglages.OPEN)
         if k not in doc.ETAT and k not in doc.TEXTES and not any(t.startswith(k + ".") for t in doc.TEXTES)]
check(not loose, "chaque section libre et chaque clé d'état est expliquée", loose)
check(not [s for s in {k.split(".")[0] for k in doc.keys()} if s not in doc.SECTIONS],
      "chaque section a un titre et une présentation", sorted({k.split(".")[0] for k in doc.keys()} - set(doc.SECTIONS)))
check(all(len(t) >= 20 and t.strip() == t for t in doc.TEXTES.values()), "aucune explication vide ou bâclée",
      [k for k, t in doc.TEXTES.items() if len(t) < 20])

# ------------------------------------------------------------------ 2. exemples et commandes vrais
page = doc.page()
examples = re.findall(r"Ex\. `brain config (\S+) (.+?)`$", page, re.M)
check(len(examples) >= 100, f"{len(examples)} exemples `brain config` dans la page", len(examples))
bad = []
for key, raw in examples:
    if raw.startswith("<"):  # emplacement à remplir (« <nombre> ») : pas une valeur à essayer
        continue
    txt = raw[1:-1] if raw[:1] == raw[-1:] == "'" else raw
    try:
        value, typed = json.loads(txt), None
    except ValueError:
        value, typed = txt, txt
    good, err = reglages.check(key, value, typed)
    if err:
        bad.append((key, raw, err))
check(not bad, "chaque exemple de la page passe la vérification de `brain config`", bad)
parser = cli.build_parser()
names = set(parser._subparsers._group_actions[0].choices)
cited = set(re.findall(r"`brain ([a-z][\w-]*)", page))
check(cited and not cited - names, f"chaque commande citée existe ({len(cited)} commandes)", sorted(cited - names))
for key in ("recall.min_cov", "eco.bash_output_max_chars", "pc.ram_alert_pct"):
    lo, hi = common.CONFIG_RANGES[key]
    check(f"de {doc._num(lo)} à {doc._num(hi)}" in doc.entry(key), f"bornes de {key} tirées du schéma", doc.entry(key))
check("valeurs : auto, 5m, 1h, off" in doc.entry("eco.cache") and "valeurs : auto, max, conseil, off"
      in doc.entry("delegation.mode"), "choix tirés du schéma (reglages.CHOICES)", doc.entry("eco.cache"))
check("défaut `0.5`" in doc.entry("recall.min_cov") and "défaut `[\"brain\"]`" in doc.entry("skills.exclude"),
      "défauts tirés de DEFAULT_CONFIG", doc.entry("recall.min_cov"))
for name in ("bashOutputMaxChars", "autoCompactWindow", "autoMemoryEnabled", "outputStyle",
             "skillListingBudgetFraction", "skillListingMaxDescChars", "promptCacheTtl"):
    check(f"| `{name}` |" in page, f"réglage de Claude Code du mode éco expliqué : {name}")
check("10 000 (`eco.bash_output_max_chars`)" in page and "200 000 (`eco.auto_compact_window`)" in page,
      "valeurs posées dans Claude Code tirées de DEFAULT_CONFIG", page[page.find("| `bashOutputMaxChars`"):][:300])
check("brain eco --annuler" in page[page.find("## Réglages de Claude Code"):], "la page dit comment tout défaire")
from brainkit import eco  # noqa: E402

check(eco.SKILLS_FRACTION == 0.005 and eco.DESC_CHARS == 250 and eco.OUT_KEY == "bashOutputMaxChars"
      and eco.WIN_KEY == "autoCompactWindow" and eco.MEMORY_KEY == "autoMemoryEnabled" and eco.STYLE_KEY ==
      "outputStyle" and eco.CACHE_KEY == "promptCacheTtl" and set(eco.CACHE_CHOICES) == {"5m", "1h"},
      "la table de Claude Code suit le mode éco (clés et valeurs de eco.py)")

# ------------------------------------------------------------------ 3. la page du dépôt est celle du code
REPO = CODE / "skills" / "brain" / "references" / "reglages.md"
check(REPO.is_file() and REPO.read_text(encoding="utf-8") == page,
      "skills/brain/references/reglages.md = reglages_doc.page() (régénérée par `brain publish`)",
      "relancer `brain publish` (ou le générateur) après un changement de reglages_doc.py")
check(install.all_refs().get("reglages.md") == page and "references/reglages.md" in install.SKILL,
      "la skill /brain livre la page et la nomme")
check("skills/brain/references/reglages.md" in (CODE / "README.md").read_text(encoding="utf-8"),
      "le README mène à la page des réglages")
dest = TMP / "skill-classique"
install.write_brain_skill(dest)
check((dest / "references" / "reglages.md").read_text(encoding="utf-8") == page,
      "installation classique : la page posée avec la skill")
install.remove_brain_skill(dest)
check(not (dest / "references").exists(), "désinstallation : la page retirée avec la skill", list(dest.rglob("*")))

# ------------------------------------------------------------------ 4. `brain config --page`
code, out, err = brain("config", "--page")
check(code == 0 and out == page, "brain config --page : la page entière", (code, err[-300:]))
code, out, err = brain("config", "--page", "recall.min_cov")
check(code == 0 and out.startswith("- **`recall.min_cov`**") and doc.TEXTES["recall.min_cov"] in out
      and out.count("- **") == 1, "brain config --page <clé> : ce réglage seulement", (code, out, err))
code, out, err = brain("config", "--page", "pc")
check(code == 0 and out.count("- **`pc.") == len([k for k in doc.keys() if k.startswith("pc.")]),
      "brain config --page <section> : toute la section", (code, out[:300], err))
code, out, err = brain("config", "--page", "eco.avant")
check(code == 0 and "tenu par le cerveau, à ne pas modifier" in out, "--page sur une clé d'état : dite interne",
      (code, out, err))
code, out, err = brain("config", "--page", "recall.min_kov")
check(code == 1 and "clé inconnue" in err and "recall.min_cov" in err and "Traceback" not in err,
      "--page sur une clé inconnue : code 1, la bonne clé proposée", (code, out, err))
code, out, err = brain("config", "--page", "recall.min_cov", "0.4")
check(code == 2 and "sans valeur" in err and "Traceback" not in err, "--page avec une valeur : code 2", (code, err))
before = (BR / "config.json").read_text(encoding="utf-8")
code, out, err = brain("config", "recall.min_kov", "0.4")
check(code == 1 and "clé inconnue" in err and (BR / "config.json").read_text(encoding="utf-8") == before,
      "une clé inconnue est toujours refusée, rien n'est écrit (étape 6)", (code, err))
code, out, err = brain("config", "recall.min_cov", "2")
check(code == 1 and "de 0 à 1" in err, "une valeur hors bornes est toujours refusée", (code, err))
code, out, err = brain("config")
check(code == 0 and json.loads(out[:out.rfind("}") + 1]).get("recall", {}).get("min_cov") == 0.5,
      "brain config sans argument : toujours la configuration en JSON", (code, out[:200], err))

# ------------------------------------------------------------------ 5. rien au démarrage d'une session
payload = json.dumps({"session_id": "s1", "cwd": str(TMP), "source": "startup"}).encode()
r = subprocess.run([sys.executable, "-X", "importtime", str(CODE / "brain.py"), "hook", "session-start"], input=payload,
                   capture_output=True, cwd=str(TMP), env=os.environ.copy(), timeout=120)
start_out, start_err = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
check(r.returncode == 0 and start_out.strip(), "démarrage de session : le hook répond", (r.returncode, start_err[-300:]))
loaded = re.findall(r"\|\s+(brainkit\.[\w.]+)\s*$", start_err, re.M)  # modules chargés (python -X importtime)
check("brainkit.hooks" in loaded and not [m for m in loaded if m.startswith("brainkit.reglages")],
      "démarrage : la page et le schéma des réglages ne sont pas chargés",
      [m for m in loaded if "reglages" in m] or loaded[:5])
check("les réglages" not in start_out and "references/reglages.md" not in start_out,
      "démarrage : la page n'est pas injectée", start_out[:300])
code, out, err = brain("config", extra=("-X", "importtime"))
loaded = re.findall(r"\|\s+(brainkit\.[\w.]+)\s*$", err, re.M)
check(code == 0 and "brainkit.reglages" in loaded and "brainkit.reglages_doc" not in loaded,
      "brain config sans argument : la page n'est pas chargée (seulement le schéma, comme avant)", loaded)

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
