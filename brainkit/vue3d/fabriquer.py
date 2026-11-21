"""Fabrique les bibliothèques de la vue 3D livrées avec le plugin (brainkit/vue3d/), depuis les paquets npm officiels.

La vue 3D (cerveau.html) chargeait trois.js et 3d-force-graph depuis trois sites (jsdelivr, unpkg, esm.sh), sans
contrôle d'intégrité, et ne marchait pas sans connexion. Elle les intègre maintenant à la page, depuis ce dossier :
- 3d-force-graph.min.js : `dist/3d-force-graph.min.js` du paquet 3d-force-graph, copié tel quel (script classique) ;
- three-fx.js : three.js (`build/three.core.min.js`) et la passe de bloom (UnrealBloomPass et ce qu'elle importe,
  `examples/jsm/`), modules ES convertis en un script classique : un module ne se charge pas depuis une page ouverte
  en file://. Le texte des modules n'est pas modifié, seules leurs lignes `import`/`export` deviennent des variables.
sources.json garde les versions et l'empreinte SHA-256 de chaque fichier (le test les vérifie) ; LICENCES.md les
licences. Pour changer de version : télécharger les paquets (`npm pack three@<v> 3d-force-graph@<v>`, rien n'est
exécuté), les décompresser, puis
    python brainkit/vue3d/fabriquer.py <dossier de three/package> <dossier de 3d-force-graph/package>
La révision de three.js doit être celle que 3d-force-graph embarque (sinon les effets de la page se désactivent).
Outil de développement : le cerveau ne l'importe jamais."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = "build/three.core.min.js"
# Passe de bloom et ses dépendances, dans l'ordre où elles se définissent
ADDONS = ("examples/jsm/shaders/CopyShader.js", "examples/jsm/shaders/LuminosityHighPassShader.js",
          "examples/jsm/postprocessing/Pass.js", "examples/jsm/postprocessing/UnrealBloomPass.js")
FG = "dist/3d-force-graph.min.js"
IMPORT_RX = re.compile(r"(?m)^import\s*\{([^}]*)\}\s*from\s*'([^']+)';[ \t]*$")
EXPORT_RX = re.compile(r"(?m)^export\s*\{([^}]*)\};[ \t]*$")
CORE_EXPORT_RX = re.compile(r"export\{([^}]*)\};?\s*$")
BAD_IN_SCRIPT = re.compile(r"</script|<!--|<script", re.I)  # rien qui puisse fermer ou dérégler un <script> en ligne


def _pairs(spec: str) -> list:
    """« a, b as c » → [("a", "a"), ("b", "c")] : (nom exporté par la source, nom local)."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            src, _, local = part.partition(" as ")
            out.append((src.strip(), (local or src).strip()))
    return out


def _core(text: str) -> str:
    """three.core.min.js (un module ES sans import, une seule ligne `export{…}` à la fin) → fonction qui rend l'objet
    des exports."""
    m = CORE_EXPORT_RX.search(text)
    if not m or re.search(r"\bimport\s*[{*(]|\bimport\.meta\b", text) or text.count("export{") != 1:
        raise SystemExit("three.core.min.js : forme inattendue (import, ou plusieurs export)")
    exports = ",".join(f"{json.dumps(name)}:{local}" for local, name in _pairs(m.group(1)))
    return "function(){\"use strict\";\n" + text[:m.start()] + "\nreturn{" + exports + "};}"


def _module(rel: str, text: str) -> str:
    """Module ES de examples/jsm → fonction(T, M) : T = three.js, M = les modules déjà définis (par chemin)."""
    head = []
    for spec, src in IMPORT_RX.findall(text):
        obj = "T" if src == "three" else "M[" + json.dumps(posixpath.normpath(posixpath.join(posixpath.dirname(rel), src))) + "]"
        if obj != "T" and json.loads(obj[2:-1]) not in ADDONS:
            raise SystemExit(f"{rel} : import inattendu {src}")
        head.append("const {" + ", ".join(a if a == b else f"{a}: {b}" for a, b in _pairs(spec)) + "} = " + obj + ";")
    body = IMPORT_RX.sub("", text)
    exports = EXPORT_RX.findall(body)
    if len(exports) != 1:
        raise SystemExit(f"{rel} : il faut exactement un export")
    body = EXPORT_RX.sub("return {" + ", ".join(a if a == b else f"{b}: {a}" for a, b in _pairs(exports[0])) + "};", body)
    if re.search(r"(?m)^\s*(?:import|export)\b", body) or "import.meta" in body or re.search(r"\bimport\(", body):
        raise SystemExit(f"{rel} : import ou export restant")
    return "function(T, M){\"use strict\";\n" + "\n".join(head) + "\n" + body + "\n}"


def build_fx(three_dir: Path) -> str:
    three_dir = Path(three_dir)
    version = json.loads((three_dir / "package.json").read_text(encoding="utf-8"))["version"]
    parts = ["/* Cerveau — effets de la vue 3D, hors ligne. Fabriqué par brainkit/vue3d/fabriquer.py : ne pas éditer.",
             f"   three.js {version} (build/three.core.min.js) et UnrealBloomPass (examples/jsm/), MIT,",
             "   Copyright © 2010-2026 three.js authors — voir LICENCES.md. Modules ES devenus un script classique. */",
             "(function(){\"use strict\";",
             "var w = typeof window !== \"undefined\" ? window : globalThis, had = \"__THREE__\" in w, prev = w.__THREE__;",
             "try { delete w.__THREE__; } catch (e) {}  // même révision que 3d-force-graph : pas d'avertissement « plusieurs three.js »",
             "var T;",
             "try { T = (" + _core((three_dir / CORE).read_text(encoding="utf-8")) + ")(); }",
             "finally { if (had) w.__THREE__ = prev; }",
             "var M = {};"]
    for rel in ADDONS:
        parts.append("M[" + json.dumps(rel) + "] = (" + _module(rel, (three_dir / rel).read_text(encoding="utf-8")) + ")(T, M);")
    parts.append("w.__cerveauFX = {THREE: T, UnrealBloomPass: M[" + json.dumps(ADDONS[-1]) + "].UnrealBloomPass, "
                 "revision: T.REVISION};")
    parts.append("})();\n")
    return "\n".join(parts)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(three_dir, fg_dir) -> int:
    three_dir, fg_dir = Path(three_dir), Path(fg_dir)
    tv = json.loads((three_dir / "package.json").read_text(encoding="utf-8"))["version"]
    fv = json.loads((fg_dir / "package.json").read_text(encoding="utf-8"))["version"]
    fg = (fg_dir / FG).read_text(encoding="utf-8")
    # la révision embarquée : la constante écrite juste avant que three.js la publie dans window.__THREE__
    revs = set(re.findall(r'const [A-Za-z_$][\w$]*="(\d{3})",', fg))
    if revs != {tv.split(".")[1]}:
        raise SystemExit(f"three {tv} : 3d-force-graph {fv} embarque la révision {sorted(revs) or '?'}")
    fx = build_fx(three_dir)
    for name, text in (("3d-force-graph.min.js", fg), ("three-fx.js", fx)):
        if BAD_IN_SCRIPT.search(text):
            raise SystemExit(f"{name} : contient </script, <script ou <!-- (ne peut pas aller dans la page)")
        (HERE / name).write_bytes(text.encode("utf-8"))
    sources = {
        "3d-force-graph.min.js": {"paquet": "3d-force-graph", "version": fv, "licence": "MIT", "fichier": FG,
                                  "sha256_source": sha256(fg_dir / FG), "sha256": sha256(HERE / "3d-force-graph.min.js")},
        "three-fx.js": {"paquet": "three", "version": tv, "licence": "MIT", "fichiers": [CORE, *ADDONS],
                        "sha256_source": {f: sha256(three_dir / f) for f in (CORE, *ADDONS)},
                        "sha256": sha256(HERE / "three-fx.js")},
    }
    (HERE / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name, meta in sources.items():
        print(f"✓ {name} : {meta['paquet']} {meta['version']}, {(HERE / name).stat().st_size // 1024} Ko, {meta['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
