"""Carte de projets (`brain map`, mapper.py), testée en direct sur de petits projets construits ici :
dossiers ignorés (build/, out/, env/ seulement là où ce sont des sorties), paquets locaux d'un monorepo (pas des
dépendances externes), exports CommonJS indexés, changement fait dans la même seconde vu, et requêtes (where, deps,
explain, impact, path) qui gardent leurs réponses.

Lancement : python tests/test_carte.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-carte-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")  # import en direct de brainkit : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "brain")
os.environ["BRAIN_OFFLINE"] = "1"
WORK = TMP / "travail"
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))

from brainkit import mapper  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def put(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def carte(root, **kw):
    meta = mapper.map_project(str(root), quiet=True, **kw)
    return mapper.load_map(meta["pid"])


# ----------------------------------------------------------------------------------------- dossiers ignorés
P = TMP / "dossiers"
put(P, "package.json", json.dumps({"name": "site"}))
put(P, "src/main.py", "from env import config\n")
put(P, "src/env/config.py", "def charge():\n    return 1\n")  # un module à soi nommé env : du code
put(P, "src/build/outil.py", "def construit():\n    pass\n")  # outils de construction à soi : du code
put(P, "app/out/rapport.py", "def sortie():\n    pass\n")
put(P, "lib/target/cible.js", "function vise() {}\n")
put(P, "build/genere.js", "function g() {}\n")  # sortie de build à la racine : ignorée, comme avant
put(P, "dist/bundle.js", "function b() {}\n")
put(P, "coverage/lcov.js", "function c() {}\n")
put(P, "packages/ui/package.json", json.dumps({"name": "ui"}))
put(P, "packages/ui/dist/ui.js", "function u() {}\n")  # à côté d'un package.json : une sortie
put(P, "packages/ui/out/ui.js", "function o() {}\n")
put(P, "packages/ui/src/bouton.js", "export function bouton() {}\n")
put(P, "rust/Cargo.toml", "[package]\nname = \"r\"\n")
put(P, "rust/target/debug/x.rs", "fn x() {}\n")
put(P, "dotnet/app.csproj", "<Project/>\n")
put(P, "dotnet/obj/gen.cs", "class Gen {}\n")
put(P, "outils/env/pyvenv.cfg", "home = /usr/bin\n")  # un vrai environnement Python nommé env
put(P, "outils/env/lib/site.py", "def s():\n    pass\n")
put(P, "outils/conda/env/conda-meta/history", "x\n")
put(P, "outils/conda/env/lib/c.py", "def c():\n    pass\n")
put(P, "venv/lib/v.py", "def v():\n    pass\n")
put(P, "node_modules/x/index.js", "function n() {}\n")
put(P, "web/vendor/jquery.js", "function jq() {}\n")
files = carte(P)["files"]
for rel in ("src/env/config.py", "src/build/outil.py", "app/out/rapport.py", "lib/target/cible.js",
            "packages/ui/src/bouton.js"):
    check(rel in files, f"dossiers ignorés : {rel} (du code, pas une sortie) est dans la carte", sorted(files))
for rel in ("build/genere.js", "dist/bundle.js", "coverage/lcov.js", "packages/ui/dist/ui.js", "packages/ui/out/ui.js",
            "rust/target/debug/x.rs", "dotnet/obj/gen.cs", "outils/env/lib/site.py", "outils/conda/env/lib/c.py",
            "venv/lib/v.py", "node_modules/x/index.js", "web/vendor/jquery.js"):
    check(rel not in files, f"dossiers ignorés : {rel} (sortie, environnement ou dépendance) reste hors de la carte")
check(files.get("src/main.py", {}).get("out") == ["src/env/config.py"], "dossiers ignorés : l'import de src/env/ est résolu",
      files.get("src/main.py"))

# ----------------------------------------------------------------------------------------- paquets locaux
M = TMP / "monorepo"
put(M, "package.json", json.dumps({"name": "mono", "private": True, "workspaces": ["packages/*"], "dependencies": {
    "@acme/utils": "workspace:*", "commun": "file:../commun", "lien": "link:../lien", "react": "^18"}}))
put(M, "packages/utils/package.json", json.dumps({"name": "@acme/utils", "main": "lib/index.js"}))
put(M, "packages/utils/lib/index.js", "export function slug(s) { return s }\n")
put(M, "packages/utils/lib/aide.js", "export const aide = 1\n")
put(M, "packages/ui/package.json", json.dumps({"name": "ui", "exports": {".": {"import": "./src/ui.js"}}}))
put(M, "packages/ui/src/ui.js", "export function bouton() {}\n")
put(M, "packages/kit/package.json", json.dumps({"name": "kit", "main": "dist/kit.js"}))  # main construit : absent
put(M, "packages/kit/src/index.js", "export function outil() {}\n")
put(M, "apps/web/index.js", "import { slug } from '@acme/utils'\nimport { aide } from '@acme/utils/lib/aide'\n"
    "import { bouton } from 'ui'\nimport { outil } from 'kit'\nconst c = require('commun')\n"
    "const l = require('lien/x')\nimport React from 'react'\nimport fs from 'fs'\n")
put(M, "pyproject.toml", '[project]\nname = "mono"\ndependencies = ["requests>=2", "coeur @ file:///opt/coeur",'
    ' "outil-local @ ./outils/local"]\n\n[tool.uv.sources]\nsoutien = { path = "../soutien" }\n')
put(M, "libs/corelib/pyproject.toml", '[project]\nname = "corelib"\n')
put(M, "libs/corelib/src/corelib/__init__.py", "def noyau():\n    pass\n")
put(M, "libs/plat/setup.py", "from setuptools import setup\nsetup(name='plat')\n")
put(M, "libs/plat/plat/__init__.py", "def plateau():\n    pass\n")
put(M, "requirements.txt", "flask==3.0\n-e ./outils/editable\n../voisin\nmonpaquet @ file:///srv/monpaquet\n"
    "git+https://exemple.test/x.git#egg=distant\n")
put(M, "app/main.py", "import corelib\nfrom corelib import noyau\nimport plat\nimport coeur\nimport outil_local\n"
    "import soutien\nimport editable\nimport voisin\nimport monpaquet\nimport requests\nimport flask\nimport json\n")
put(M, "libs/corelib/src/corelib/outils.py", "def aide():\n    pass\n")
put(M, "services/paiement/stripe_api.py", "def payer():\n    pass\n")  # paquet espace de noms : sans __init__.py
put(M, "app/usage.py", "from corelib.outils import aide\nfrom services.paiement.stripe_api import payer\n"
    "from services import paiement\nimport services\nfrom app import main\nimport pydantic\n")
m = carte(M)
f = m["files"]
web, py = f["apps/web/index.js"], f["app/main.py"]
check(web.get("out") == ["packages/kit/src/index.js", "packages/ui/src/ui.js", "packages/utils/lib/aide.js",
                         "packages/utils/lib/index.js"],
      "paquets locaux : les imports JS d'un paquet du monorepo vont vers ses fichiers (main, exports, src/index, chemin)",
      web.get("out"))
check(web.get("ext") == ["react"], "paquets locaux : seuls les vrais paquets JS sont externes (pas workspace:, file:, link:)",
      web.get("ext"))
check(py.get("out") == ["libs/corelib/src/corelib/__init__.py", "libs/plat/plat/__init__.py"],
      "paquets locaux : les imports Python d'un paquet du dépôt (libs/x/src/x, libs/x/x) sont résolus", py.get("out"))
check(py.get("ext") == ["flask", "requests"],
      "paquets locaux : file:, chemin, uv path, -e ./ ne sont pas des paquets Python externes", py.get("ext"))
check(f["requirements.txt"].get("deps") == ["flask", "distant"] and f["requirements.txt"].get("local") ==
      ["editable", "monpaquet", "voisin"], "paquets locaux : requirements.txt sépare les dossiers des dépendances",
      f["requirements.txt"])
check(f["package.json"].get("local") == ["@acme/utils", "commun", "lien"], "paquets locaux : package.json les note",
      f["package.json"].get("local"))
use = f["app/usage.py"]
check(use.get("out") == ["app/main.py", "libs/corelib/src/corelib/outils.py", "services/paiement/stripe_api.py"],
      "paquets locaux : `from paquet.module import nom` résout le module", use.get("out"))
check(use.get("ext") == ["pydantic"], "paquets locaux : `from paquet.module import nom` ne rend pas le paquet externe "
      "(ni un paquet espace de noms sans __init__.py)", use.get("ext"))
lines = mapper.deps(m, "apps/web/index.js")
check(any(x.startswith("→ paquets externes : react") for x in lines) and not any("@acme" in x and "externes" in x for x in lines),
      "paquets locaux : `brain deps` ne les montre plus comme externes", lines)

# ----------------------------------------------------------------------------------------- exports CommonJS
C = TMP / "commonjs"
put(C, "package.json", json.dumps({"name": "outils", "main": "lib/index.js"}))
put(C, "lib/index.js", """'use strict'
function interne() {}
exports.slugify = function (s) { return s.toLowerCase() }
exports.lent = async (x) => x
module.exports.aide = (x) => x
exports.VERSION = '1.0'
exports.Panier = class {}
""")
put(C, "lib/objet.js", """const fs = require('fs')
function lire() {}
module.exports = {
  lire,
  ecrire() { return 1 },
  'copier': require('./copie'),
  taille: 3,
  ...autres,
  libelle: "a, b } c",
  async vider() {},
}
""")
put(C, "lib/copie.js", "module.exports = function copier() {}\n")
put(C, "lib/moteur.js", "module.exports = class Moteur {}\n")
put(C, "app.js", "const { slugify } = require('./lib')\nslugify('X')\n")
m = carte(C)
syms = {rel: {s["n"]: (s["k"], s["l"]) for s in f.get("symbols", [])} for rel, f in m["files"].items()}
want = {"lib/index.js": {"interne": ("fn", 2), "slugify": ("fn", 3), "lent": ("fn", 4), "aide": ("fn", 5),
                         "VERSION": ("const", 6), "Panier": ("class", 7)},
        "lib/objet.js": {"lire": ("fn", 2), "ecrire": ("fn", 5), "copier": ("const", 6), "taille": ("const", 7),
                         "libelle": ("const", 9), "vider": ("fn", 10)},
        "lib/copie.js": {"copier": ("fn", 1)}, "lib/moteur.js": {"Moteur": ("class", 1)}}
for rel, exp in want.items():
    check(syms.get(rel) == exp, f"exports CommonJS : symboles de {rel}", syms.get(rel))
check(mapper.where(m, "slugify")[:1] == ["lib/index.js:3  fn slugify"], "exports CommonJS : `brain where slugify` le trouve",
      mapper.where(m, "slugify"))
check(mapper.where(m, "vider") == ["lib/objet.js:10  fn vider"], "exports CommonJS : un export d'objet se trouve aussi",
      mapper.where(m, "vider"))
check("autres" not in syms["lib/objet.js"], "exports CommonJS : `...autres` n'est pas un nom exporté")

# ----------------------------------------------------------------------------------------- même seconde
import time  # noqa: E402

Q = TMP / "seconde"
a = put(Q, "app.py", "def avant():\n    pass\n")
b = put(Q, "autre.py", "def stable():\n    pass\n")
carte(Q)
st = a.stat()
a.write_text("def apres():\n    pass\n", encoding="utf-8", newline="\n")  # même taille
os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))  # 1 µs plus tard : la même seconde
m = carte(Q)
check([s["n"] for s in m["files"]["app.py"].get("symbols", [])] == ["apres"],
      "même seconde : un changement 1 µs après la carte précédente est vu", m["files"]["app.py"])
st = a.stat()
a.write_text("def autre():\n    pass\n", encoding="utf-8", newline="\n")
os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns))  # date identique (disque aux dates à la seconde, FAT…)
m = carte(Q)
check([s["n"] for s in m["files"]["app.py"].get("symbols", [])] == ["autre"],
      "même seconde : un changement à date identique, juste après la carte précédente, est vu", m["files"]["app.py"])
old = time.time_ns() - 3600 * 10**9  # fichiers d'il y a une heure : plus rien n'est proche de la dernière carte
for f in (a, b):
    os.utime(f, ns=(old, old))
carte(Q)
g = mapper.process_file.__globals__
reads = []


def counting_open(path, *args, **kw):
    reads.append(str(path))
    return open(path, *args, **kw)


g["open"] = counting_open
try:
    meta = mapper.map_project(str(Q), quiet=True)
finally:
    del g["open"]
check(meta["parsed"] == 0 and not [r for r in reads if r.endswith(".py")],
      "même seconde : un projet inchangé n'est ni relu ni ré-analysé", (meta["parsed"], reads))
os.utime(b, ns=(old, old + 5))  # date changée, contenu identique : relu, pas ré-analysé
meta = mapper.map_project(str(Q), quiet=True)
check(meta["parsed"] == 0, "même seconde : contenu identique sous une autre date : pas ré-analysé", meta)

# ----------------------------------------------------------------------------------------- requêtes et formats
# Caractérisation : ce que la carte répond aujourd'hui (découpage de mapper.py en modules le 21/11/2026, sans changer
# une réponse). Un changement voulu de ces réponses se fait ici, en connaissance de cause.
import zipfile  # noqa: E402

F = TMP / "boutique"
put(F, "package.json", json.dumps({"name": "boutique", "main": "server/index.js", "scripts": {"dev": "node server/index.js"},
                                   "dependencies": {"express": "^4", "react": "^18"}}))
put(F, "server/index.js", "// Serveur de la boutique\nconst express = require('express')\nconst { total } = require('./prix')\n"
    "const app = express()\napp.get('/api/produits', (req, res) => res.json([]))\n"
    "const PORT = process.env.PORT || 3000\n// TODO: brancher le paiement\nmodule.exports = { app }\n")
put(F, "server/prix.js", "exports.total = (p) => p.reduce((s, x) => s + x, 0)\n")
put(F, "outils/__init__.py", "")
put(F, "outils/calcul.py", "def somme(xs):\n    return sum(xs)\n\n\nclass Moyenne:\n    def valeur(self):\n"
    "        return somme([1])\n")
put(F, "outils/tache.py", '"""Tâche du jour : calcule et envoie le rapport."""\nimport os\n\nimport requests\n'
    "from flask import Flask\n\nfrom outils.calcul import somme, Moyenne\nfrom .aide import formater\n\n"
    'app = Flask(__name__)\nURL = os.environ.get("RAPPORT_URL")\n\n\n'  # coupé avant le décorateur : collé au
    '@app.route("/rapport")\ndef rapport():\n'  # saut de ligne, `brain publish` le prendrait pour une adresse e-mail
    "    return formater(somme([1, 2]))\n\n\ndef principal():\n    m = Moyenne()\n    requests.post(URL, json=m.valeur())\n"
    '    # POURQUOI: le serveur limite les envois\n\n\nif __name__ == "__main__":\n    principal()\n')
put(F, "outils/aide.py", "def formater(x):\n    return str(x)\n")
put(F, "outils/cycle_a.py", "from outils.cycle_b import b\n\n\ndef a():\n    return b()\n")
put(F, "outils/cycle_b.py", "from outils.cycle_a import a\n\n\ndef b():\n    return a()\n")
put(F, "tests/test_calcul.py", "from outils.calcul import somme\n\n\ndef test_somme():\n    assert somme([1]) == 1\n")
put(F, "README.md", "# Boutique de thé\n\nUne boutique en ligne.\n\n## Installation\n\nVoir [le guide](docs/guide.md).\n")
put(F, "docs/guide.md", "# Guide\n\n## Déployer\n")
put(F, "public/index.html", "<html><head><title>Boutique</title><link rel=\"stylesheet\" href=\"style.css\"></head>"
    "<body><h1>Bienvenue</h1></body></html>\n")
put(F, "public/style.css", "@import 'theme.css';\n")
put(F, "public/theme.css", "body{}\n")
put(F, "donnees/ventes.csv", "date,produit,montant\n2026-01-01,the,12\n")
put(F, "requirements.txt", "requests\nflask\n")
put(F, "secrets.json", "{}\n")
(F / "media").mkdir()
(F / "media/logo.png").write_bytes(b"\x89PNG" + b"\x00" * 64)
with zipfile.ZipFile(F / "docs/rapport.docx", "w") as z:
    z.writestr("docProps/core.xml", "<cp:coreProperties><dc:title>Rapport annuel</dc:title></cp:coreProperties>")
    z.writestr("word/document.xml", '<w:document><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Résultats</w:t>'
               "</w:r></w:p></w:document>")
with zipfile.ZipFile(F / "donnees/budget.xlsx", "w") as z:
    z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Janvier"/><sheet name="Février"/></sheets></workbook>')
(F / "docs/fiche.pdf").write_bytes(b"%PDF-1.4 << /Title (Fiche produit) >> << /Type /Page >>\n")
m = carte(F)
files = m["files"]
got = mapper.where(m, "somme")
check(got == ['outils/calcul.py:1  fn somme', 'tests/test_calcul.py:4  fn test_somme'],
      'requêtes : where', got)
got = mapper.where(m, "PORT")
check(got == ['outils/tache.py:15  fn rapport', "variable d'env PORT utilisée dans : server/index.js", 'outils/tache.py  route ANY /rapport → rapport'],
      'requêtes : where env', got)
got = mapper.where(m, "rapport")
check(got == ['outils/tache.py:15  fn rapport', 'outils/tache.py  route ANY /rapport → rapport'],
      'requêtes : where route', got)
got = mapper.deps(m, "outils/tache.py")
check(got == ['`outils/tache.py`', '→ importe (2) : outils/aide.py, outils/calcul.py', '→ paquets externes : flask, requests', '← importé par (0) : —'],
      'requêtes : deps', got)
got = mapper.explain(m, "outils/calcul.py")[1:]
check(got == ['Symboles (3) : somme (fn l.1), Moyenne (class l.5), Moyenne.valeur (method l.6)', 'Importé par (2) : outils/tache.py, tests/test_calcul.py'],
      'requêtes : explain fichier', got)
got = mapper.explain(m, "outils/calcul.py:somme")[:3]
check(got == ['Symbole « somme » : outils/calcul.py:1  fn', 'Appelé par (3) : Moyenne.valeur (outils/calcul.py:7) · rapport (outils/tache.py:16) · test_somme (tests/test_calcul.py:5)', ''],
      'requêtes : explain symbole', got)
got = mapper.impact(m, "somme")
check(got == (['Impact de « somme » — outils/calcul.py:1 (fonction) · profondeur 2', '', 'Dépend directement (3) :', '- outils/calcul.py:7  Moyenne.valeur appelle somme', '- outils/tache.py:16  rapport appelle somme', '- tests/test_calcul.py:5  test_somme appelle somme', '', 'Niveau 2 (1) :', '- outils/tache.py:21  principal appelle (déduit) Moyenne.valeur', '', 'À revoir : 1 fichier(s) — `outils/tache.py`', 'Tests reliés : `tests/test_calcul.py`', '(« déduit » : méthode au nom unique dans le projet, appelée sur un objet : à confirmer)'], 0),
      'requêtes : impact', got)
got = mapper.path_between(m, "outils/tache.py", "outils/aide.py")
check(got == ['1 saut(s) : `outils/tache.py` importe `outils/aide.py`'],
      'requêtes : path', got)
got = mapper.path_between(m, "public/index.html", "public/theme.css")
check(got == ['2 saut(s) : `public/index.html` importe `public/style.css` importe `public/theme.css`'],
      'requêtes : path html', got)
got = len(mapper.call_edges(m))
check(got == 10,
      "requêtes : graphe d'appels", got)
got = m["meta"]["stack"]["summary"]
check(got == 'Python 81% · JavaScript 14% · CSS 3% · Express · React · Flask · requests',
      'requêtes : stack', got)
got = m["meta"]["entries"]
check(got == [['server/index.js', 'package.json'], ['outils/tache.py', '__main__'], ['public/index.html', 'page']],
      "requêtes : points d'entrée", got)
got = m["cycles"]
check(got == [['outils/cycle_a.py', 'outils/cycle_b.py']],
      'requêtes : cycles', got)
got = {k: files["docs/rapport.docx"].get(k) for k in ("title", "headings")}
check(got == {'title': 'Rapport annuel', 'headings': ['## Résultats']},
      'requêtes : Word', got)
got = files["donnees/budget.xlsx"].get("sheets")
check(got == ['Janvier', 'Février'],
      'requêtes : Excel', got)
got = {k: files["docs/fiche.pdf"].get(k) for k in ("title", "doc")}
check(got == {'title': 'Fiche produit', 'doc': '1 page(s)'},
      'requêtes : PDF', got)
got = files["donnees/ventes.csv"].get("doc")
check(got == '2 lignes · colonnes : date,produit,montant',
      'requêtes : CSV', got)
got = files["secrets.json"].get("sensitive")
check(got == True,
      'requêtes : fichier sensible', got)
got = files["media/logo.png"].get("lang")
check(got == 'asset',
      'requêtes : image', got)
got = files["server/index.js"].get("routes")
check(got == ['GET /api/produits'],
      'requêtes : routes JS', got)
got = files["outils/tache.py"].get("routes")
check(got == ['ANY /rapport → rapport'],
      'requêtes : routes Flask', got)
got = files["outils/tache.py"].get("why")
check(got == [[22, 'POURQUOI', 'le serveur limite les envois']],
      'requêtes : raisons notées', got)
got = files["server/index.js"].get("todos")
check(got == [[7, 'TODO', 'brancher le paiement']],
      'requêtes : TODO', got)
got = [x for x in (F and (mapper.PROJECTS_DIR / m["meta"]["pid"] / "MAP.md").read_text(encoding="utf-8").splitlines()) if x.startswith("## ")]
check(got == ['## Structure', "## Fichiers clés (centralité dans le graphe d'imports/liens)", "## Modules (communautés d'imports)", '## Routes / endpoints (2)', "## Variables d'environnement (noms uniquement)", "## Documents (4, plus récents d'abord)", '## Données (2)', '## Récemment modifiés', "## Points d'attention", '## Utiliser cette carte'],
      'requêtes : sections de MAP.md', got)
digest = (mapper.PROJECTS_DIR / m["meta"]["pid"] / "DIGEST.md").read_text(encoding="utf-8").splitlines()[0]
check(digest.startswith("**🗺️ Carte du dossier** (") and digest.endswith(") : 22 fichiers — 12 code, 4 docs, 5 données, 1 médias."), "requêtes : DIGEST.md", digest)
got = [r["key"] for r in mapper.search_files(m["meta"]["pid"], "total du panier", 3)]
check(got == ['server/prix.js'],
      'requêtes : recherche', got)

# ----------------------------------------------------------------------------------------- fin
from brainkit.common import remove_tree  # noqa: E402

os.chdir(CODE)
if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
