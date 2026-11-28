"""Le hook « retiens que… » sous son budget (étape 22 du plan), sur un cerveau de 3 000 souvenirs, et rien de perdu.

Avant, ce message coûtait 0,6 à 0,7 s à 3 000 souvenirs (6 à 7 fois une question) : l'index des souvenirs était refait
deux fois (doublon reformulé, puis rappel), mots.bin relu pour l'anti-doublon, et tout graph.json réécrit (44 ms sous
Python 3.10 à 3.12, dont l'encodeur JSON indenté est en Python). Désormais le hook :
- cherche ses doublons et fait le rappel du message dans l'index du cerveau tel qu'il l'a lu (memidx.bin), sans
  reconstruire ni relire mots.bin ; le rappel est celui du savoir d'avant l'écriture, sans les souvenirs qu'elle touche ;
- met le souvenir dans graph-attente.json (attente.py) au lieu de réécrire graph.json : toute lecture l'y voit aussitôt,
  la tâche de fond lancée par le hook le fait entrer dans graph.json, puis refait l'index et les vues ;
- s'arrête sans libérer le cerveau lu objet par objet (common.exit_now).
Vérifié ici : le travail fait (compté, comme tests/test_vitesse_message.py), le temps (médianes : au plus deux fois celui
d'une question, mesuré sur la même machine), et la durée de vie du souvenir : arrêt entre l'écriture et l'entrée dans
graph.json, arrêt pendant cette entrée, lecteur et écrivain de la version d'avant (8.44.0, tirée de l'historique git),
compteurs de rappel, fichier d'attente illisible.

Lancement : python tests/test_retiens_vite.py   (sortie : « N vérifications OK, M échec(s) »)"""
import io
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-retiens-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK",
          "CLAUDE_CODE_SESSION_ID"):
    os.environ.pop(k, None)
os.environ.update(BRAIN_HOME=str(TMP / "brain"), CLAUDE_CONFIG_DIR=str(TMP / "claude"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), PYTHONDONTWRITEBYTECODE="1")
for d in ("brain", "claude", "home", "projets/boutique"):
    (TMP / d).mkdir(parents=True, exist_ok=True)
os.chdir(TMP / "projets")
sys.path.insert(0, str(CODE))

from brainkit import attente, store  # noqa: E402
from brainkit.common import CONFIG_FILE, GRAPH_FILE, remove_tree, write_json  # noqa: E402
from brainkit.store import Brain  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


write_json(CONFIG_FILE, {"auto_map": {"enabled": False}, "eco": {"auto": False}, "promptlib": {"auto": False},
                         "pc": {"enabled": False}, "backup": {"enabled": False}})
BOUTIQUE = TMP / "projets" / "boutique"
NB = 3000
rnd = random.Random(22)
MOTS = ("client commande colis livraison stock fournisseur facture paiement remboursement retour emballage étiquette "
        "transporteur boutique fiche produit photo prix promotion newsletter abonné avis catalogue saison collection "
        "thé matcha sencha théière bol tasse céramique fonte bambou fouet cuillère boîte sachet échantillon cadeau "
        "carte message rendez-vous salon marché atelier comptable banque devis contrat assurance local entrepôt "
        "vitrine thème couleur logo police bannière vidéo tournage montage chaîne publication horaire réseau compte "
        "mot-clé référencement page article recette dégustation température infusion arôme récolte jardin région "
        "importation douane taxe tarif remise palier volume minimum délai semaine mois trimestre objectif chiffre").split()


def phrase(n):
    return " ".join(rnd.choice(MOTS) for _ in range(n))


with Brain.edit() as b:
    b.add("project", "Boutique de thé", "Boutique en ligne de thé japonais.", nid="boutique",
          meta={"path": str(BOUTIQUE)})
    b.add("fact", "Fournisseur de théières Tokoname", "Le fournisseur japonais Tokoname livre les théières kyusu en "
          "six semaines, par bateau.", project="boutique", nid="tokoname")
    b.add("fact", "Thème Dawn de la boutique", "Le thème Dawn est gardé, couleurs vert matcha.", project="boutique",
          nid="theme")
    for i in range(NB - 3):
        b.add(rnd.choice(("fact", "decision", "learning", "feedback")), f"{phrase(4).capitalize()} {i}", phrase(26),
              project="boutique" if i % 3 else None, tags=[rnd.choice(MOTS)])
    ids = list(b.nodes)
    for _ in range(NB):
        b.link(rnd.choice(ids), rnd.choice(ids))
ENV = dict(os.environ, BRAIN_IMPL="python")


def brain(*args, code=CODE, stdin=None):
    r = subprocess.run([sys.executable, "-I", "-S", str(code / "brain.py"), *args], capture_output=True, input=stdin,
                       cwd=str(BOUTIQUE), env=ENV, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def settle():
    """Le message suivant arrive après la réponse de Claude : la tâche de fond (vues.py) a fini."""
    brain("vues", "--attendre")


brain("vues")  # index des souvenirs, mots, vues : comme chez l'utilisateur, la tâche de fond les a déjà faits

DRIVER = TMP / "pilote.py"
DRIVER.write_text("""
import io, json, os, sys
sys.path.insert(0, sys.argv[1])
from brainkit.common import setup_io
setup_io()
from brainkit import hooks, mots, search, store
n = {"build": 0, "prime": 0, "graph": 0, "loads": 0}
build, prime, wg, init = search._build_memory_index, mots.prime, store._write_graph, store.Brain.__init__
def _build(*a, **k):
    n["build"] += 1
    return build(*a, **k)
def _prime(*a, **k):
    n["prime"] += 1
    return prime(*a, **k)
def _wg(*a, **k):
    n["graph"] += 1
    return wg(*a, **k)
def _init(self, data=None):
    n["loads"] += data is None
    init(self, data)
search._build_memory_index, mots.prime, store._write_graph, store.Brain.__init__ = _build, _prime, _wg, _init
if os.environ.get("SANS_FOND"):  # tâche de fond impossible à lancer, puis arrêt net : rien n'entre dans graph.json
    hooks.spawn_background = lambda args: False
real, sys.stdout = sys.stdout, io.StringIO()
code = hooks.run(sys.argv[2])
out, sys.stdout = sys.stdout.getvalue(), real
obj = json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
print(json.dumps({"n": n, "code": code, "ctx": (obj.get("hookSpecificOutput") or {}).get("additionalContext") or "",
                  "vu": obj.get("systemMessage") or ""}))
sys.stdout.flush()
if os.environ.get("SANS_FOND"):
    os._exit(0)
""", encoding="utf-8")
SID = [0]


def hook(prompt, extra=None):
    """`hook prompt` compté (processus neuf, comme Claude Code) → (compteurs, contexte pour Claude, ligne vue)."""
    SID[0] += 1
    data = json.dumps({"session_id": f"retiens-{SID[0]}", "cwd": str(BOUTIQUE), "prompt": prompt})
    r = subprocess.run([sys.executable, "-I", "-S", str(DRIVER), str(CODE), "prompt"], input=data.encode(),
                       capture_output=True, cwd=str(BOUTIQUE), env=dict(ENV, **(extra or {})), timeout=120)
    try:
        got = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"erreur": r.stderr.decode("utf-8", "replace")[-600:]}, "", ""
    return got["n"], got["ctx"], got["vu"]


def ids_in(ctx):
    return re.findall(r"`([a-z0-9][a-z0-9\-]*)`", ctx or "")


def recalled(ctx):
    """Ids des souvenirs du rappel (bloc « Souvenirs liés »), dans l'ordre."""
    block = ctx.split("🧠 Souvenirs liés :", 1)[1] if "🧠 Souvenirs liés :" in ctx else ""
    return [i for line in block.splitlines() if line.startswith("- ") for i in ids_in(line)[-1:]]


def on_disk(nid):
    return nid in json.loads(GRAPH_FILE.read_text(encoding="utf-8"))["nodes"]


# ------------------------------------------------------------------ 1. le travail fait par le hook
from brainkit import hooks_rappel  # noqa: E402
from brainkit.common import load_config  # noqa: E402
from brainkit.hooks import recall_query  # noqa: E402

MSG = "retiens que le fournisseur Tokoname livre aussi les bols en céramique pour les théières"
before = Brain()
expected = [n["id"] for n, _ in hooks_rappel.pick_memories(before, recall_query(MSG), load_config()["recall"], "boutique",
                                                           prev=[], raw=MSG)]
graph_before = GRAPH_FILE.read_bytes()
settle()
n1, ctx1, vu1 = hook(MSG)
new = next((i for i in ids_in(ctx1.split("\n", 1)[0]) if i.startswith("le-fournisseur-tokoname")), None)
check(new and "Retenu" in vu1, "« retiens que… » : enregistré par le hook, et dit à l'utilisateur", (n1, ctx1[:300], vu1))
check(n1.get("build") == 0, "doublons et rappel du message : l'index des souvenirs n'est pas reconstruit (avant : deux "
      "fois, 0,4 s à 3 000 souvenirs)", n1)
check(n1.get("prime") == 0, "anti-doublon : seuls les souvenirs qui peuvent atteindre le seuil sont comparés (avant : "
      "l'empreinte de chacun des 3 000 calculée, 30 ms)", n1)
check(n1.get("graph") == 0 and n1.get("loads") == 1, "graph.json lu une fois et pas réécrit : le souvenir va dans le "
      "fichier d'attente", n1)
got = recalled(ctx1)
check(got and got == [i for i in expected if i != new][:len(got)] and "tokoname" in got,
      "rappel du même message : celui du savoir d'avant l'écriture, sans le souvenir écrit", (got, expected))
c, out = brain("q", "bols céramique Tokoname")
check(c == 0 and new in out, "`brain q` juste après : le souvenir est là (en attente ou déjà dans graph.json)", out[:400])
settle()
check(on_disk(new) and not attente.FILE.exists() and GRAPH_FILE.read_bytes() != graph_before,
      "tâche de fond finie : le souvenir est dans graph.json, plus rien en attente", attente.FILE.exists())
n2, ctx2, _ = hook("quel délai pour les bols en céramique du fournisseur Tokoname ?")
check(n2.get("build") == 0 and new in recalled(ctx2), "message suivant : souvenir rappelé, index des souvenirs déjà refait "
      "par la tâche de fond (avant : 150 à 200 ms dans ce hook)", (n2, ctx2[:400]))
data = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
check((data["nodes"][new].get("meta") or {}).get("sessions") == ["retiens-1"],
      "provenance : la session du hook gardée jusque dans graph.json", data["nodes"][new].get("meta"))
textes = (TMP / "brain" / "history" / "textes.jsonl").read_text(encoding="utf-8")
check(f'"id": "{new}"' in textes or f'"id":"{new}"' in textes, "journal des textes : l'ajout y est noté", textes[-300:])

from brainkit import search  # noqa: E402

full, near = Brain(), Brain()
near.pinned_index = search.memory_index(near)
some = [n for n in list(full.nodes.values())[5:2900:97] if n["type"] != "project"]
asks = [(n["title"], n["body"]) for n in some[:10]] + [(n["title"][:30], n["body"][:60] + " " + phrase(6)) for n in some[10:]]
asks += [(phrase(5), phrase(12)) for _ in range(8)]
same = [(full.similar(t, x, None, limit=6, threshold=0.3), near.similar(t, x, None, limit=6, threshold=0.3))
        for t, x in asks]
check(all([(s, n["id"]) for s, n in a] == [(s, n["id"]) for s, n in b] for a, b in same)
      and sum(bool(a) for a, _ in same) >= 10 and near._sim_cache is None,
      "anti-doublon par l'index : exactement les mêmes souvenirs proches, dans le même ordre, que tout le cerveau comparé",
      [(a[:2], b[:2]) for a, b in same if a != b][:2])

# ------------------------------------------------------------------ 2. le temps : au plus deux fois une question
# Une question puis un « retiens que… », l'un juste après l'autre (la tâche de fond du précédent finie) : la charge de
# la machine pèse sur les deux. Médiane des rapports de 7 paires ; jusqu'à 3 essais sur une machine très chargée (CI,
# scripts lancés en parallèle). Avant : 5 à 7 fois une question, à chaque essai.
def timed(prompt):
    data = json.dumps({"session_id": f"temps-{time.time_ns()}", "cwd": str(BOUTIQUE), "prompt": prompt}).encode()
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", "prompt"], input=data,
                   capture_output=True, cwd=str(BOUTIQUE), env=ENV, timeout=120)
    return (time.perf_counter() - t0) * 1000


tries = []
for attempt in range(3):
    q, r = [], []
    for i in range(7):
        settle()
        q.append(timed(f"quel est le prix du {rnd.choice(MOTS)} en {rnd.choice(MOTS)} ?"))
        r.append(timed(f"retiens que le grossiste Hoshino {attempt}-{i} livre le {rnd.choice(MOTS)} et le "
                       f"{rnd.choice(MOTS)} le {i + 3} du mois"))
    ratio = statistics.median(y / x for x, y in zip(q, r))
    tries.append((round(ratio, 2), round(statistics.median(q)), round(statistics.median(r))))
    print(f"(à {NB} souvenirs : question {tries[-1][1]} ms, « retiens que… » {tries[-1][2]} ms, médianes de 7 ; "
          f"rapport {ratio:.2f})")
    if ratio <= 2:
        break
check(tries[-1][0] <= 2, f"« retiens que… » à {NB} souvenirs : au plus deux fois une question (avant : 5 à 7 fois)",
      tries)

# ------------------------------------------------------------------ 3. arrêt avant l'entrée dans graph.json
OLD_REFS = ("cerveau--v8.44.0", "6e4d9c4")


def old_code():
    for ref in OLD_REFS:
        if subprocess.run(["git", "-C", str(CODE), "cat-file", "-e", f"{ref}:brainkit/attente.py"],
                          capture_output=True).returncode == 0:
            continue  # pas la 8.44.0
        got = subprocess.run(["git", "-C", str(CODE), "archive", ref, "brain.py", "brainkit"], capture_output=True)
        if got.returncode == 0:
            dest = TMP / "v844"
            dest.mkdir()
            with tarfile.open(fileobj=io.BytesIO(got.stdout)) as tar:
                try:
                    tar.extractall(dest, filter="data")
                except TypeError:  # Python 3.10 et 3.11 sans le filtre
                    tar.extractall(dest)
            return dest
    sys.exit("✗ code de la 8.44.0 introuvable dans ce dépôt (" + ", ".join(OLD_REFS) + ") : `git fetch --unshallow`")


V844 = old_code()
settle()
n3, ctx3, _ = hook("retiens que l'entrepôt de Nantes ferme à 19 heures le samedi", {"SANS_FOND": "1"})
late = next((i for i in ids_in(ctx3.split("\n", 1)[0]) if i.startswith("l-entrepot-de-nantes")), None)
time.sleep(0.5)
check(late and attente.FILE.exists() and not on_disk(late), "arrêt net avant l'entrée dans graph.json : le souvenir "
      "est dans le fichier d'attente", (ctx3[:200], attente.FILE.exists()))
c, out = brain("show", late or "?")
check(c == 0 and "Nantes" in out, "il est lu tout de suite par la version courante (`brain show`)", out[:300])
b = Brain()
check(late in b.nodes and b.stamp == store.graph_stamp() and "+" in (b.stamp or ""),
      "empreinte du cerveau lu = celle de graph.json et du fichier d'attente (caches des hooks justes)", b.stamp)
c, out = brain("show", late or "?", code=V844)
check(c != 0 or "Nantes" not in out, "8.44.0 : ne le voit pas tant qu'il n'est pas dans graph.json (délai documenté)",
      out[:200])
c, out = brain("add", "-t", "fact", "-T", "Écrit par la 8.44.0", "-b", "Un fait de l'ancienne version.", "-p", "none",
               "--id", "ancien-code", code=V844)
check(c == 0 and on_disk("ancien-code") and not on_disk(late) and attente.FILE.exists(),
      "8.44.0 écrit graph.json pendant l'attente : le souvenir reste en attente", out[-300:])
b = Brain()
check(late in b.nodes and "ancien-code" in b.nodes, "version courante : les deux souvenirs (l'attente et l'écriture de "
      "la 8.44.0)", sorted(set(b.nodes) - set(data["nodes"]))[:6])
c, out = brain("add", "-t", "fact", "-T", "Horaires du dépôt de Lille", "-b", "Le dépôt de Lille ouvre à 8 heures.",
               "-p", "none", "--id", "lille")
check(c == 0 and on_disk(late) and on_disk("lille") and on_disk("ancien-code") and not attente.FILE.exists(),
      "écriture suivante (`brain add`) : le souvenir en attente entre dans graph.json, l'attente est vidée", out[-300:])
c, out = brain("show", late, code=V844)
check(c == 0 and "Nantes" in out, "8.44.0 : le voit une fois dans graph.json", out[:300])
mark = json.loads(GRAPH_FILE.read_text(encoding="utf-8")).get("attente")
check(isinstance(mark, dict) and mark.get("n", 0) >= 1, "graph.json note jusqu'où il contient l'attente", mark)

# ------------------------------------------------------------------ 4. arrêt pendant l'entrée dans graph.json
with Brain.edit(defer=True) as b:  # comme le hook : une ligne d'attente
    b.add("fact", "Code du portail de l'entrepôt", "Le portail de l'entrepôt s'ouvre avec le badge bleu.",
          project="boutique", nid="portail")
    b.link("portail", "boutique", "about")
check(attente.FILE.exists() and not on_disk("portail"), "Brain.edit(defer=True) : une ligne d'attente, graph.json intact")
real = attente.settle
attente.settle = lambda epoch, num: True  # arrêt après l'écriture de graph.json, avant le ménage de l'attente
try:
    with Brain.edit() as b:
        b.dirty = True
finally:
    attente.settle = real
check(on_disk("portail") and attente.FILE.exists(), "arrêt pendant l'entrée : graph.json la contient, la ligne est "
      "encore en attente")
c, out = brain("edit", "portail", "-b", "Le portail s'ouvre avec le badge vert.", code=V844)
b = Brain()
links = [e for e in b.edges if (e["from"], e["to"], e["rel"]) == ("portail", "boutique", "about")]
check(c == 0 and "badge vert" in b.nodes["portail"]["body"] and len(links) == 1,
      "ligne déjà dans graph.json : jamais appliquée deux fois (ni le texte d'avant, ni un lien en double)",
      (out[-200:], b.nodes["portail"]["body"], len(links)))
c, _ = brain("add", "-t", "fact", "-T", "Horaires du dépôt de Lyon", "-b", "Le dépôt de Lyon ouvre à 9 heures.",
             "-p", "none", "--id", "lyon")
check(not attente.FILE.exists() and "badge vert" in Brain().nodes["portail"]["body"],
      "écriture suivante : le ménage est fait, l'écriture de la 8.44.0 gardée")

# ------------------------------------------------------------------ 5. compteurs de rappel d'un souvenir en attente
hits0 = Brain().nodes["theme"].get("hits", 0)
store.bump_hits(["theme"])
with Brain.edit(defer=True) as b:
    b.update("theme", body="Le thème Dawn est gardé, couleurs vert matcha et crème.")
b = Brain()
check(attente.FILE.exists() and b.nodes["theme"].get("hits", 0) == hits0 + 1 and "crème" in b.nodes["theme"]["body"],
      "souvenir modifié en attente : son rappel compté une fois, pas deux", (hits0, b.nodes["theme"].get("hits")))
attente.absorb()
b = Brain()
check(not attente.FILE.exists() and b.nodes["theme"].get("hits", 0) == hits0 + 1 and on_disk("theme"),
      "entré dans graph.json : toujours compté une fois", b.nodes["theme"].get("hits"))

# ------------------------------------------------------------------ 6. fichier d'attente illisible
attente.FILE.write_text('{"id": "x", "n": 3, "lignes": [{"n"', encoding="utf-8")
try:
    b, err = Brain(), None
except Exception as exc:
    err = exc
check(err is None, "fichier d'attente illisible : le cerveau se lit quand même", err)
with Brain.edit(defer=True) as b:
    b.add("fact", "Badge du livreur", "Le livreur sonne deux fois.", project="boutique", nid="livreur")
aside = list((TMP / "brain").glob("graph-attente.illisible-*.json"))
check(on_disk("livreur") and len(aside) == 1 and '"lignes"' in aside[0].read_text(encoding="utf-8"),
      "écriture suivante : graph.json réécrit, le fichier illisible gardé de côté (jamais écrasé)", aside)

# ------------------------------------------------------------------ 7. fin d'un hook sans libérer la mémoire, sans rien couper
mark_file = TMP / "fil-fini.txt"
snippet = ("import sys, threading, time; sys.path.insert(0, sys.argv[1]); from brainkit.common import exit_now\n"
           "def late():\n    time.sleep(0.3)\n    open(sys.argv[2], 'w').write('fini')\n"
           "threading.Thread(target=late).start(); print('sortie', flush=False); exit_now(3)\n")
r = subprocess.run([sys.executable, "-I", "-S", "-c", snippet, str(CODE), str(mark_file)], capture_output=True,
                   timeout=60)
check(r.returncode == 3 and r.stdout.decode().strip() == "sortie" and mark_file.exists(),
      "exit_now : sortie vidée, code gardé, un fil encore au travail attendu", (r.returncode, r.stdout, r.stderr[-300:]))
r = subprocess.run([sys.executable, "-I", "-S", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from brainkit.common "
                    "import exit_now; print('vite', end=''); exit_now(0)", str(CODE)], capture_output=True, timeout=60)
check(r.returncode == 0 and r.stdout == b"vite", "exit_now : sortie complète avant l'arrêt", r.stdout)

settle()
remove_tree(TMP)
print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
