"""Vitesse du hook de chaque message et de la fin de tour (étape 4 du plan) : ce qui est gardé d'un hook à l'autre l'est
sans jamais servir un état périmé, et chaque hook ne charge que ce dont il se sert. Aucune mesure de temps (instable
en CI) : on compte ce qui est fait (empreinte du savoir, index reconstruit, cerveau lu, fichiers analysés, modules).

- index des souvenirs : repris sans relire tout le savoir tant que graph.json n'a pas changé (une réécriture de même
  taille, même date, même n° de fichier comprise), reconstruit après un vrai changement ; relu de memidx.bin, il rend
  les mêmes résultats que l'index construit en mémoire ;
- message : empreinte du savoir calculée au plus une fois ; « ok merci » ne lit pas le cerveau ;
- question datée : les dates citées par les souvenirs gardées d'un hook à l'autre, relues si la date d'écriture change ;
- fin de tour : graph.json lu une seule fois, puis plus du tout pour le journal tant qu'il n'a pas changé (nouvelle
  session dans le même dossier comprise) ;
- réflexe des skills : un SKILL.md inchangé n'est pas relu, un SKILL.md modifié est vu (seul lui est relu), même réécrit
  dans le même tic d'horloge ; aucune expression compilée par skill à chaque message ;
- observations de fin de tâche : l'index n'est pas refait à chaque message, il voit une observation ajoutée ;
- imports : compaction, « ok merci » et fin de tour ne chargent ni la recherche ni l'index ni le cerveau commun.

Lancement : python tests/test_vitesse_message.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import json
import marshal
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-vitesse-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK"):
    os.environ.pop(k, None)
os.environ.update(BRAIN_HOME=str(TMP / "brain"), CLAUDE_CONFIG_DIR=str(TMP / "claude"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), PYTHONDONTWRITEBYTECODE="1")
for d in ("brain", "claude", "home", "projets/boutique", "neutre"):
    (TMP / d).mkdir(parents=True, exist_ok=True)
os.chdir(TMP / "neutre")
sys.path.insert(0, str(CODE))

from brainkit import observations, search, skills  # noqa: E402
from brainkit.common import CONFIG_FILE, GRAPH_FILE, STATE_DIR, remove_tree, write_json  # noqa: E402
from brainkit.store import Brain  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


# Rien en arrière-plan ni sur le réseau pendant les hooks.
write_json(CONFIG_FILE, {"auto_map": {"enabled": False}, "eco": {"auto": False}, "promptlib": {"auto": False},
                         "pc": {"enabled": False}, "backup": {"enabled": False}})
BOUTIQUE = TMP / "projets" / "boutique"
with Brain.edit() as b:
    b.add("project", "Boutique de thé", "Boutique en ligne de thé japonais.", nid="boutique", meta={"path": str(BOUTIQUE)})
    for i, (title, body) in enumerate((
            ("Transporteur Colissimo pour les colis", "Les colis partent avec Colissimo, suivi envoyé au client."),
            ("Thème Dawn de la boutique Shopify", "Le thème Dawn est gardé, couleurs vert matcha."),
            ("Prix du matcha de cérémonie", "Le matcha de cérémonie se vend 32 € les 30 g."),
            ("Commande Marukyu reçue le 12/11", "La commande du fournisseur Marukyu est arrivée le 12/11, sans casse."),
            ("Fournisseur de bols en céramique", "Le fournisseur de bols livre en octobre, commande passée le 3/10."),
            ("Newsletter du mois", "La newsletter part le premier lundi du mois, 900 abonnés."))):
        b.add("fact", title, body, project="boutique")

DRIVER = TMP / "pilote.py"
DRIVER.write_text("""
import io, json, sys
sys.path.insert(0, sys.argv[1])
from brainkit.common import setup_io
setup_io()
from brainkit import search, store
n = {"sig": 0, "build": 0, "loads": 0, "spans": 0}
sig, build, init, spans = search._mem_sig, search._build_memory_index, store.Brain.__init__, search._month_spans
def _sig(b):
    n["sig"] += 1
    return sig(b)
def _build(b, archived=False):
    n["build"] += 1
    return build(b, archived)
def _init(self, data=None):
    n["loads"] += data is None
    init(self, data)
def _spans(text, ref):
    n["spans"] += 1
    return spans(text, ref)
search._mem_sig, search._build_memory_index, store.Brain.__init__, search._month_spans = _sig, _build, _init, _spans
from brainkit import hooks
real, sys.stdout = sys.stdout, io.StringIO()
code = hooks.run(sys.argv[2])
out, sys.stdout = sys.stdout.getvalue(), real
obj = json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
print(json.dumps({"n": n, "code": code, "ctx": (obj.get("hookSpecificOutput") or {}).get("additionalContext") or ""}))
""", encoding="utf-8")
ENV = dict(os.environ, BRAIN_IMPL="python")
SID = [0]


def hook(event, payload, cwd=BOUTIQUE):
    """`brain.py hook <event>` comme Claude Code le lance (processus neuf), compté → (compteurs, contexte injecté)."""
    SID[0] += 1
    data = dict({"session_id": f"vitesse-{SID[0]}", "cwd": str(cwd)}, **payload)
    r = subprocess.run([sys.executable, "-I", "-S", str(DRIVER), str(CODE), event], input=json.dumps(data).encode(),
                       capture_output=True, cwd=str(cwd), env=ENV, timeout=120)
    try:
        got = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"erreur": r.stderr.decode("utf-8", "replace")[-600:]}, ""
    return got["n"], got["ctx"]


def ids_in(ctx):
    return re.findall(r"`([a-z0-9][a-z0-9\-]*)`", ctx or "")


# ------------------------------------------------------------------ 1. index des souvenirs, d'un message à l'autre
NOWHERE = "explique la photosynthèse des plantes vertes"  # cherché dans l'index, ne rappelle rien (graph.json intact)
n1, _ = hook("prompt", {"prompt": NOWHERE})
n2, _ = hook("prompt", {"prompt": NOWHERE})
check(n1.get("build") == 1 and n1.get("sig") == 1, "premier message : savoir signé une fois, index construit", n1)
check(n2.get("sig") == 0 and n2.get("build") == 0 and n2.get("loads") == 1,
      "message suivant, graph.json inchangé : index repris sans relire tout le savoir (ni empreinte ni reconstruction)", n2)
with Brain.edit() as b:
    new = b.add("fact", "Fournisseur de théières Kyusu Tokoname",
                "Le fournisseur japonais Tokoname livre les théières kyusu en six semaines.", project="boutique")["id"]
n3, ctx3 = hook("prompt", {"prompt": "délai du fournisseur Tokoname pour les théières kyusu ?"})
check(n3.get("build") == 1 and new in ids_in(ctx3), "souvenir ajouté : index reconstruit, le nouveau souvenir rappelé",
      (n3, ctx3[:400]))
hook("prompt", {"prompt": NOWHERE})  # (l'empreinte de graph.json tel qu'il est maintenant est notée)
raw = GRAPH_FILE.read_bytes()
st = os.stat(GRAPH_FILE)
with open(GRAPH_FILE, "r+b") as fh:  # même taille, même fichier, même date : seul le contenu change
    fh.write(raw.replace("Tokoname".encode(), "Bankoyak".encode()))
    fh.truncate()
os.utime(GRAPH_FILE, ns=(st.st_atime_ns, st.st_mtime_ns))
same = os.stat(GRAPH_FILE)
n5, ctx5 = hook("prompt", {"prompt": "délai du fournisseur Bankoyak pour les théières kyusu ?"})
check((same.st_size, same.st_mtime_ns) == (st.st_size, st.st_mtime_ns) and n5.get("build") == 1 and new in ids_in(ctx5),
      "graph.json réécrit à l'identique de taille et de date : jamais l'index d'avant", (n5, ctx5[:300]))
check(sum(1 for c in (n1, n3, n5) if c.get("sig", 9) <= 1) == 3, "chaque message : empreinte du savoir calculée au plus "
      "une fois (avant : à chaque recherche, deux à trois fois)", (n1, n3, n5))
n6, ctx6 = hook("prompt", {"prompt": "ok merci, on continue"})
check(n6.get("loads") == 0 and n6.get("sig") == 0, "« ok merci, on continue » : rien à chercher, graph.json pas lu", n6)

# Relu de memidx.bin : fréquences en octets (aucune table par souvenir chargée), mêmes résultats qu'en mémoire.
b = Brain.load()
built = search._build_memory_index(b)
built._fuzzy_maps()
search._LOADED.clear()
search.memory_index(b)
blob = marshal.loads((STATE_DIR / "memidx.bin").read_bytes())
kept = search.Index.from_state(blob)
kept._phon, kept._del, kept._root, kept._tri = blob["phon"], blob["del"], blob["root"], blob["tri"]
kept.subword = True
check("tfs" not in vars(kept) and "post" not in vars(kept), "index relu : aucune table de fréquences par souvenir chargée",
      sorted(vars(kept)))
queries = ["transporteur colis", "théme shopify", "matcha prix", "fournisseur", "comande marukyu", "newsletter abonnés",
           "Colissimo suivi client", "céramique bols octobre", "inteligence", "kyusu", "vert matcha boutique"]
diff = [q for q in queries if built.search(q, 80) != kept.search(q, 80)]
check(not diff, "index relu de memidx.bin : mêmes résultats (scores, ordre, mots trouvés) que l'index construit", diff)

# ------------------------------------------------------------------ 2. question datée : dates des souvenirs gardées
DATED = "qu'est-ce que le fournisseur a livré la semaine dernière ?"
d1, _ = hook("prompt", {"prompt": DATED})
d2, _ = hook("prompt", {"prompt": DATED})
check(d1.get("spans", 0) > 0 and d2.get("spans") == 0,
      "question datée : les dates citées par les souvenirs lues une fois, reprises au message suivant", (d1, d2))
node = {"id": "x", "title": "Livré le 15/10", "body": "", "created": "2026-11-20T10:00:00", "updated": "2026-11-20T10:00:00"}
try:
    read = search._Cited()
    first = search._periods(node, read)[0]
    node["created"] = node["updated"] = "2025-11-20T10:00:00"
    again = search._periods(node, read)[0]
except (AttributeError, TypeError) as exc:
    first = again = repr(exc)
check(first == [(dt.date(2026, 10, 15),) * 2] and again == [(dt.date(2025, 10, 15),) * 2],
      "date d'écriture changée (texte identique) : les dates du texte relues par rapport à elle", (first, again))

# ------------------------------------------------------------------ 3. fin de tour : graph.json lu une fois
transcript = TMP / "home" / "s.jsonl"
transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in (
    {"type": "user", "cwd": str(BOUTIQUE), "message": {"role": "user", "content": "et pour les colis ?"}},
    {"type": "assistant", "cwd": str(BOUTIQUE), "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Je regarde la configuration des envois de la boutique, rien d'autre à signaler ici."}]}},
)) + "\n", encoding="utf-8")
SID[0] += 1
sid = f"vitesse-fin-{SID[0]}"
states = STATE_DIR / "sessions"
states.mkdir(parents=True, exist_ok=True)
write_json(states / f"{sid}.json", {"injected": [new], "used": [], "cwd": str(BOUTIQUE)})


def stop():
    r = subprocess.run([sys.executable, "-I", "-S", str(DRIVER), str(CODE), "stop"], capture_output=True, cwd=str(BOUTIQUE),
                       input=json.dumps({"session_id": sid, "cwd": str(BOUTIQUE), "transcript_path": str(transcript)}).encode(),
                       env=ENV, timeout=120)
    try:
        return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])["n"]
    except (ValueError, IndexError):
        return {"erreur": r.stderr.decode("utf-8", "replace")[-600:]}


s1 = stop()
entry = json.loads((TMP / "brain" / "journal" / "sessions.json").read_text(encoding="utf-8"))["sessions"].get(sid) or {}
check(s1.get("loads") == 1 and entry.get("project") == "boutique",
      "fin de tour (souvenir montré à vérifier, journal dû) : graph.json lu une seule fois", (s1, entry))
state = json.loads((states / f"{sid}.json").read_text(encoding="utf-8"))
state.update(injected=[], journal_at=0)  # tour suivant, plus d'une minute après : journal dû, rien à vérifier
write_json(states / f"{sid}.json", state)
(TMP / "brain" / "journal" / "sessions.json").unlink()
s2 = stop()
entry = json.loads((TMP / "brain" / "journal" / "sessions.json").read_text(encoding="utf-8"))["sessions"].get(sid) or {}
check(s2.get("loads") == 0 and entry.get("project") == "boutique",
      "fin de tour suivante, graph.json inchangé : projet du journal repris sans relire le cerveau", (s2, entry))
sid = f"vitesse-fin-autre-{SID[0]}"  # autre session, même dossier : son premier tour non plus
s3 = stop()
entry = json.loads((TMP / "brain" / "journal" / "sessions.json").read_text(encoding="utf-8"))["sessions"].get(sid) or {}
check(s3.get("loads") == 0 and entry.get("project") == "boutique",
      "nouvelle session dans le même dossier : son premier journal sans relire le cerveau", (s3, entry))

# ------------------------------------------------------------------ 4. réflexe des skills
SK = TMP / "claude" / "skills"


def skill(name, desc):
    p = SK / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {name}\ndescription: \"{desc}\"\n---\n\n# {name}\n", encoding="utf-8")
    return p


T0 = time.time_ns() - 60 * 10 ** 9  # dates des fichiers fixées : rien ne dépend de la vitesse de la machine
for i, (name, desc) in enumerate((("facture-client", "À utiliser pour « préparer une facture » client."),
                                  ("article-blog", "À utiliser pour « écrire un article » de blog."),
                                  ("miniature-video", "À utiliser pour « faire une miniature » de vidéo."))):
    os.utime(skill(name, desc), ns=(T0, T0))
parsed = []
parse = skills.parse


def counted(path, *a, **k):
    parsed.append(Path(path).parent.name)
    return parse(path, *a, **k)


skills.parse = counted
kc = {"plugins": False}
first = {s["name"]: s["description"] for s in skills.index(None, kc)}
parsed.clear()
again = {s["name"]: s["description"] for s in skills.index(None, kc)}
check(len(first) == 3 and again == first and not parsed, "skills inchangées : aucun SKILL.md relu", parsed)
p = skill("article-blog", "À utiliser pour « écrire un article » de blog, et pour « relire un brouillon ».")
os.utime(p, ns=(T0 + 10 ** 9, T0 + 10 ** 9))
parsed.clear()
cat = {s["name"]: s["description"] for s in skills.index(None, kc)}
check("relire un brouillon" in cat.get("article-blog", "") and parsed == ["article-blog"],
      "SKILL.md modifié : vu au message suivant, lui seul relu", parsed)
# Écrit juste avant d'être lu, puis réécrit dans le même tic d'horloge (même taille, même date) : le contenu est vérifié.
# (horloge de skills.py figée : le test ne dépend pas de la vitesse de la machine)
skills_clock = getattr(skills, "time", None)
NOW = [T0 + 2 * 10 ** 9]
skills.time = type("Horloge", (), {"time_ns": staticmethod(lambda: NOW[0])})
try:
    p = skill("facture-client", "À utiliser pour « préparer une facture » client.")
    os.utime(p, ns=(T0 + 2 * 10 ** 9 - 10 ** 8,) * 2)
    skills.index(None, kc)
    st = os.stat(p)
    p.write_text(p.read_text(encoding="utf-8").replace("client.", "patron."), encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    NOW[0] += 5 * 10 ** 8
    cat = {s["name"]: s["description"] for s in skills.index(None, kc)}
finally:
    if skills_clock is None:
        del skills.time
    else:
        skills.time = skills_clock
check(os.stat(p).st_size == st.st_size and "patron" in cat.get("facture-client", ""),
      "SKILL.md réécrit dans le même tic d'horloge (même taille, même date) : vu quand même", cat.get("facture-client"))
skills.parse = parse
compiled = []
real_search = re.search


def spy(pattern, *a, **k):
    compiled.append(pattern)
    return real_search(pattern, *a, **k)


catalog = skills.index(None, kc)
re.search = spy
try:
    got = [r["name"] for r in skills.match("peux-tu préparer une facture pour ce client ?", catalog)]
finally:
    re.search = real_search
check(got[:1] == ["facture-client"] and not compiled, "réflexe des skills : aucune expression compilée par skill quand "
      "aucun nom de skill n'est dans le message", (got, len(compiled)))

# ------------------------------------------------------------------ 5. observations de fin de tâche
RAYONS = ("thé vert", "thé noir", "théières", "bols", "fouets", "coffrets", "encens", "baguettes", "plateaux", "tasses")
obs = [{"id": f"o{i:03d}", "at": f"2026-06-{1 + i % 28:02d}T10:{i % 60:02d}:00", "p": 1 + i % 3, "proj": "boutique",
        "t": f"Inventaire du rayon {RAYONS[i % 10]} et du rayon {RAYONS[(i * 3 + 1) % 10]} terminé, lot {100 + i}"}
       for i in range(30)]
obs.append({"id": "o900", "at": "2026-06-02T15:00:00", "p": 3, "proj": "boutique",
            "t": "Le transporteur Chronopost refuse les colis de plus de 30 kilos"})
write_json(observations.OBS_FILE, {"version": 1, "obs": obs, "digests": []}, indent=None)
words = []
tok = observations.tokenize  # (le même découpage, sous ses deux noms : l'index d'avant passait par search.tokenize)


def tcount(text, *a, **k):
    words.append(text)
    return tok(text, *a, **k)


observations.tokenize = search.tokenize = tcount
try:
    q = "le transporteur refuse les colis lourds ?"
    o1 = observations.recall(q, q, "boutique")
    words.clear()
    o2 = observations.recall(q, q, "boutique")
    check(o1 == o2 and o2 and "Chronopost" in o2[0]["t"] and len(words) <= 2,
          "observations : index gardé, pas un texte redécoupé au message suivant", (len(words), o2))
    observations.add(["🔴 Le fournisseur Marukyu passe au paiement à 60 jours"], project="boutique",
                     now=dt.datetime(2026, 6, 3, 9, 0))
    words.clear()
    o3 = observations.recall("paiement du fournisseur Marukyu ?", "paiement du fournisseur Marukyu ?", "boutique")
    check(o3 and "Marukyu" in o3[0]["t"] and len(words) <= 3,
          "observation ajoutée : vue au message suivant, seul son texte découpé", (len(words), o3))
finally:
    observations.tokenize = search.tokenize = tok
pool = observations._items()
fresh = search.Index((i, [(o["t"], 1.0)]) for i, o in enumerate(pool))
kept = observations._pool_index(pool, pool)[0] if hasattr(observations, "_pool_index") else None
diff = [x for x in ("transporteur colis", "stock matcha", "paiement", "lot rangé", "chronopost kilos")
        if kept is None or fresh.search(x, 30) != kept.search(x, 30)]
check(not diff, "observations : l'index gardé rend les mêmes résultats qu'un index refait", diff)

# ------------------------------------------------------------------ 6. imports : seulement ce dont le hook se sert


def modules(event, payload):
    data = dict({"session_id": f"imports-{event}-{SID[0]}", "cwd": str(BOUTIQUE)}, **payload)
    r = subprocess.run([sys.executable, "-X", "importtime", "-I", "-S", str(CODE / "brain.py"), "hook", event],
                       input=json.dumps(data).encode(), capture_output=True, cwd=str(BOUTIQUE), env=ENV, timeout=120)
    return {m.group(1) for m in re.finditer(r"\|\s+(brainkit\.\w+)\s*$", r.stderr.decode("utf-8", "replace"), re.M)}


HEAVY = {"brainkit.search", "brainkit.index", "brainkit.commun", "brainkit.concis", "brainkit.plugin"}
got = modules("post-compact", {"compact_summary": "Current Work: le thème de la boutique."})
check("brainkit.hooks" in got and not got & HEAVY, "compaction : ni recherche, ni index, ni cerveau commun chargés",
      sorted(got & HEAVY))
got = modules("prompt", {"prompt": "ok merci, on continue"})
check("brainkit.hooks" in got and not got & (HEAVY - {"brainkit.search"}) and "brainkit.wikistore" not in got,
      "« ok merci » : ni index, ni cerveau commun, ni lecture du cerveau", sorted(got & (HEAVY | {"brainkit.wikistore"})))
got = modules("stop", {"transcript_path": str(transcript)})
check("brainkit.hooks" in got and not got & HEAVY, "fin de tour sans souvenir à vérifier : ni recherche, ni index, ni "
      "cerveau commun", sorted(got & HEAVY))

if not remove_tree(TMP, wait=30):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
