"""Une mémoire plus juste (étape 14 du plan, d'après Graphiti et mem0) : dates dites dans le texte proposées à l'ajout ;
un remplacement daté au début du nouveau fait (et un remplaçant futur qui laisse l'ancien vrai jusque-là) ; un « nouveau »
qui commence avant l'ancien n'est pas son remplaçant ; deux périodes distinctes ne se contredisent pas ; les variantes
d'un même nom réunies ; un nom propre rare partagé suggère un remplacement ; les règles d'écriture dans le rappel de fin
de tâche ; un motif proposé par le rêve pour un gros sujet. Dans un dossier temporaire.

Lancement : python tests/test_justesse.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
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

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
