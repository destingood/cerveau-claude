"""Chemin d'écriture du cerveau (étape 4 du plan, « Vitesse ») : `brain add` n'écrit que le graphe, ses vues (BRAIN.md,
MEMOIRES.md, cerveau.html, cerveau-2d.html) se refont en arrière-plan une fois les écritures calmées, et identiques à
ce qu'elles auraient été ; les compteurs de rappel vont dans un petit fichier à part (graph.json n'est plus réécrit à
chaque rappel, l'index n'est plus refait pour un rappel, rien n'est compté deux fois) ; les mots de chaque souvenir sont
gardés d'une commande à l'autre, et les liens suggérés par `add` restent ceux de l'analyse complète du graphe.

Lancement : python tests/test_ecriture.py   (sortie : « N vérifications OK, M échec(s) »)"""
import contextlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-ecriture-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")  # import en direct de brainkit : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "brain")
os.environ["BRAIN_OFFLINE"] = "1"
WORK = TMP / "travail"  # dossier courant hors de tout projet et de tout wiki
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))

from brainkit import graph, index, store, viz  # noqa: E402
from brainkit.common import (EXPORT_FILE, GRAPH_FILE, INDEX_FILE, STATE_DIR, VIZ2D_FILE, VIZ_FILE, FileLock,  # noqa: E402
                             remove_tree)
from brainkit.store import Brain  # noqa: E402

try:  # modules de l'étape 4 : absents du code d'avant, dont chaque vérification ci-dessous doit alors échouer
    from brainkit import mots, vues
except ImportError:
    mots = vues = None


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def verify(label, fn):
    """fn() → booléen, ou (booléen, détail). Une exception (fonction absente du code d'avant…) compte comme un échec."""
    try:
        res = fn()
    except Exception as exc:
        check(False, label, repr(exc))
        return
    cond, detail = res if isinstance(res, tuple) else (res, "")
    check(bool(cond), label, detail)


def brain(*args, env=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       cwd=str(WORK), env=env or os.environ, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def viz_data(path):
    """Données d'une vue (cerveau.html ou cerveau-2d.html), sans leur heure de génération."""
    html = read(path)
    try:
        data = json.JSONDecoder().raw_decode(html[html.index('{"generated"'):].replace("<\\/", "</"))[0]
    except ValueError:
        return None
    data.pop("generated", None)
    return data


def wait_views():
    """Vues demandées refaites (la tâche de fond, ou ici si personne ne s'en charge)."""
    return vues.wait(120) if vues else False


# ------------------------------------------------------------------ 0. un cerveau au vocabulaire réaliste
# Sept sujets aux mots bien à eux, des mots communs à tous : l'analyse du graphe en tire de vrais liens déduits.
SUJETS = {
    "boutique": "shopify thème panier produit collection variante stock commande remise paiement",
    "livraison": "colissimo transporteur relais expédition colis suivi délai étiquette mondial frais",
    "seo": "référencement balise sitemap backlinks indexation google console vitesse canonique robots",
    "python": "script fonction module pytest exception boucle fichier chemin encodage unicode",
    "factures": "facture devis tva comptable relance échéance avoir montant acompte règlement",
    "youtube": "vidéo miniature chaîne abonnés montage tournage audience description sous-titres playlist",
    "pc": "windows pilote bios processeur carte ventilateur température disque partition firmware",
}
COMMUNS = "vérifier toujours projet semaine important noter rapide simple propre tester mesurer garder".split()
rng = random.Random(20261121)
DATE = "2026-10-01T09:00:00"


def memory(i, sujet, other=None):
    words = SUJETS[sujet].split()
    title = " ".join(rng.sample(words, rng.randint(2, 4))).capitalize() + f" ({sujet} {i})"
    pool = words * 3 + (SUJETS[other].split() if other else []) + COMMUNS * 2
    body = " ".join(rng.choice(pool) for _ in range(rng.randint(10, 22))) + "."
    return title, body


nodes, edges = {}, []
for p in ("boutique", "youtube"):
    nodes[f"projet-{p}"] = {"id": f"projet-{p}", "type": "project", "title": f"Projet {p}", "body": SUJETS[p],
                            "tags": [], "project": None, "importance": 3, "created": DATE, "updated": DATE, "hits": 0,
                            "source": "utilisateur", "status": "active", "meta": {"path": str(TMP / p)}}
for i in range(150):
    sujet = list(SUJETS)[i % len(SUJETS)]
    title, body = memory(i, sujet, rng.choice([None, None, rng.choice(list(SUJETS))]))
    nid = f"s{i}"
    nodes[nid] = {"id": nid, "type": rng.choice(["fact", "learning", "decision", "reference", "todo"]), "title": title,
                  "body": body, "tags": rng.sample(["boutique", "client", "rapide", "outil", "prix"], rng.randint(0, 2)),
                  "project": f"projet-{sujet}" if sujet in ("boutique", "youtube") and i % 3 else None,
                  "importance": rng.randint(1, 5), "created": DATE, "updated": DATE, "hits": rng.randint(0, 3),
                  "source": "utilisateur", "status": "archived" if i % 29 == 0 else "active", "meta": {}}
for _ in range(60):
    a, b = rng.sample([f"s{i}" for i in range(150)], 2)
    edges.append({"from": a, "to": b, "rel": rng.choice(["relates", "depends_on", "uses"]), "created": DATE[:10]})
edges.append({"from": "s1", "to": "s1", "rel": "relates", "created": DATE[:10]})  # boucle et lien cassé : l'export
edges.append({"from": "s2", "to": "disparu", "rel": "relates", "created": DATE[:10]})  # les ignore comme avant
GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
GRAPH_FILE.write_text(json.dumps({"version": 1, "created": DATE, "nodes": nodes, "edges": edges}, ensure_ascii=False),
                      encoding="utf-8")

# ------------------------------------------------------------------ 1. add : le graphe seul, les vues en arrière-plan
code, out = brain("add", "-t", "learning", "-T", "Relais colissimo pour les colis lourds",
                  "-b", "Expédition des colis lourds : transporteur colissimo, relais mondial, suivi et délai notés.",
                  "-p", "none")
added = Brain.load().nodes.get("relais-colissimo-pour-les-colis-lourds")
check(code == 0 and "✓ mémorisé" in out and added is not None, "add : souvenir enregistré dans graph.json", out[-600:])
code, out = brain("vues", "--attendre")
check(code == 0 and "vues à jour" in out, "`brain vues --attendre` : attend que les vues demandées soient refaites", out)
verify("vues refaites après add : le nouveau souvenir dans MEMOIRES.md et dans les vues 3D et 2D",
       lambda: "### Relais colissimo pour les colis lourds" in read(EXPORT_FILE)
       and any(n["id"] == "relais-colissimo-pour-les-colis-lourds" for n in (viz_data(VIZ_FILE) or {}).get("nodes", []))
       and viz_data(VIZ2D_FILE) == viz_data(VIZ_FILE))
before_export, before_index, before_viz = read(EXPORT_FILE), read(INDEX_FILE), viz_data(VIZ_FILE)
b0 = Brain.load()
verify("vues de la tâche de fond identiques à une régénération immédiate (export, index, vue 3D)",
       lambda: (index.export(b0) == before_export and index.build_index(b0) == before_index
                and viz.render(b0) and viz_data(VIZ_FILE) == before_viz,
                [len(before_export), len(before_index), bool(before_viz)]))

# ------------------------------------------------------------------ 2. plusieurs add à la suite : une régénération
regens = []
if vues:
    real_spawn, real_regen = vues._spawn, vues.regenerate
    vues._spawn = lambda: True  # comme si la tâche détachée était partie, mais rien ne tourne : tout est observable

    def counting():
        regens.append(time.time())
        real_regen()
    vues.regenerate = counting
mtimes = {f: f.stat().st_mtime_ns if f.exists() else 0 for f in (EXPORT_FILE, VIZ_FILE, VIZ2D_FILE)}
from brainkit import cli  # noqa: E402
titles = ["Miniature youtube et playlist", "Sitemap et balise canonique", "Relance des factures avec acompte"]
for t in titles:
    with contextlib.redirect_stdout(io.StringIO()):
        cli.main(["add", "-t", "fact", "-T", t, "-b", f"{t} : à garder pour la semaine.", "-p", "none"])
verify("trois add de suite : graphe écrit, vues pas encore refaites (demandées)",
       lambda: (all(t in json.dumps(json.loads(read(GRAPH_FILE))["nodes"], ensure_ascii=False) for t in titles)
                and all((f.stat().st_mtime_ns if f.exists() else 0) == m for f, m in mtimes.items())
                and vues.pending() and not regens, vues and vues._state()))
verify("trois add de suite → une seule régénération, avec les trois souvenirs",
       lambda: (vues.wait(120) and len(regens) == 1 and all(f"### {t}" in read(EXPORT_FILE) for t in titles)
                and not vues.pending(), (len(regens), vues._state())))
if vues:
    vues._spawn, vues.regenerate = real_spawn, real_regen

# ------------------------------------------------------------------ 3. compteurs de rappel : à part de graph.json
wait_views()
X, Y = "s3", "s10"
g0 = GRAPH_FILE.read_bytes()
m0 = GRAPH_FILE.stat().st_mtime_ns
h0, u0 = Brain.load().nodes[X].get("hits", 0), Brain.load().nodes[X].get("used", 0) or 0
first = index.ensure_index(Brain.load())
INDEX_FILE.write_text(first + "\nMARQUEUR", encoding="utf-8")  # index à jour : relu tel quel tant que rien ne bouge
store.bump_hits([X, Y])
store.bump_used([X])
n1 = Brain.load().nodes
check(GRAPH_FILE.read_bytes() == g0 and GRAPH_FILE.stat().st_mtime_ns == m0,
      "un rappel ne réécrit plus graph.json (montré, utilisé)")
check(n1[X].get("hits") == h0 + 1 and (n1[X].get("used") or 0) == u0 + 1 and n1[X].get("last_hit")
      and n1[X].get("last_used"), "compteurs visibles à la lecture du graphe, comme avant",
      {k: n1[X].get(k) for k in ("hits", "used", "last_hit", "last_used")})
check(index.ensure_index(Brain.load()).endswith("MARQUEUR"), "un rappel ne fait plus refaire l'index BRAIN.md")
code, out = brain("show", X)  # (montre les compteurs, puis compte son propre affichage)
check(f"montré {h0 + 1}×" in out and f"utilisé {u0 + 1}×" in out, "`brain show` : compteurs à jour", out[:400])
verify("compteurs en attente dans state/compteurs.json", lambda: store.COUNTERS_FILE.is_file()
       and store._counters()["rows"])
with Brain.edit() as b:  # une vraie écriture : les compteurs entrent dans graph.json et quittent le fichier d'attente
    b.update(Y, body=b.nodes[Y]["body"] + " Vu.")
disk = json.loads(read(GRAPH_FILE))
verify("vraie écriture : compteurs écrits dans graph.json, plus rien en attente, rien compté deux fois",
       lambda: (disk["nodes"][X]["hits"] == h0 + 2 and disk["nodes"][X].get("used") == u0 + 1
                and not store._counters()["rows"] and Brain.load().nodes[X]["hits"] == h0 + 2,
                (disk["nodes"][X].get("hits"), store._counters())))


def crash_between():
    """Arrêt entre l'écriture de graph.json et le ménage du fichier d'attente : rien n'est compté deux fois."""
    store.bump_hits([X])
    b = Brain()
    data = b._own_data()
    data["compteurs"] = {"id": b._counted[0], "n": b._counted[1]}
    GRAPH_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")  # sans _settle_counters
    once = Brain.load().nodes[X]["hits"]
    with Brain.edit() as b2:
        b2.absorb_counters()
    return once == h0 + 3 and Brain.load().nodes[X]["hits"] == h0 + 3 and not store._counters()["rows"], once


verify("arrêt entre graph.json et le fichier d'attente : rien n'est compté deux fois", crash_between)
BUMP = ("import sys\nsys.path.insert(0, sys.argv[1])\nfrom brainkit import store\n"
        "for _ in range(10):\n    store.bump_hits([sys.argv[2]])\nfor _ in range(5):\n    store.bump_used([sys.argv[2]])\n")
h1, u1 = Brain.load().nodes[X]["hits"], Brain.load().nodes[X].get("used") or 0
g1 = GRAPH_FILE.read_bytes()
with FileLock(store.LOCK_FILE, timeout=10):  # graphe verrouillé (longue consolidation) : avant, ces rappels se perdaient
    procs = [subprocess.Popen([sys.executable, "-c", BUMP, str(CODE), X], env=os.environ) for _ in range(6)]
    for p in procs:
        p.wait(timeout=300)
    n2 = Brain.load().nodes[X]
check(n2["hits"] == h1 + 60 and (n2.get("used") or 0) == u1 + 30 and GRAPH_FILE.read_bytes() == g1,
      "rappels simultanés, graphe verrouillé : tous comptés, graph.json intact", (n2["hits"] - h1, (n2.get("used") or 0) - u1))
code, out = brain("consolidate", "--auto")
disk = json.loads(read(GRAPH_FILE))
verify("entretien du jour : les compteurs en attente écrits dans graph.json",
       lambda: (disk["nodes"][X]["hits"] == h1 + 60 and not store._counters()["rows"], disk["nodes"][X].get("hits")))
EDIT = ("import sys\nsys.path.insert(0, sys.argv[1])\nfrom brainkit.store import Brain\n"
        "for i in range(12):\n    with Brain.edit(timeout=60) as b:\n        b.update(sys.argv[2], body=f'version {i}')\n")
h2 = Brain.load().nodes[X]["hits"]
procs = [subprocess.Popen([sys.executable, "-c", BUMP, str(CODE), X], env=os.environ) for _ in range(3)]
procs.append(subprocess.Popen([sys.executable, "-c", EDIT, str(CODE), Y], env=os.environ))
for p in procs:
    p.wait(timeout=300)
disk = json.loads(read(GRAPH_FILE))
verify("rappels pendant des écritures du graphe : chacun compté une fois (graph.json + fichier d'attente)",
       lambda: (Brain.load().nodes[X]["hits"] == h2 + 30 and disk["nodes"][Y]["body"] == "version 11",
                (Brain.load().nodes[X]["hits"] - h2, disk["nodes"][Y]["body"])))

# ------------------------------------------------------------------ 4. mots gardés d'une commande à l'autre
wait_views()
for f in ("mots.bin", "termes.bin"):
    with contextlib.suppress(OSError):
        (STATE_DIR / f).unlink()
code, out = brain("add", "-t", "fact", "-T", "Pilote windows et firmware du bios", "-b",
                  "Le firmware du bios et le pilote windows : partition du disque vérifiée, température notée.", "-p", "none")
check(code == 0 and "✓ mémorisé" in out, "add sans mots gardés (premier après une mise à jour)", out[-400:])
check((STATE_DIR / "mots.bin").is_file() and (STATE_DIR / "termes.bin").is_file(),
      "premier add : les mots de tout le cerveau gardés pour les suivants (state/mots.bin, termes.bin)")
wait_views()


def primed():
    """Un cerveau relu : similar() part des mots gardés, sauf pour un souvenir modifié depuis (redécoupé)."""
    data = json.loads(read(GRAPH_FILE))
    data["nodes"]["s5"]["body"] = "Texte entièrement nouveau sur les pieuvres géantes du Pacifique et leurs ventouses."
    GRAPH_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    b = Brain.load()
    words = b._words()
    known, stale = len(words), "s5" in words
    hits = b.similar("Pieuvres géantes du Pacifique", "pieuvres géantes ventouses Pacifique", threshold=0.3)
    return known >= 100 and not stale and any(m["id"] == "s5" for _, m in hits), (known, stale, [m["id"] for _, m in hits])


verify("similar() : mots repris de state/mots.bin, jamais ceux d'un texte modifié depuis", primed)


def same_links():
    b = Brain.load()
    an = graph.ensure(b, write=False)
    ids = [n["id"] for n in b.active()]
    full = {i: graph.inferred_of(an, i, 3) for i in ids}
    mots._LOADED.clear()
    for f in ("mots.bin", "termes.bin"):
        with contextlib.suppress(OSError):
            (STATE_DIR / f).unlink()
    cold = {i: mots.inferred(b, i, 3) for i in ids}
    mots.rebuild(b)
    warm = {i: mots.inferred(b, i, 3) for i in ids}
    bad = [i for i in ids if not (full[i] == cold[i] == warm[i])]
    return not bad and sum(1 for v in full.values() if v) >= 50, (bad[:3], [(full[i], warm[i]) for i in bad[:2]],
                                                                    sum(1 for v in full.values() if v))


verify("liens déduits d'un souvenir (mots.inferred) : ceux de l'analyse complète, sans et avec les fichiers", same_links)
code, out = brain("add", "-t", "learning", "-T", "Montage vidéo et miniature de la chaîne",
                  "-b", "Montage de la vidéo, miniature et description, audience des abonnés, playlist de la chaîne.",
                  "-p", "none")
created = "montage-video-et-miniature-de-la-chaine"
b = Brain.load()
sug = [x for x in graph.inferred_of(graph.ensure(b, write=False), created, 3) if x[2] != "faible"][:2]
want = ("Liens suggérés : " + " · ".join(f"`{o}` ({', '.join(why)}) → `brain link {created} {o}`" for o, w, conf, why in sug)
        if sug else None)
got = next((line for line in out.splitlines() if line.startswith("Liens suggérés")), None)
check(code == 0 and created in b.nodes and sug and got == want,
      "add : liens suggérés identiques à ceux de l'analyse complète du graphe (non-régression)", (got, want))

# ------------------------------------------------------------------ 5. export : voisins indexés une fois
def frozen_export():
    plain = Brain.load()
    text = index.export(plain)
    frozen = Brain.load()
    frozen.freeze_neighbors()
    return index.export(frozen) == text and "Liens : " in text, len(text)


verify("export d'un cerveau figé (voisins indexés une fois) : identique, boucle et lien cassé compris", frozen_export)

wait_views()
if not remove_tree(TMP, wait=60):  # tâches de fond du cerveau testé : on attend qu'elles aient fini d'y écrire
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
