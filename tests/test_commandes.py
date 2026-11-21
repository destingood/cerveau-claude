"""Ligne de commande : chaque commande garde son aide, son code de sortie et son point d'entrée (étape 8 du plan).

`cli.py` est découpé en modules par thème : ce test vérifie que rien ne change pour l'utilisateur ni pour le reste du
cerveau. Pour chaque commande et chacun de ses alias : `brain <nom> -h` répond en français avec le code 0 ; `brain -h`
les liste toutes ; les noms dont d'autres modules se servent (`cli.main`, `cli.cmd_consolidate` pour optimize.py…)
existent toujours ; un parcours de vraies commandes sur un petit cerveau d'essai donne les bons codes et les bons
messages. (La preuve octet par octet du découpage — 240 commandes rejouées avant et après — est dans le compte rendu de
l'étape 8 ; ce test en garde l'essentiel.)

Lancement : python tests/test_commandes.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-commandes-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_DEBUG"):
    os.environ.pop(k, None)
BR, CFG, HOME, P1 = TMP / "brain", TMP / "claude", TMP / "home", TMP / "projet"
os.environ.update(CLAUDE_CONFIG_DIR=str(CFG), BRAIN_HOME=str(BR), HOME=str(HOME), USERPROFILE=str(HOME),
                  PYTHONIOENCODING="utf-8", HTTPS_PROXY="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1",
                  https_proxy="http://127.0.0.1:1", http_proxy="http://127.0.0.1:1", NO_PROXY="")
for d in (P1 / "src", CFG, HOME, BR):
    d.mkdir(parents=True)
(P1 / "src" / "app.py").write_text("import os\n\ndef login(user):\n    return os.getcwd()\n", encoding="utf-8")
(P1 / "src" / "util.py").write_text("from app import login\n\ndef helper():\n    return login('x')\n", encoding="utf-8")
now = time.strftime("%Y-%m-%dT%H:%M:%S")
(BR / "config.json").write_text(json.dumps({  # rien d'autre en arrière-plan pendant le test
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "journal": {"rattrapage_le": now}, "garde": {"le": now}}), encoding="utf-8")
sys.path.insert(0, str(CODE))
from brainkit import __version__, cli  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402

ENGLISH = re.compile(r"Traceback|unrecognized arguments|arguments are required|invalid choice|expected one argument|"
                     r"invalid \w+ value|error:|usage:|show this help|positional arguments")


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def brain(*args, stdin=None, cwd=P1):
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), *map(str, args)], input=stdin, capture_output=True,
                       env=os.environ.copy(), cwd=str(cwd), timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ 1. les commandes et leurs alias
parser = cli.build_parser()
choices = parser._subparsers._group_actions[0].choices  # nom ou alias → sous-parseur
mains = {}  # sous-parseur → nom principal (le premier enregistré)
for name, sp in choices.items():
    mains.setdefault(id(sp), name)
check(len(mains) >= 60 and len(choices) > len(mains), "parseur : toutes les commandes et leurs alias",
      (len(mains), len(choices)))
for name, sp in choices.items():
    func = sp.get_default("func")
    main = mains[id(sp)]
    check(callable(func), f"`brain {name}` : un point d'entrée", func)
    text = sp.format_help()
    check(text.startswith(f"utilisation : brain {main}") and not ENGLISH.search(text),
          f"`brain {name} -h` : aide en français", text[:300])
for name in sorted(set(mains.values())):
    fname = getattr(choices[name].get_default("func"), "__name__", "")
    check(fname.startswith("cmd_") and callable(getattr(cli, fname, None)),
          f"`brain {name}` : sa fonction ({fname or '?'}) reste accessible depuis brainkit.cli")

# aide de chaque commande par le vrai programme (code 0, rien sur la sortie d'erreur) ; `brain hook …` passe par le
# chemin rapide de brain.py (les hooks), jamais par argparse
for name in sorted(set(mains.values()) - {"hook"}):
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), name, "-h"], capture_output=True,
                       env=os.environ.copy(), cwd=str(P1), timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    check(r.returncode == 0 and out.startswith(f"utilisation : brain {name}") and not r.stderr,
          f"`brain {name} -h` : code 0", (r.returncode, out[:200], r.stderr[-300:]))
code, out = brain("--help")
missing = [n for n in mains.values() if not re.search(rf"(?m)^    {re.escape(n)}(?: \(|\s|$)", out)]
check(code == 0 and not missing, "`brain -h` : toutes les commandes listées", missing)
code, out = brain("--version")
check(code == 0 and out.strip() == f"brain {__version__}", "`brain --version`", out)
code, out = brain()
check(code == 0 and out.startswith("utilisation : brain"), "`brain` sans argument : l'aide, code 0", out[:200])

# ------------------------------------------------------------------ 2. noms dont le reste du cerveau se sert
for name in ("main", "build_parser", "die", "refresh_views", "Parser", "node_line", "project_arg", "cmd_consolidate",
             "cmd_q", "cmd_add", "cmd_doctor", "cmd_hook"):
    check(callable(getattr(cli, name, None)), f"brainkit.cli.{name} existe toujours")

# ------------------------------------------------------------------ 2 bis. découpage : petits modules chargés au besoin
big = {p.name: n for p in sorted((CODE / "brainkit").glob("cli*.py"))
       if (n := p.read_text(encoding="utf-8").count("\n")) > 1000}
check(not big and (CODE / "brainkit" / "cli_memoire.py").is_file(), "cli découpé : aucun module cli*.py de plus de "
      "1 000 lignes", big)
check(not any(m.startswith("brainkit.cli_") and m != "brainkit.cli_commun" for m in sys.modules),
      "construire le parseur ne charge le code d'aucune commande",
      sorted(m for m in sys.modules if m.startswith("brainkit.cli")))
try:
    from brainkit import cli_carte, cli_commun
    moved = cli.map_for is cli_carte.map_for and cli.die is cli_commun.die and cli._FR_ON is cli_commun._FR_ON
except ImportError as exc:  # cli.py d'avant le découpage
    moved = exc
check(moved is True, "anciens noms internes (cli.map_for, cli.die…) servis depuis leur nouveau module", moved)
r = subprocess.run([sys.executable, "-X", "importtime", str(CODE / "brain.py"), "--version"], capture_output=True,
                   env=os.environ.copy(), cwd=str(P1), timeout=60)
loaded = set(re.findall(r"\|\s+(brainkit[\w.]*)\s*$", r.stderr.decode("utf-8", "replace"), re.M))
check(r.returncode == 0 and "brainkit.cli" in loaded and not loaded & {"brainkit.search", "brainkit.index",
                                                                      "brainkit.cli_memoire", "brainkit.cli_entretien"},
      "`brain --version` ne charge ni la recherche ni le code des commandes", sorted(loaded))

# ------------------------------------------------------------------ 3. erreurs de la ligne de commande
for args, want, text in ((["zzzz"], 2, "commande inconnue"), (["q"], 2, "argument manquant"),
                         (["q", "x", "-k", "abc"], 2, "nombre entier attendu"), (["show", "zzz"], 1, "introuvable"),
                         (["add", "-T", "-rf", "-b", "x"], 2, "-T=-rf"), (["neurone", "zzz"], 2, "choix inconnu")):
    code, out = brain(*args)
    check(code == want and text in out and not ENGLISH.search(out),
          f"brain {' '.join(args)} : code {want}, message en français", (code, out))

# ------------------------------------------------------------------ 4. un parcours de vraies commandes
STEPS = [
    (["proj", "add", P1], 0, "✓"),
    (["add", "-t", "learning", "-T", "Le login expire après trente minutes", "-b", "La session dure 30 min.",
      "--id", "m1", "-p", "."], 0, "✓ mémorisé"),
    (["add", "-t", "todo", "-T", "Recompter le stock", "-b", "Avant la fin du mois.", "--id", "m2", "--due",
      "2026-12-01"], 0, "✓ mémorisé"),
    (["add", "-t", "fact", "-T", "Note lue sur l'entrée", "-b", "-", "--id", "m3"], 0, "✓ mémorisé"),
    (["q", "session du login"], 0, "Le login expire"),
    (["q", "--json", "login"], 0, '"id"'),
    (["ls"], 0, "Recompter le stock"),
    (["show", "m1"], 0, "Le login expire"),
    (["edit", "m1", "-a", "Vérifié."], 0, "✓"),
    (["link", "m1", "m2"], 0, "✓ lien"),
    (["unlink", "m1", "m2"], 0, "✓"),
    (["todo"], 0, "Recompter le stock"),
    (["done", "m2"], 0, "✓"),
    (["rm", "m3"], 0, "✓"),
    (["map", P1, "--quiet"], 0, None),
    (["where", "login"], 0, "src/app.py"),
    (["deps", "src/util.py"], 0, None),
    (["explain", "login"], 0, None),
    (["impact", "login"], 0, "Impact"),
    (["files", "login"], 0, None),
    (["index", "--print"], 0, None),
    (["context", "--cwd", P1], 0, None),
    (["recall", "--cwd", P1, "combien de temps dure la session du login"], 0, None),
    (["journal"], 0, None),
    (["stats"], 0, None),
    (["config", "recall.enabled"], 0, None),
    (["config", "recall.enabled", "false"], 0, "✓"),
    (["export"], 0, None),
    (["viz"], 0, "les deux fonctionnent hors ligne"),  # la vue 3D aussi, depuis qu'elle embarque ses bibliothèques
    (["regroupe"], 0, None),
    (["consolidate", "--dry-run"], 0, None),
    (["history"], 0, None),
    (["doctor"], None, "brain"),
    (["skill", "ls"], 0, None),
    (["install", "--dry-run"], 0, None),
    (["vues", "--attendre"], 0, None),
]
for args, want, text in STEPS:
    code, out = brain(*args, stdin="Texte venu de l'entrée.\n".encode("utf-8") if "-" in args else None)
    label = "brain " + " ".join(str(x) for x in args)
    check("Traceback" not in out and not ENGLISH.search(out), f"{label} : ni trace Python ni anglais", out)
    if want is not None:
        check(code == want, f"{label} : code de sortie {want}", f"code {code} : {out}")
    if text:
        check(text in out, f"{label} : « {text} » dans la sortie", out)

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
