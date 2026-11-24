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

# ---------------------------------------------------------------------------------------------- chronologie (étape 13)
def page_data(path):
    text = Path(path).read_text(encoding="utf-8")
    start = text.index("const DATA = ") + len("const DATA = ")
    return json.loads(text[start:text.index("</script>", start)].rstrip().rstrip(";"))


with Brain.edit() as b:
    ovh = b.add("decision", "Hébergement chez OVH", body="On héberge chez OVH.", nid="ovh",
                meta={"valid_from": "2026-03-01", "domaine": ["infra"]})
    scw = b.add("decision", "Hébergement chez Scaleway", body="On passe chez Scaleway.", nid="scw",
                meta={"valid_from": "2026-06-01", "niveau": "vision"})
    fac = b.add("fact", "Facture serveur de mai", body="Payée.", nid="facture")
    b.supersede("scw", "ovh", why="OVH trop cher")
    ovh["meta"]["valid_to"] = "2026-05-31"
    ovh["created"], scw["created"] = "2026-03-01T09:00:00", "2026-06-01T09:00:00"
    b.link("ovh", "facture")
    b.unlink("ovh", "facture")
    b.link("scw", "facture")
    b.unlink("scw", "facture")
    for e in b.data["ended_edges"]:
        if e["from"] == "scw":
            e["created"], e["ended"] = "2026-06-10", "2026-07-01"
    # étape 17 : un lien typé (flèche) et un lien « lié à » (sans flèche), tous deux d'aujourd'hui
    b.add("fact", "Serveur dédié de production", body="Le serveur.", nid="serveur")
    b.link("scw", "serveur", "uses")
    b.link("facture", "serveur")
OLD_REF = "af568b4"  # main à la 8.33.0, avant l'étape 13
v833 = TMP / "v833"
arch = subprocess.run(["git", "-C", str(CODE), "archive", OLD_REF, "brain.py", "brainkit"], capture_output=True)
if arch.returncode == 0:
    v833.mkdir()
    subprocess.run(["tar", "-x", "-C", str(v833)], input=arch.stdout, check=True)
    # le code de la 8.33.0 sur les skills d'aujourd'hui : le même cerveau des deux côtés (l'étape 18 en ajoute cinq,
    # qui sont des nœuds de la vue ; seul le code doit différer)
    shutil.copytree(CODE / "skills", v833 / "skills", ignore=shutil.ignore_patterns("__pycache__"))
    r = subprocess.run([sys.executable, "-I", "-S", str(v833 / "brain.py"), "viz"], capture_output=True, env=os.environ.copy(),
                       timeout=300)
    old_data = page_data(viz.VIZ_FILE) if r.returncode == 0 else None
    check(old_data is not None, "8.33.0 : sa vue du même cerveau est faite", r.stderr.decode("utf-8", "replace")[-500:])
else:
    old_data = None
    check(False, f"code de la 8.33.0 ({OLD_REF}) introuvable dans l'historique git : `git fetch --unshallow`")
chrono_path = viz.render()
d = page_data(chrono_path)
past = {n["id"]: n for n in d.get("past", [])}
present = {n["id"]: n for n in d["nodes"]}
check("ovh" in past and "ovh" not in present and past["ovh"].get("sb") == "scw" and past["ovh"].get("why") == "OVH trop cher"
      and past["ovh"].get("vt") == "2026-05-31" and past["ovh"].get("dom") == "infra",
      "données : le souvenir remplacé est dans le passé, avec fin, raison, remplaçant et domaine", past.get("ovh"))
check(present.get("scw", {}).get("vf") == "2026-06-01" and present["scw"].get("niv") == "vision",
      "données : le présent porte son début et son niveau corrigé", present.get("scw"))
ended = [e for e in d.get("pastEdges", []) if e.get("e")]
check(any(e["s"] == "scw" and e["t"] == "facture" and e["c"] == "2026-06-10" and e["e"] == "2026-07-01" for e in ended),
      "données : un lien terminé, avec sa création et sa fin", d.get("pastEdges"))
check(not any(e["s"] == "ovh" or e["t"] == "ovh" for e in d["edges"]) and not any(
      e["s"] == "scw" and e["t"] == "facture" for e in d["edges"]), "données : DATA.edges ne garde que le présent")
if old_data is not None:
    check({n["id"] for n in old_data["nodes"]} == set(present),
          "mêmes souvenirs qu'en 8.33.0 dans DATA.nodes (la vue 2D et le tableau ne voient que le présent)",
          sorted({n["id"] for n in old_data["nodes"]} ^ set(present)))
    check({(e["s"], e["t"], e["r"]) for e in old_data["edges"]} == {(e["s"], e["t"], e["r"]) for e in d["edges"]},
          "mêmes liens qu'en 8.33.0 dans DATA.edges")
    check(old_data.get("stats") == d.get("stats"), "mêmes compteurs qu'en 8.33.0", (old_data.get("stats"), d.get("stats")))
check(any(e["s"] == "scw" and e["t"] == "serveur" and e["r"] == "uses" and e.get("c") for e in d["edges"])
      and any(e["s"] == "facture" and e["t"] == "serveur" and e["r"] == "relates" for e in d["edges"]),
      "données : un lien typé daté et un lien « lié à » (flèches et survol de l'étape 17)", d["edges"])
check(len(json.dumps(d.get("past"))) + len(json.dumps(d.get("pastEdges"))) < 20_000,
      "le passé pèse peu dans la page (quelques souvenirs ici)")

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

if node and not os.environ.get("CERVEAU_SANS_NAVIGATEUR") and not (probe or {}).get("skip"):
    try:
        r = subprocess.run([node, str(CODE / "tests" / "vue3d_chronologie.js"), str(chrono_path)], capture_output=True,
                           text=True, timeout=180, cwd=str(TMP))
        ch = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        ch = {"errors": [repr(exc)]}
    check(not ch.get("errors"), "chronologie : aucune erreur", ch.get("errors"))
    check(ch.get("todayExtra") == [] and ch.get("todayMissing") == [] and ch.get("todayPastLinks") == 0
          and ch.get("todayLinks") == ch.get("presentLinks"),
          "curseur à droite : exactement le présent (mêmes souvenirs et liens qu'en 8.33.0, rien du passé)", ch)
    pc = ch.get("pastCase") or {}
    check(pc.get("old") == "ovh" and pc.get("oldShown") and pc.get("replacement") == "scw" and not pc.get("replacementShown"),
          "à une date passée : le souvenir remplacé depuis est visible, son remplaçant pas encore", pc)
    check(ch.get("endedLink") == {"aliveBefore": True, "aliveAfter": False},
          "un lien terminé : visible avant sa fin, plus après", ch.get("endedLink"))
    check("dom" in (ch.get("layers") or []) and "heat" in (ch.get("layers") or []),
          "couleurs « domaine » et « chaleur », et le bouton des couches", ch.get("layers"))
    check(ch.get("layered") is True and ch.get("unlayered") is True,
          "couches : chaque souvenir à la hauteur de son niveau, puis libéré", (ch.get("layered"), ch.get("unlayered")))
    check(ch.get("legendDom") == "d:infra", "couleur « domaine » : le domaine écrit du souvenir", ch.get("legendDom"))
    check(isinstance(ch.get("afterPlay"), dict) and ch.get("settled") == 0,
          "lecture ▶ : jouée puis arrêtée sans erreur, plus aucun nœud en cours d'extinction ensuite", ch)

# ---------------------------------------------------------------------------------------------- vue 3D, suite (étape 17)
check(tpl.count("onNodeDragEnd(") == 1 and "pauseAnimation()" in tpl and "resumeAnimation()" in tpl
      and "linkDirectionalArrowLength(" in tpl and "linkLabel(" in tpl and 'id="orbBtn"' in tpl and 'id="pinBtn"' in tpl,
      "gabarit : flèches, étiquette des liens, nœuds posés, orbite et pause de l'onglet caché branchées")
if node and not os.environ.get("CERVEAU_SANS_NAVIGATEUR") and not (probe or {}).get("skip"):
    try:
        r = subprocess.run([node, str(CODE / "tests" / "vue3d_suite.js"), str(chrono_path)], capture_output=True,
                           text=True, timeout=240, cwd=str(TMP))
        su = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        su = {"errors": [repr(exc)]}
    check(not su.get("errors"), "suite : aucune erreur", su.get("errors"))
    ar = su.get("arrows") or {}
    check((ar.get("typed") or 0) > 0 and ar.get("relates") == 0 and ar.get("inf") == 0 and ar.get("con") == 0
          and ar.get("relPos") == 1 and ar.get("color"),
          "flèches : sur un lien typé (« utilise »), pas sur « lié à », ni sur les liens déduits ou les concepts", ar)
    check(ar.get("typedObj") is True and ar.get("relatesObj") is False,
          "flèches : le cône est dessiné pour le lien typé, aucun pour « lié à »", ar)
    created = (su.get("created") or "")[:10]
    fr_created = f"{created[8:10]}/{created[5:7]}/{created[:4]}"
    check("utilise" in (su.get("tipTyped") or "") and f"créé le {fr_created}" in (su.get("tipTyped") or "")
          and "terminé" not in (su.get("tipTyped") or ""),
          "survol d'un lien : son type et sa date de création", su.get("tipTyped"))
    check("lié à" in (su.get("tipEnded") or "") and "créé le 10/06/2026" in (su.get("tipEnded") or "")
          and "terminé le 01/07/2026" in (su.get("tipEnded") or ""),
          "survol d'un lien terminé : son type, sa création et sa fin", su.get("tipEnded"))
    check(su.get("hover") == {"on": True, "bigger": True, "off": True}, "survol d'un lien : il s'allume, puis s'éteint", su.get("hover"))
    check(any(h and h.startswith("uses | ") and "utilise" in h for h in su.get("realHover") or []),
          "vrai survol à la souris d'un lien : son étiquette s'affiche (les halos des nœuds ne le masquent pas)", su.get("realHover"))
    rg = su.get("realDrag") or {}
    check(rg.get("pinned") is True and rg.get("others") == [] and rg.get("controls") is True and rg.get("released") == 1
          and rg.get("errors") == 0,
          "vrai glisser à la souris : le nœud reste posé, la caméra se pilote encore, aucune erreur", rg)
    dr = su.get("drag") or {}
    check(dr.get("fx") == 123 and dr.get("fy") == 45 and dr.get("fz") == -67 and dr.get("button") is True
          and dr.get("stayed") == "123,45,-67", "nœud lâché : il reste où on le pose (fx, fy, fz)", dr)
    lay = dr.get("layered") or {}
    check(lay.get("fy") == lay.get("level") and lay.get("fx") == 123 and lay.get("fz") == -67 and dr.get("unlayered") == 45,
          "nœud posé et couches : sa hauteur suit son niveau, puis il retrouve la sienne", dr)
    check(dr.get("released") == {"fx": True, "fy": True, "fz": True, "pin": True, "button": True} and dr.get("dblclick") is True,
          "nœuds posés : libérés par le bouton, et par un double-clic sur le fond", dr)
    ob = su.get("orbit") or {}
    check("Orbite (vidéo)" in (ob.get("tip") or "") and ob.get("pressed") == "true" and ob.get("controlsOff") is True
          and ob.get("turned") is True and ob.get("steady") is True,
          "orbite : la caméra tourne seule autour du cerveau, à distance constante", ob)
    check(ob.get("released") is True and ob.get("stopped") is True, "orbite : arrêtée en douceur, la souris reprend la caméra", ob)
    check(ob.get("fxOff") == {"orbit": False, "disabled": True, "controls": True} and ob.get("fxBack") is True,
          "orbite : coupée avec les effets", ob)
    rd = su.get("reduced") or {}
    check(rd.get("disabled") is True and rd.get("started") is False and rd.get("orbit") is False
          and "moins d'animations" in (rd.get("tip") or ""),
          "orbite : jamais quand le système demande moins d'animations", rd)
    vi = su.get("visibility") or {}
    check(vi.get("paused") is True and vi.get("raf") == 0 and vi.get("frozen") is True and vi.get("pause") == 1,
          "onglet caché : boucle d'animation et rendu de 3d-force-graph en pause (une seule fois)", vi)
    check(vi.get("resumed") is True and vi.get("running") is True and vi.get("resume") == 1,
          "onglet revenu : tout reprend", vi)
else:
    SKIP.append("navigateur : vue 3D, suite (étape 17)")

for s in SKIP:
    print(f"· sauté : {s}")
print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
