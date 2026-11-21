"""Vue 3D sans aucun site extérieur (étape 8 du plan) : bibliothèques livrées avec le plugin et intégrées à la page,
empreintes et licences, page sûre (aucune balise <script> qui déborde), plugin construit avec les fichiers, mise à jour
classique qui les copie, et — si Playwright et Chromium sont là (pas sur la CI) — la page ouverte depuis le disque,
réseau coupé : graphe dessiné, effets actifs, aucune erreur.

Lancement : python tests/test_vue3d.py   (sortie : « N vérifications OK, M échec(s) »)"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-vue3d-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD"):
    os.environ.pop(k, None)
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "BRAIN_HOME": str(TMP / "brain"), "HOME": str(TMP / "home"),
                   "USERPROFILE": str(TMP / "home"), "BRAIN_NO_BACKGROUND": "1"})
sys.path.insert(0, str(CODE))
OK, FAIL, SKIP = [], [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


from brainkit import selfupdate, viz, viz3d  # noqa: E402
from brainkit.store import Brain  # noqa: E402

VUE = CODE / "brainkit" / "vue3d"

# ---------------------------------------------------------------------------------------------- fichiers livrés
check(VUE.is_dir() and (VUE / "page.html").is_file(), "le gabarit de la vue 3D est un fichier (vue3d/page.html)")
lines = len((CODE / "brainkit" / "viz3d.py").read_text(encoding="utf-8").splitlines())
check(lines < 1000, "viz3d.py fait moins de 1 000 lignes", lines)
manifest = json.loads((VUE / "sources.json").read_text(encoding="utf-8")) if (VUE / "sources.json").is_file() else {}
check(set(manifest) == {"3d-force-graph.min.js", "three-fx.js"}, "sources.json décrit les deux bibliothèques", manifest)
for name, meta in manifest.items():
    path = VUE / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    check(digest == meta.get("sha256"), f"{name} : empreinte SHA-256 conforme à sources.json", digest)
    check(meta.get("licence") in ("MIT", "ISC", "BSD-3-Clause", "Apache-2.0"), f"{name} : licence permissive", meta)
fg = manifest.get("3d-force-graph.min.js", {})
check(fg.get("sha256") == fg.get("sha256_source"), "3d-force-graph.min.js est le fichier du paquet npm, tel quel")
tv = manifest.get("three-fx.js", {}).get("version", "")
fgtext = (VUE / "3d-force-graph.min.js").read_text(encoding="utf-8") if (VUE / "3d-force-graph.min.js").is_file() else ""
revs = set(re.findall(r'const [A-Za-z_$][\w$]*="(\d{3})",', fgtext))
check(tv.count(".") == 2 and revs == {tv.split(".")[1]}, "three-fx.js a la révision de three.js que 3d-force-graph embarque",
      (tv, revs))
lic = (VUE / "LICENCES.md").read_text(encoding="utf-8") if (VUE / "LICENCES.md").is_file() else ""
for want in ("3d-force-graph", "three", "d3-force-3d", "ngraph.graph", "## MIT", "## ISC", "## BSD-3-Clause",
             "Vasco Asturiano", "three.js authors", "Mike Bostock", "Andrei Kashcha", "Permission is hereby granted"):
    check(want in lic, f"LICENCES.md mentionne « {want} »")
for name in ("3d-force-graph.min.js", "three-fx.js"):
    text = (VUE / name).read_text(encoding="utf-8") if (VUE / name).is_file() else ""
    check(text and not re.search(r"</script|<!--|<script", text, re.I), f"{name} tient dans un <script> en ligne")
fx = (VUE / "three-fx.js").read_text(encoding="utf-8") if (VUE / "three-fx.js").is_file() else ""
check("__cerveauFX" in fx and not re.search(r"(?m)^\s*(?:import|export)\s*\{", fx),
      "three-fx.js est un script classique (aucun import/export de module, qui ne marcherait pas en file://)")
tpl = (VUE / "page.html").read_text(encoding="utf-8") if (VUE / "page.html").is_file() else ""
check(tpl and not re.search(r"https?://", tpl), "le gabarit ne nomme aucun site (ni CDN ni polices en ligne)",
      re.findall(r"https?://[^\s\"'`)]+", tpl)[:5])
check(all(tpl.count(h) == 1 for h in ("__DATA__", "__LIB_3D__", "__LIB_FX__")), "le gabarit a ses trois trous, une fois chacun")
check("jsdelivr" not in tpl and "unpkg" not in tpl and "esm.sh" not in tpl and "import(" not in tpl,
      "aucun chargement depuis jsdelivr, unpkg ou esm.sh")

# ---------------------------------------------------------------------------------------------- page générée
with Brain.edit() as b:
    b.add("fact", "Le site vitrine utilise Astro", body="Un détail.")
    b.add("fact", "Titre piégé </script><script>alert(1)</script>", body="<!-- et un commentaire")
html_path = viz.render()
html = Path(html_path).read_text(encoding="utf-8")
check("ForceGraph3D" in html and "__cerveauFX" in html, "cerveau.html intègre les deux bibliothèques")
check(not re.search(r"<script[^>]*\bsrc=", html, re.I), "cerveau.html ne charge aucun script de l'extérieur (aucun src=)")
check(not re.search(r"<link[^>]*href=[\"']?https?:", html, re.I), "cerveau.html ne charge aucune feuille ni police en ligne")
opens, closes = len(re.findall(r"<script\b", html, re.I)), len(re.findall(r"</script>", html, re.I))
check(opens == closes == 4, "chaque <script> de la page se ferme où il doit (titre piégé échappé)", (opens, closes))
data_txt = html[html.index("const DATA = "):html.index("</script>", html.index("const DATA = "))]
check("alert(1)" in data_txt and not re.search(r"<!--|<script|</", data_txt, re.I),
      "les données n'ont ni « <script », ni « </ », ni « <!-- » (titre piégé échappé)")
check(json.loads(data_txt[len("const DATA = "):].rstrip().rstrip(";"))["nodes"] is not None,
      "les données échappées restent du JSON valide")
check(len(html) > 1_500_000, "la page embarque bien le moteur (≈ 1,7 Mo)", len(html))

# bibliothèque absente (installation incomplète) : la page se fait quand même, et dit quoi faire
saved = dict(viz3d.LIBS)
viz3d.LIBS["LIB_3D"] = TMP / "absente.js"
try:
    broken = viz3d.page("{}")
finally:
    viz3d.LIBS.clear()
    viz3d.LIBS.update(saved)
check("__LIB_3D__" not in broken and "ForceGraph3D=" not in broken and "brain doctor" in broken,
      "bibliothèque absente : page faite quand même, avec le message qui dit quoi faire")

# ---------------------------------------------------------------------------------------------- distribution
files = selfupdate._code_files(CODE)
for rel in ("brainkit/vue3d/page.html", "brainkit/vue3d/3d-force-graph.min.js", "brainkit/vue3d/three-fx.js",
            "brainkit/vue3d/LICENCES.md", "brainkit/vue3d/sources.json"):
    check(rel in files, f"self-update copie {rel}")
from brainkit import publish  # noqa: E402

dest = TMP / "plugin"
subprocess.run(["git", "init", "-q", str(dest)], check=False, capture_output=True)
try:
    built = set(publish.build(dest, repo="destingood/cerveau-claude"))
except Exception as exc:  # noqa: BLE001
    built = set()
    check(False, "plugin construit", repr(exc))
for rel in ("brainkit/vue3d/page.html", "brainkit/vue3d/3d-force-graph.min.js", "brainkit/vue3d/three-fx.js",
            "brainkit/vue3d/LICENCES.md"):
    check(rel in built, f"le plugin construit contient {rel}")
check(not publish.secrets_in(dest), "contrôle de la publication : aucun secret ni e-mail", publish.secrets_in(dest)[:3])

# ---------------------------------------------------------------------------------------------- dans un navigateur
node = shutil.which("node")
probe = None
if node and not os.environ.get("CERVEAU_SANS_NAVIGATEUR"):
    try:
        r = subprocess.run([node, str(CODE / "tests" / "vue3d_navigateur.js"), str(html_path)], capture_output=True,
                           text=True, timeout=180, cwd=str(TMP))
        probe = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        probe = {"skip": repr(exc)}
if not probe or probe.get("skip"):
    SKIP.append("navigateur : " + ((probe or {}).get("skip") or "node absent"))
else:
    check(not probe.get("errors"), "navigateur : aucune erreur dans la console", probe.get("errors"))
    check(not probe.get("outside"), "navigateur : aucune requête vers l'extérieur (réseau coupé)", probe.get("outside"))
    check(probe.get("forceGraph") and probe.get("canvas") and probe.get("nodes", 0) > 0,
          "navigateur : le graphe est dessiné depuis le disque, hors ligne", probe)
    check(probe.get("fxActive") and probe.get("bloom"), "navigateur : effets et bloom actifs (three.js intégré)", probe)
    check(not probe.get("fallbackShown"), "navigateur : pas de message « vue 3D indisponible »", probe.get("fallbackText"))
    check(not any("Multiple instances" in w for w in probe.get("warnings", [])),
          "navigateur : un seul three.js déclaré (pas d'avertissement)", probe.get("warnings"))

for s in SKIP:
    print(f"· sauté : {s}")
print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
