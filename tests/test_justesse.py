"""Une mémoire plus juste (étape 14 du plan, d'après Graphiti et mem0) : dates dites dans le texte proposées à l'ajout ;
un remplacement daté au début du nouveau fait (et un remplaçant futur qui laisse l'ancien vrai jusque-là) ; un « nouveau »
qui commence avant l'ancien n'est pas son remplaçant ; deux périodes distinctes ne se contredisent pas ; les variantes
d'un même nom réunies ; un nom propre rare partagé suggère un remplacement ; les règles d'écriture dans le rappel de fin
de tâche ; un motif proposé par le rêve pour un gros sujet ; l'index nom → souvenirs gardé pour `q` et `add` (mêmes
résultats, rien relu deux fois, refait s'il manque ou est abîmé, graphe ancien lu tel quel) ; l'usage façon ACT-R mesuré
par `brain bench` sur les échanges rejoués, sans toucher au modèle appris d'avant. Dans un dossier temporaire.

Lancement : python tests/test_justesse.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import math
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-justesse-test-"))
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "BRAIN_HOME": str(TMP / "brain"), "PYTHONUTF8": "1",
                   "BRAIN_NO_BACKGROUND": "1"})
WORK = TMP / "travail"
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))
OK, FAIL = [], []

from brainkit import hooks, reconcile, temps  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-900:]}" if detail else ""))


def brain(*args):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *args], capture_output=True, cwd=str(WORK),
                       env=dict(os.environ), timeout=180)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def graph():
    return json.loads((TMP / "brain" / "graph.json").read_text(encoding="utf-8"))


TODAY = dt.date.today()


def iso(days):
    return (TODAY + dt.timedelta(days=days)).isoformat()


def fr(d):
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}"


# ------------------------------------------------------------------ 1. dates dites dans le texte
T = dt.date(2026, 11, 24)
check(temps.text_dates("On livre en Mondial Relay depuis le 01/09.", T) == {"valid_from": "2026-09-01"},
      "« depuis le 01/09 » : début proposé")
check(temps.text_dates("9 euros à partir du 1er janvier 2027 et jusqu'au 31/03/2027.", T)
      == {"valid_from": "2027-01-01", "valid_to": "2027-03-31"}, "« à partir du … jusqu'au … » : début et fin")
check(temps.text_dates("À rendre d'ici le 15/12.", T) == {}, "« d'ici le » : une échéance, pas une fin")
c, out = brain("add", "-t", "fact", "-T", "Transporteur des colis", "-b", "On livre en Mondial Relay depuis le 01/09.",
               "-p", "none", "--id", "transport")
check(c == 0 and "📅" in out and "--depuis" in out and "valid_from" not in graph()["nodes"]["transport"]["meta"],
      "à l'ajout : la date du texte est proposée, pas posée", out)

# ------------------------------------------------------------------ 2. remplacement daté
brain("add", "-t", "fact", "-T", "Tarif express", "-b", "L'express coûte 12 euros.", "-p", "none", "--depuis", iso(-90),
      "--id", "tarif-ancien")
brain("add", "-t", "fact", "-T", "Nouveau tarif express", "-b", "L'express coûtera 9 euros.", "-p", "none",
      "--depuis", iso(20), "--id", "tarif-futur", "--force")
c, out = brain("supersede", "tarif-futur", "tarif-ancien", "--parce-que", "nouveau contrat")
old = graph()["nodes"]["tarif-ancien"]
check(c == 0 and old["status"] == "active" and old["meta"]["valid_to"] == iso(19) and "encore vrai jusqu'au" in out,
      "remplaçant qui commence dans 20 jours : l'ancien reste vrai et actif jusqu'à la veille", out + json.dumps(old["meta"]))
c, out = brain("consolidate")
check(graph()["nodes"]["tarif-ancien"]["status"] == "active", "l'entretien du jour ne l'archive pas avant sa fin", out)
brain("add", "-t", "fact", "-T", "Horaires", "-b", "Ouvert de 9 h à 18 h.", "-p", "none", "--depuis", iso(-60), "--id", "h1")
brain("add", "-t", "fact", "-T", "Horaires d'hiver", "-b", "Ouvert de 10 h à 17 h.", "-p", "none", "--depuis", iso(-10),
      "--id", "h2", "--force")
c, out = brain("supersede", "h2", "h1")
check(c == 0 and graph()["nodes"]["h1"]["meta"]["valid_to"] == iso(-11) and graph()["nodes"]["h1"]["status"] == "archived",
      "remplaçant déjà commencé : l'ancien finit la veille de son début", out)
brain("add", "-t", "fact", "-T", "Fournisseur A", "-b", "Le matcha vient du fournisseur A.", "-p", "none", "--depuis",
      iso(-30), "--id", "fa")
brain("add", "-t", "fact", "-T", "Fournisseur B", "-b", "Le matcha venait du fournisseur B.", "-p", "none", "--depuis",
      iso(-200), "--id", "fb", "--force")
c, out = brain("supersede", "fb", "fa")
check(c != 0 and "avant" in out and graph()["nodes"]["fa"]["status"] == "active",
      "un « nouveau » qui commence avant l'ancien : remplacement refusé, rien ne change", out)

# ------------------------------------------------------------------ 3. périodes distinctes, variantes de noms
check(reconcile.names("Envoi par Mondial Relay") == reconcile.names("Envoi par MondialRelay") == {"mondialrelay"},
      "« Mondial Relay » et « MondialRelay » : le même nom")
check(reconcile.names("Le code NEWS15 sur judge.me") == {"news15", "judgeme"}, "codes et domaines : forme sans point")
sig = reconcile.signals({"title": "Envoi par Mondial Relay", "body": "Les colis partent en point relais."},
                        "Envoi par MondialRelay", "Les colis partent en point relais.")
check(not sig.get("autre sujet"), "titres qui ne diffèrent que par l'écriture du nom : même sujet", sig)
g = graph()
g["nodes"]["promo-2025"] = {"id": "promo-2025", "type": "fact", "title": "Code promo de Noël", "body": "Le code NOEL donne 10 %.",
                            "tags": [], "project": None, "importance": 3, "created": iso(-400) + "T09:00:00",
                            "updated": iso(-330) + "T09:00:00", "hits": 0, "source": "claude", "status": "active",
                            "meta": {"valid_from": iso(-400), "valid_to": iso(-330)}}
(TMP / "brain" / "graph.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
c, out = brain("add", "-t", "fact", "-T", "Code promo de Noël", "-b", "Le code NOEL donne 15 %.", "-p", "none", "--id", "promo-2026")
g = graph()
check(c == 0 and "promo-2026" in g["nodes"] and g["nodes"]["promo-2025"].get("meta", {}).get("superseded_by") is None
      and "remplace `promo-2025`" not in out, "une période passée et finie n'est ni fusionnée ni remplacée par la nouvelle", out)

# ------------------------------------------------------------------ 4. nom propre rare partagé : suggestion
brain("add", "-t", "fact", "-T", "Colissimo pour les gros colis", "-b", "Les colis de plus de 5 kg partent en Colissimo à 14 euros.",
      "-p", "none", "--id", "colis")
c, out = brain("add", "-t", "fact", "-T", "Prix Colissimo revu", "-b", "Désormais 16 euros au-delà de 5 kg.", "-p", "none",
               "--id", "colis2")
check(c == 0 and "colis" in out and "remplace peut-être" in out and graph()["nodes"]["colis"]["status"] == "active",
      "nom propre rare partagé (Colissimo) : remplacement suggéré, jamais appliqué seul", out)

# ------------------------------------------------------------------ 5. règles d'écriture en fin de tâche
text = hooks.STOP_REASON.replace(hooks.CMD, 'python "$HOME/.claude/brain/brain.py"')
check("tient seul" in hooks.STOP_REASON and "X → Y" in hooks.STOP_REASON and len(text) < 600,
      "rappel de fin de tâche : les règles d'écriture, dans le budget de 600 caractères", len(text))

# ------------------------------------------------------------------ 6. motif proposé par le rêve
from brainkit.store import Brain  # noqa: E402

with Brain.edit() as b:
    ids = []
    for i in range(10):
        n = b.add("learning", f"Bento laqué numéro {i}", f"Le bento laqué {i} se vend mieux avec la boîte en bois de hinoki.",
                  tags=["bento", "hinoki"])
        ids.append(n["id"])
    for i in range(10):
        for j in range(i + 1, 10):
            b.link(ids[i], ids[j], "relates")
c, out = brain("dream", "--no-apply")
m = re.search(r"« ([^»]+) » \((\d+) souvenirs", out.split("## Motif à écrire")[-1]) if "## Motif à écrire" in out else None
check(m and int(m.group(2)) >= 8 and "add -t analysis -T \"Motif : " in out and ":about" in out,
      "rêve : un motif proposé pour un gros sujet, avec ses preuves en liens", out[-800:])
if m:
    brain("add", "-t", "analysis", "-T", f"Motif : {m.group(1)}", "-b", "Le hinoki fait vendre les bentos laqués.", "-p", "none")
    c, out2 = brain("dream", "--no-apply")
    check(f"« {m.group(1)} »" not in out2.split("## Motif à écrire")[-1] if "## Motif à écrire" in out2 else True,
          "motif écrit : plus proposé au rêve suivant", out2[-500:])

# ------------------------------------------------------------------ 7. index nom → souvenirs (point 5)
from brainkit import noms, search  # noqa: E402
from brainkit.common import STATE_DIR  # noqa: E402

with Brain.edit() as b:
    b.add("fact", "Fabrication du coffret Hōjicha", "Le coffret Hōjicha est fabriqué par l'atelier Sato à Uji.",
          nid="hojicha")
    b.add("fact", "Fermeture estivale de l'atelier Sato", "L'atelier Sato ferme tout le mois d'août pour congés.",
          nid="sato")
    for i in range(40):
        b.add("fact", f"Note de stock numéro {i}", f"Le carton {i} part chez Kobe{i} Craft le lundi.", nid=f"stock{i}")
NB, HOP = STATE_DIR / noms.FILE, "le coffret Hōjicha sera-t-il disponible cet été ?"
SPANS, CALLS = reconcile._entity_spans, []


def counted(text):
    CALLS.append(1)
    return SPANS(text)


def hop(use_cache=True):
    del CALLS[:]
    noms._LOADED.clear()  # comme une nouvelle commande
    r = search.search_memories(Brain.load(), HOP, limit=5, expand=False, fuse=True, use_cache=use_cache)
    return [(x["node"]["id"], x.get("via")) for x in r], len(CALLS)


reconcile._entity_spans = counted
try:
    NB.unlink(missing_ok=True)
    first, n_first = hop()
    again, n_again = hop()
    plain, _ = hop(use_cache=False)
    total = len(Brain.load().nodes)
    check(("sato", "lien (sato)") in first and first == again == plain,
          "`q` : deuxième saut par un nom rare (Hōjicha → atelier Sato), le même avec ou sans l'index des noms",
          (first, again, plain))
    check(NB.is_file() and n_first >= total and n_again == 0,
          f"index nom → souvenirs gardé : la question suivante ne relit aucun des {total} souvenirs (avant : tous)",
          (n_first, n_again, total))
    with Brain.edit() as b:
        b.update("stock3", body="Le carton 3 part chez Zorglub Craft le lundi.")
    after, n_after = hop()
    check(n_after == 1 and "zorglub" in noms.table(Brain.load())["stock3"][1] and after == first,
          "un souvenir changé : lui seul est relu, ses nouveaux noms sont dans l'index", (n_after, after))
    NB.write_bytes(b"pas un index")
    broken, n_broken = hop()
    check(broken == first and n_broken >= total and noms.table(Brain.load())["sato"][1] == ("sato",),
          "index abîmé : refait sans erreur, mêmes résultats", (broken, n_broken))
    del CALLS[:]
    c, out = brain("add", "-t", "fact", "-T", "Congés de l'atelier Sato en 2027", "-b", "Fermé du 1er au 20 août.",
                   "-p", "none", "--id", "sato-2027")
    check(c == 0 and "sato" in out and "remplace peut-être" in out,
          "`add` : le nom rare partagé (atelier Sato) se trouve par l'index des noms", out)
finally:
    reconcile._entity_spans = SPANS
# Graphe d'une ancienne version (champs absents : contenu, étiquettes, méta, compteurs) : lu tel quel, jamais réécrit.
GF = TMP / "brain" / "graph.json"
saved = GF.read_bytes()
oldg = {"version": 1, "edges": [], "nodes": {
    "vieux": {"id": "vieux", "type": "fact", "title": "Transporteur Chronopost pour le Japon"},
    "vieux2": {"id": "vieux2", "type": "fact", "title": "Tarif Chronopost", "body": "Chronopost facture 30 euros vers le Japon."}}}
GF.write_text(json.dumps(oldg, ensure_ascii=False), encoding="utf-8")
raw = GF.read_bytes()
NB.unlink(missing_ok=True)
c, out = brain("q", "Chronopost Japon")
check(c == 0 and "vieux" in out and GF.read_bytes() == raw and NB.is_file(),
      "graphe d'une ancienne version : `q` répond, graph.json inchangé, l'index des noms refait à côté", out)
GF.write_bytes(saved)

# ------------------------------------------------------------------ 8. usage (ACT-R) : mesuré, pas mis en service
from brainkit import bench, neurone, vivant  # noqa: E402
from brainkit.common import load_config  # noqa: E402

NOW = dt.datetime(2026, 11, 28, 12, 0)
ago = lambda d: (NOW - dt.timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
act = lambda n: vivant.activation(n, NOW)  # noqa: E731
check(act({"id": "x", "title": "t"}) == 0 and act({"used": "3", "last_used": "hier"}) == 0
      and act({"used": True, "last_used": ago(1)}) == 0 and act({"used": 0, "last_used": ago(1)}) == 0,
      "activation : 0 sans reprise, et sans erreur sur les champs absents ou bizarres d'un ancien graphe")
one = act({"used": 1, "last_used": ago(1), "created": ago(60)})
check(abs(one - 1.0) < 1e-9 and act({"used": 1, "last_used": ago(30), "created": ago(60)}) < one
      < act({"used": 5, "last_used": ago(1), "created": ago(60)}),
      "activation d'ACT-R : une reprise d'hier vaut 1, elle décline avec le temps, grandit avec le nombre")
hot = {"used": 9, "last_used": ago(0.2), "created": ago(40)}
check(vivant.order([{}, {}, {}], [10, 9, 5]) == [0, 1, 2] and vivant.order([{}, hot, {}], [10, 9, 5], NOW) == [1, 0, 2]
      and vivant.order([{}, {}, hot], [10, 9, 5], NOW) == [0, 1, 2],
      "usage : l'ordre seulement, à pertinence voisine (au plus +20 %) ; rien retiré, sans usage rien ne bouge")


def f(score, rank, acc=1):
    x = [0.0] * len(neurone.NAMES)
    x[0], x[4], x[11] = round(math.log1p(score), 4), rank / 10, float(acc)
    return x


def month(later=False):
    """Un mois d'échanges : la question sur D seule (D utile), et une question où D n'arrive que 4e des acceptés."""
    rows = []
    for d in range(20):
        t_d, t_mix = (ago(10 - d / 4), ago(30 - d / 2)) if later else (ago(30 - d), ago(30 - d - 0.5))
        rows.append({"t": t_d, "s": f"a{d}", "id": "D", "f": f(12, 0), "y": 1, "c": [90, 40], "src": "live"})
        for k, (nid, sc) in enumerate((("A", 10), ("B", 9.5), ("C", 9), ("D", 8.8))):
            rows.append({"t": t_mix, "s": f"b{d}", "id": nid, "f": f(sc, k), "y": int(nid == "D"), "c": [90, 40],
                         "src": "live"})
    return rows


rc = load_config()["recall"]
res = vivant.replay(month(), rc)
msgs = {}
for r in month():
    msgs.setdefault((r["s"], r["t"]), []).append(r)
alone = neurone._simulate(sorted(msgs.items(), key=lambda kv: kv[0][1]), neurone._rule_pick(rc), rc)
check(res["messages"] == 40 and res["regle"] == alone and res["usage"]["utiles"] > res["regle"]["utiles"]
      and res["usage"]["injectes"] == res["regle"]["injectes"],
      "rejeu : le souvenir souvent repris passe dans les 3 montrés ; la règle seule comptée comme le neurone la compte",
      res)
late = vivant.replay(month(later=True), rc)
check(late["usage"]["utiles"] == late["regle"]["utiles"],
      "rejeu : l'usage d'un souvenir ne compte qu'à partir de ses reprises (rien du futur)", late)
# Modèle déjà appris sur le PC (version 1 des traits) : il sert tel quel, la mesure ne le touche pas.
model = dict(neurone.Model().to_dict(), v=1, ready=True, n=400, pos=60, at="2026-11-20T10:00:00", bytes=0,
             bytes_per_row=300)
neurone.MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
neurone.MODEL_FILE.write_text(json.dumps(model), encoding="utf-8")
neurone.EX_FILE.write_text("".join(json.dumps(r) + "\n" for r in month()), encoding="utf-8")
before = (neurone.MODEL_FILE.read_bytes(), neurone.EX_FILE.read_bytes())
neurone._CACHE.clear()
got = vivant.measure(Brain.load())
line = bench.usage_line(Brain.load())
check(neurone.V == 1 and len(neurone.NAMES) == 27 and neurone.load() is not None and got["with"] == "neurone"
      and got["messages"] == 40 and "rejoué sur tes 40" in line and "le neurone seul" in line,
      "modèle appris d'avant (27 traits, version 1) : chargé et rejoué tel quel par la mesure de `brain bench`", line)
r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", "prompt"], capture_output=True,
                   cwd=str(WORK), env=dict(os.environ), timeout=60, input=json.dumps(
                       {"session_id": "vieux-modele", "cwd": str(WORK), "hook_event_name": "UserPromptSubmit",
                        "prompt": "quand ferme l'atelier Sato cet été ?"}).encode())
check(r.returncode == 0 and (neurone.MODEL_FILE.read_bytes(), neurone.EX_FILE.read_bytes()) == before,
      "message avec le modèle d'avant : rappel sans erreur, ni ses poids ni ses exemples réécrits", r.stderr[-400:])
neurone.EX_FILE.write_text("", encoding="utf-8")
check("pas encore d'échanges" in bench.usage_line(Brain.load()), "aucun échange étiqueté : `brain bench` le dit")

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
