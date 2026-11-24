"""Le temps dans le graphe (étape 11 du plan, temps.py) : début et fin de validité, liens terminés, lignée d'un
remplacement et sa raison, domaine et niveau, le cerveau à une date sans instantané, le même aller-retour en mode wiki,
et la compatibilité avec la 8.33.0 dans les deux sens (son code est tiré de l'historique git). Tout se passe dans un
dossier temporaire.

Lancement : python tests/test_temps.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-temps-test-"))
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "BRAIN_HOME": str(TMP / "brain"), "PYTHONUTF8": "1"})
WORK = TMP / "travail"
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))
OK, FAIL = [], []

from brainkit import dates, mcp_server, temps  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-900:]}" if detail else ""))


def run(code_dir, *args, home=None):
    env = dict(os.environ)
    if home:
        env["BRAIN_HOME"] = str(home)
    r = subprocess.run([sys.executable, "-I", "-S", str(code_dir / "brain.py"), *args], capture_output=True,
                       cwd=str(WORK), env=env, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def brain(*args, home=None):
    return run(CODE, *args, home=home)


TODAY = dt.date.today()


def ago(days):
    return (TODAY - dt.timedelta(days=days)).isoformat()


def graph(home=None):
    return json.loads(((home or TMP / "brain") / "graph.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 1. dates
T = dt.date(2026, 11, 24)
check(dates.parse("01/09", T, nearest=True) == "2026-09-01" and dates.parse("01/09", T) == "2027-09-01",
      "« depuis le 01/09 » dit le 24/11 : le 01/09 passé (une échéance, elle, reste la prochaine)")
check(dates.parse("20/12", T, nearest=True) == "2026-12-20" and dates.parse("30/02", T, nearest=True) is None,
      "date la plus proche : un début à venir reste possible, une date impossible est refusée")

# ------------------------------------------------------------------ 2. un graphe de la 8.33.0 se charge sans être réécrit
home = TMP / "brain"
home.mkdir(parents=True)
old_graph = {"version": 1, "created": "2026-03-01T09:00:00", "edges": [
    {"from": "a", "to": "b", "rel": "relates", "created": "2026-03-01"}], "nodes": {
    nid: {"id": nid, "type": "fact", "title": title, "body": body, "tags": [], "project": None, "importance": 3,
          "created": "2026-03-01T09:00:00", "updated": "2026-03-01T09:00:00", "hits": 0, "last_hit": None,
          "source": "utilisateur", "status": "active", "meta": {}}
    for nid, title, body in (("a", "Thé vert du matin", "Je bois du sencha le matin."),
                             ("b", "Thé noir le soir", "Du darjeeling après dîner."))}}
(home / "graph.json").write_text(json.dumps(old_graph, ensure_ascii=False, indent=1), encoding="utf-8")
before = (home / "graph.json").read_bytes()
c, out = brain("show", "a")
c2, out2 = brain("q", "thé", "--no-files")
check(c == 0 and c2 == 0 and "valable depuis le 01/03/2026" in out and "niveau détail" in out,
      "graphe 8.33.0 : `show` donne la validité et le niveau déduits", out)
check((home / "graph.json").read_bytes() == before, "graphe 8.33.0 : lu sans être réécrit (rien n'est migré)")

# ------------------------------------------------------------------ 3. début, fin, niveau, domaine
c, out = brain("add", "-t", "fact", "-T", "Promo de Noël", "-b", "Remise de 10 % sur tout.", "-p", "none",
               "--depuis", "01/12", "--jusqu", "31/12", "--niveau", "procédure", "--id", "promo")
n = graph()["nodes"].get("promo", {})
check(c == 0 and n.get("status") == "active" and (n.get("meta") or {}).get("valid_to", "").endswith("-12-31")
      and n["meta"].get("niveau") == "procedure" and n["meta"].get("valid_from", "").endswith("-12-01"),
      "add --depuis --jusqu --niveau : dates et niveau gardés, actif jusqu'à la fin", out + json.dumps(n))
c, out = brain("add", "-t", "fact", "-T", "Tarif d'avant", "-b", "29 euros.", "-p", "none", "--jusqu", "hier")
check(c != 0 and "avant le début" in out and "Tarif d'avant" not in json.dumps(graph()),
      "fin avant le début (sans --depuis, le début est aujourd'hui) : refusé, rien n'est enregistré", out)
c, out = brain("add", "-t", "fact", "-T", "Date folle", "-b", "x", "-p", "none", "--depuis", "le jour d'après")
check(c != 0 and "illisible" in out, "date illisible : refusée", out)
c, out = brain("edit", "promo", "--niveau", "galaxie")
check(c != 0 and "niveau inconnu" in out and "vision" in out, "niveau inconnu : refusé, les niveaux sont listés", out)
c, out = brain("add", "-t", "fact", "-T", "Tarif d'avant", "-b", "29 euros.", "-p", "none", "--depuis", ago(60),
               "--jusqu", ago(1), "--id", "tarif")
check(c == 0 and graph()["nodes"]["tarif"]["status"] == "active", "fin déjà passée à l'ajout : actif jusqu'à l'entretien", out)
c, out = brain("consolidate")
g = graph()
check("vrai jusqu'au" in out and g["nodes"]["tarif"]["status"] == "archived" and g["nodes"]["promo"]["status"] == "active",
      "entretien du jour : fin passée → archivé ; fin à venir → reste actif", out)
c, out = brain("edit", "promo", "--jusqu", ago(2))
check(c != 0 and "avant le début" in out and graph()["nodes"]["promo"]["status"] == "active",
      "edit --jusqu avant le --depuis déjà posé : refusé, rien ne change", out)
c, out = brain("edit", "promo", "--depuis", ago(10), "--jusqu", ago(2))
check(c == 0 and graph()["nodes"]["promo"]["status"] == "archived", "edit --jusqu dans le passé : archivé tout de suite", out)
brain("edit", "promo", "--jusqu", "none", "--unarchive")
check(graph()["nodes"]["promo"]["status"] == "active" and "valid_to" not in graph()["nodes"]["promo"]["meta"],
      "edit --jusqu none --unarchive : sans fin, de nouveau actif")

nodes = {"p": {"id": "p", "type": "project", "meta": {"domaine": ["code"]}},
         "x": {"id": "x", "type": "decision", "project": "p", "meta": {}},
         "y": {"id": "y", "type": "learning", "project": "p", "meta": {"domaine": ["infra"], "niveau": "detail"}},
         "u": {"id": "u", "type": "user", "meta": {}}}
check(temps.axes(nodes["x"], nodes) == ("code", "architecture"), "axes : décision → architecture, domaine du projet")
check(temps.axes(nodes["y"], nodes) == ("infra", "detail"), "axes : domaine et niveau écrits sur le souvenir priment")
check(temps.axes(nodes["u"], nodes) == (None, "vision") and temps.axes(nodes["p"], nodes) == ("code", "vision"),
      "axes : profil et projet → vision")

# ------------------------------------------------------------------ 4. remplacement, raison, lignée
brain("add", "-t", "decision", "-T", "Hébergement chez OVH", "-b", "On héberge chez OVH.", "-p", "none",
      "--depuis", ago(120), "--id", "ovh")
brain("add", "-t", "decision", "-T", "Hébergement chez Scaleway", "-b", "On passe chez Scaleway.", "-p", "none",
      "--replaces", "ovh", "--parce-que", "OVH trop cher pour le stockage", "--id", "scw")
c, out = brain("add", "-t", "decision", "-T", "Hébergement chez Hetzner", "-b", "On passe chez Hetzner.", "-p", "none",
               "--id", "htz")
c, out = brain("supersede", "htz", "scw", "--parce-que", "Scaleway en panne trois fois")
g = graph()
check(c == 0 and g["nodes"]["scw"]["meta"].get("end_reason") == "Scaleway en panne trois fois"
      and g["nodes"]["ovh"]["meta"].get("end_reason") == "OVH trop cher pour le stockage",
      "supersede --parce-que et add --replaces --parce-que : la raison est gardée sur l'ancien", out)
c, out = brain("show", "ovh")
line = next((x for x in out.splitlines() if x.startswith("↻ lignée")), "")
check(line.index("`htz`") < line.index("`scw`") < line.index("`ovh`") and "parce que Scaleway en panne" in line
      and "parce que OVH trop cher" in line and "depuis le" in line.split("←")[0],
      "lignée dans show : du plus récent au plus ancien, avec dates et raisons", out)
check(f"du {ago(120)[8:10]}/{ago(120)[5:7]}/{ago(120)[:4]}" in line, "lignée : le début de validité donné à l'ajout", line)

# ------------------------------------------------------------------ 5. liens terminés
brain("link", "htz", "promo")
c, out = brain("unlink", "htz", "promo")
g = graph()
ended = [e for e in g.get("ended_edges", []) if e["from"] == "htz" and e["to"] == "promo"]
check(c == 0 and ended and ended[0]["ended"] == TODAY.isoformat() and not any(
      e["from"] == "htz" and e["to"] == "promo" for e in g["edges"]),
      "unlink : le lien n'est pas effacé, il devient un lien terminé daté du jour", out + json.dumps(g.get("ended_edges")))
from brainkit.store import Brain  # noqa: E402
b = Brain.load()
check(not any(m["id"] == "promo" for m, _, _ in b.neighbors("htz")) and any(
      e["to"] == "promo" for e in b.all_edges if e["from"] == "htz"),
      "Brain.edges et les voisins ne voient plus le lien terminé ; Brain.all_edges le garde")
from brainkit import graph as gr  # noqa: E402
an = gr.analyze(b) if hasattr(gr, "analyze") else gr.ensure(b, wait=True)
check(not an.get("deg", {}).get("promo"), "l'analyse du graphe (degré) ne compte pas le lien terminé", an.get("deg"))
c, out = brain("show", "htz")
check("promo" not in out.split("Liens :")[-1].split("\n\n")[0] if "Liens :" in out else True,
      "show : un lien terminé n'est plus listé dans les liens", out)
brain("add", "-t", "fact", "-T", "Note à jeter", "-b", "rien", "-p", "none", "--id", "jet")
brain("link", "jet", "htz")
brain("unlink", "jet", "htz")
brain("rm", "jet", "--purge")
check(not any("jet" in (e["from"], e["to"]) for e in graph().get("ended_edges", [])),
      "suppression définitive : ses liens terminés partent avec lui")

# ------------------------------------------------------------------ 6. le cerveau il y a six mois, sans instantané
six = ago(182)
g = graph()
for nid, start, end, status, extra in (("vieux", ago(300), ago(100), "archived", {"superseded_by": "neuf"}),
                                       ("neuf", ago(100), None, "active", {}),
                                       ("lien", ago(300), None, "active", {})):
    g["nodes"][nid] = {"id": nid, "type": "decision", "title": f"Fournisseur de colis {nid}",
                       "body": f"Les colis partent avec le transporteur {nid}.", "tags": [], "project": None,
                       "importance": 3, "created": start + "T09:00:00", "updated": (end or start) + "T09:00:00",
                       "hits": 0, "source": "utilisateur", "status": status,
                       "meta": dict(extra, **({"valid_to": end} if end else {}))}
g["edges"].append({"from": "neuf", "to": "vieux", "rel": "supersedes", "created": ago(100)})
g.setdefault("ended_edges", []).append({"from": "lien", "to": "vieux", "rel": "relates", "created": ago(250),
                                        "ended": ago(150)})
(home / "graph.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
state = temps.state_on(g, six)
check("vieux" in state["nodes"] and "neuf" not in state["nodes"] and state["nodes"]["vieux"]["status"] == "active",
      "state_on il y a six mois : le souvenir remplacé depuis est là (actif), son remplaçant pas encore")
check(any(e["from"] == "lien" and e["to"] == "vieux" for e in state["edges"]) and not any(
      e["from"] == "neuf" for e in state["edges"]), "state_on : le lien terminé depuis existait, le lien à venir non")
check("promo" not in temps.state_on(g, ago(400))["nodes"], "state_on : un souvenir pas encore valable est absent")
for f in (home / "history").glob("graph-*.json.gz"):
    f.unlink()
c, out = brain("q", "transporteur colis", "--at", six)
check(c == 0 and "reconstruit d'après les dates" in out and "vieux" in out and "`neuf`" not in out,
      "q --at il y a six mois sans instantané : répond, reconstruit d'après les dates, et le dit", out)
c, out = brain("q", "transporteur colis")
check("`neuf`" in out and "`vieux`" not in out, "aujourd'hui : seul le remplaçant est rappelé", out)
day_month = f"{T.day:02d}/{T.month:02d}"
check(dates.parse(day_month, T, nearest=True) == T.isoformat(), "--at sans année : la date la plus proche")

# ------------------------------------------------------------------ 7. serveur MCP : « at », et une liste qui ne s'allonge pas
size = len(json.dumps({"tools": mcp_server.tools({})}, ensure_ascii=False, separators=(",", ":")))
check(size <= 3204, f"outils MCP de la mémoire : {size} caractères, pas plus qu'en 8.33.0 (3 204)", size)
search_tool = next(t for t in mcp_server.tools({}) if t["name"] == "memory_search")
check("at" in search_tool["inputSchema"]["properties"], "memory_search accepte « at »")
res = mcp_server.call_tool("memory_search", {"query": "transporteur colis", "at": six})
text = json.dumps(res, ensure_ascii=False)
check("reconstruit" in text and "vieux" in text, "memory_search avec « at » : le cerveau de cette date", text[:600])

# ------------------------------------------------------------------ 8. la 8.33.0 lit un graphe récent sans le casser
OLD_REFS = ("cerveau--v8.33.0", "af568b4")


def old_code():
    for ref in OLD_REFS:
        if subprocess.run(["git", "-C", str(CODE), "cat-file", "-e", f"{ref}:brainkit/temps.py"],
                          capture_output=True).returncode == 0:
            continue  # pas la 8.33.0
        r = subprocess.run(["git", "-C", str(CODE), "archive", ref, "brain.py", "brainkit"], capture_output=True)
        if r.returncode == 0:
            dest = TMP / "v833"
            dest.mkdir()
            with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
                try:
                    tar.extractall(dest, filter="data")
                except TypeError:  # Python 3.10 et 3.11 sans le filtre
                    tar.extractall(dest)
            return dest
    sys.exit("✗ code de la 8.33.0 introuvable dans ce dépôt (" + ", ".join(OLD_REFS) + ") : `git fetch --unshallow`")


V833 = old_code()
c, out = run(V833, "show", "ovh")
check(c == 0 and "Hébergement chez OVH" in out, "8.33.0 : lit un souvenir du graphe récent", out)
c, out = run(V833, "add", "-t", "fact", "-T", "Écrit par la 8.33.0", "-b", "Un fait ajouté par l'ancienne version.",
             "-p", "none")
g = graph()
check(c == 0 and any(e["from"] == "htz" and e["to"] == "promo" for e in g.get("ended_edges", []))
      and g["nodes"]["ovh"]["meta"].get("end_reason") and g["nodes"]["promo"]["meta"].get("niveau"),
      "8.33.0 : son écriture garde les liens terminés, la raison et le niveau", out)
c, out = brain("show", "ovh")
check(c == 0 and "↻ lignée" in out, "après l'écriture de la 8.33.0 : la lignée est toujours là", out)

# ------------------------------------------------------------------ 9. mode wiki : l'aller-retour page ↔ graphe
WHOME = TMP / "brain-wiki"
WIKI = TMP / "wiki"
c, out = brain("wiki", "init", str(WIKI), home=WHOME)
check(c == 0, "wiki : créé", out)
for args in (("add", "-t", "decision", "-T", "Hébergement chez OVH", "-b", "On héberge chez OVH.", "-p", "none",
              "--depuis", ago(90), "--id", "ovh"),
             ("add", "-t", "decision", "-T", "Hébergement chez Scaleway", "-b", "On passe chez Scaleway.", "-p", "none",
              "--replaces", "ovh", "--parce-que", "OVH trop cher", "--niveau", "vision", "--id", "scw"),
             ("add", "-t", "fact", "-T", "Budget serveurs", "-b", "200 euros par mois. Voir [[Hébergement chez Scaleway]].",
              "-p", "none", "--jusqu", "31/12", "--id", "budget"),
             ("add", "-t", "fact", "-T", "Facture d'octobre", "-b", "Payée.", "-p", "none", "--id", "facture"),
             ("link", "scw", "facture"), ("unlink", "scw", "facture")):
    c, out = brain(*args, home=WHOME)
    check(c == 0, f"wiki : {' '.join(args[:2])}", out)


def wpage(title):
    hits = sorted(WIKI.rglob(f"{title}*.md"))
    return hits[0].read_text(encoding="utf-8") if hits else ""


p_ovh, p_scw = wpage("Hébergement chez OVH"), wpage("Hébergement chez Scaleway")
check(f"debut: {ago(90)}" in p_ovh and "raison_fin: \"OVH trop cher\"" in p_ovh and "fin: " in p_ovh,
      "page : début, fin et raison écrits en propriétés", p_ovh)
check("niveau: vision" in p_scw and f"anciens_liens: [\"lie_a · facture · {TODAY} → {TODAY}\"]" in p_scw
      and "[[Facture" not in p_scw, "page : niveau et lien terminé (en texte, pas en [[lien]] vivant)", p_scw)
before = graph(WHOME)
(WHOME / "graph.json").unlink()
for f in WHOME.rglob("wiki-pages.json"):
    f.unlink()
c, out = brain("show", "ovh", home=WHOME)
after = graph(WHOME)
check(after.get("ended_edges") == before.get("ended_edges") and after["nodes"]["ovh"]["meta"] == before["nodes"]["ovh"]["meta"]
      and after["nodes"]["scw"]["meta"].get("niveau") == "vision",
      "cache refait depuis les seules pages : dates, raison, niveau et liens terminés reviennent",
      json.dumps([before.get("ended_edges"), after.get("ended_edges")]))
check("↻ lignée" in out and "parce que OVH trop cher" in out, "wiki : la lignée se lit depuis les pages", out)
bud = next(WIKI.rglob("Budget serveurs*.md"))
bud.write_text(bud.read_text(encoding="utf-8").replace(" Voir [[Hébergement chez Scaleway]].", ""), encoding="utf-8")
brain("show", "budget", home=WHOME)
check(any(e["from"] == "budget" and e["to"] == "scw" and e["ended"] == TODAY.isoformat()
          for e in graph(WHOME).get("ended_edges", [])),
      "lien retiré à la main dans Obsidian : devenu un lien terminé à la lecture suivante")
brain("add", "-t", "fact", "-T", "Une autre note", "-b", "Rien de plus.", "-p", "none", home=WHOME)
check("anciens_liens: [\"lie_a · scw ·" in wpage("Budget serveurs"),
      "… et écrit dans sa page à l'écriture suivante (il survit à une reconstruction du cache)", wpage("Budget serveurs"))

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
