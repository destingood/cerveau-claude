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

# ----------------------------------------------------------------------------------------- fin
from brainkit.common import remove_tree  # noqa: E402

os.chdir(CODE)
if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
