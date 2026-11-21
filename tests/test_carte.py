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

# ----------------------------------------------------------------------------------------- fin
from brainkit.common import remove_tree  # noqa: E402

os.chdir(CODE)
if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
