"""Démarrage, fin de session et compaction sans attente (étape 4 du plan, « Vitesse ») : l'analyse du graphe n'est jamais
calculée dans un hook (la précédente sert, le recalcul part en arrière-plan), l'index du démarrage est gardé tant que
rien de ce qu'il montre n'a changé, la fin de session et la compaction confient visualisation et index à une tâche de
fond, et un fichier énorme de la mémoire de Claude Code n'est pas importé. Aucune mesure de temps (trop variable en CI) :
le verrou de la tâche de fond, tenu par le test, montre ce que fait le hook et ce qui attend la tâche.

Lancement : python tests/test_demarrage.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-demarrage-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update(CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1")
WORK, WORK2 = TMP / "boutique", TMP / "potager"
for d in (WORK, WORK2, TMP / "home", TMP / "claude", TMP / "brain" / "state"):
    d.mkdir(parents=True)
os.chdir(TMP)
sys.path.insert(0, str(CODE))

from brainkit import graph, index, install, store  # noqa: E402
from brainkit.common import GRAPH_FILE, INDEX_FILE, STATE_DIR, FileLock, load_config, read_json, remove_tree  # noqa: E402
from brainkit.store import Brain  # noqa: E402

LOCK, MARK = STATE_DIR / "index-fond.lock", STATE_DIR / "index-fond.lance"  # tâche de fond : verrou, dernier lancement
CACHE, VIZ = STATE_DIR / "demarrage.json", TMP / "brain" / "cerveau.html"
KEPT = "⟦GARDÉ⟧"  # marque glissée dans un index gardé : la revoir prouve qu'il n'a pas été refait


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def hook(event, sid, cwd=WORK, **extra):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", event],
                       input=json.dumps({"session_id": sid, "cwd": str(cwd), **extra}).encode(), capture_output=True,
                       env=dict(os.environ), cwd=str(cwd), timeout=180)
    out = r.stdout.decode("utf-8", "replace")
    try:  # la sortie du hook est UN objet JSON
        return json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
    except ValueError:
        return {"brut": out + r.stderr.decode("utf-8", "replace")}


def ctx(obj) -> str:
    return (obj.get("hookSpecificOutput") or {}).get("additionalContext") or obj.get("brut", "")


def brain(*args):
    r = subprocess.run([sys.executable, str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       env=dict(os.environ), cwd=str(TMP), timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def wait(cond, limit=90.0) -> bool:
    end = time.time() + limit
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return bool(cond())


def idle():
    """Attend la fin de la tâche de fond en cours (elle tient son verrou pendant tout son travail)."""
    with FileLock(LOCK, timeout=180):
        pass


def analysis_sig():
    return (read_json(graph.ANALYSIS_FILE, {}) or {}).get("sig")


def current_sig():
    return graph._signature(Brain.load())


def entry(slot) -> dict:
    data = read_json(CACHE, None)
    found = ((data.get("items") or {}).get(slot) if isinstance(data, dict) else None) or {}
    return found if isinstance(found, dict) else {}


def tamper(slot) -> bool:
    """Glisse la marque dans l'index gardé de `slot` (projet, ou "" hors projet). Faux s'il n'y en a pas."""
    data = read_json(CACHE, None)
    found = ((data or {}).get("items") or {}).get(slot) if isinstance(data, dict) else None
    if not isinstance(found, dict) or not isinstance(found.get("text"), str):
        return False
    found["text"] += f"\n{KEPT}"
    CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return True


def add(ntype, title, body, project="boutique"):
    with Brain.edit() as b:
        b.add(ntype, title, body, project=project)


# ------------------------------------------------------------------ cerveau d'essai : deux projets, du vocabulaire commun
OLD = "2026-03-10T09:00:00"


def node(nid, ntype, title, body, project=None, **meta):
    return {"id": nid, "type": ntype, "title": title, "body": body, "tags": [], "project": project, "importance": 3,
            "created": OLD, "updated": OLD, "hits": 0, "source": "utilisateur", "status": "active", "meta": meta}


nodes = [node("boutique", "project", "Boutique Atelier", "Boutique Shopify de céramique.", path=str(WORK)),
         node("potager", "project", "Potager du jardin", "Le potager familial.", path=str(WORK2)),
         node("vouvoyer", "feedback", "Toujours vouvoyer les clients", "Dans les e-mails, toujours le vouvoiement."),
         node("profil", "user", "Utilisateur francophone", "Préfère des réponses en français.")]
subjects = ["livraison Colissimo", "thème Dawn", "transporteur Mondial Relay", "photos des vases", "prix des bols",
            "fiche produit tasse", "frais de port", "emballage des colis", "retours clients", "stock des assiettes"]
nodes += [node(f"b{i}", ("fact", "learning", "decision")[i % 3], f"Boutique : {s} ({i})",
               f"Pour la boutique, {s} : réglage numéro {i}, vu avec le transporteur et le thème.", "boutique")
          for i, s in enumerate(subjects * 2)]
nodes += [node(f"p{i}", "fact", f"Potager : {s}", f"Au potager, {s}.", "potager")
          for i, s in enumerate(["tomates cerises", "arrosage goutte à goutte", "compost", "semis de radis"])]
GRAPH_FILE.write_text(json.dumps({"version": 1, "created": OLD, "nodes": {n["id"]: n for n in nodes}, "edges": [
    {"from": "b0", "to": "b1", "rel": "relates", "created": OLD[:10]}]}), encoding="utf-8")
now = dt.datetime.now().replace(microsecond=0).isoformat()
# Rien d'autre en arrière-plan : ni carte (elle réécrit le projet), ni mode éco, sauvegarde, rattrapage, garde, veille PC
(TMP / "brain" / "config.json").write_text(json.dumps({
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "journal": {"rattrapage_le": now}, "garde": {"le": now}}), encoding="utf-8")
(STATE_DIR / "last_consolidate").write_text(now, encoding="utf-8")
brain("report")  # analyse du graphe à jour au départ
hook("session-start", "s0")
idle()

# ------------------------------------------------------------------ 1. démarrage après un changement : l'analyse attend
with FileLock(LOCK, timeout=180):  # la tâche de fond ne peut pas passer tant que le test tient son verrou
    if MARK.exists():
        MARK.unlink()
    before = analysis_sig()
    add("feedback", "Répondre aux avis clients sous 24 h", "Chaque avis client reçoit une réponse sous 24 heures.")
    after = current_sig()
    text = ctx(hook("session-start", "a1"))
    stale = analysis_sig() == before != after
    check(stale and MARK.is_file() and "Projet courant : Boutique Atelier" in text
          and "Répondre aux avis clients sous 24 h" in text,
          "démarrage après un changement : l'analyse du graphe n'est pas refaite dans le hook (la précédente sert, son "
          "recalcul est lancé), l'index est injecté avec le nouveau souvenir",
          f"analyse {analysis_sig()} (avant {before}, contenu {after}) · lancé {MARK.is_file()} · {text[:300]}")
fresh = wait(lambda: analysis_sig() == after)
check(stale and fresh, "l'analyse est refaite par la tâche de fond, dès qu'elle peut passer", analysis_sig())
idle()
got = entry("boutique")
check(got.get("stale") is False and "Répondre aux avis clients sous 24 h" in (got.get("text") or ""),
      "la tâche de fond prépare aussi l'index du démarrage du projet, avec l'analyse à jour", got)

# ------------------------------------------------------------------ 2. index du démarrage gardé tant que rien ne change
hook("session-start", "b1")
tampered = tamper("boutique")
kept = KEPT in ctx(hook("session-start", "b2"))
store.bump_hits(["b3", "b4", "vouvoyer"])  # compteurs de rappel : ils réécrivent graph.json à chaque message
with Brain.edit() as b:  # date de la carte du projet : le cartographe la réécrit à chaque passage
    b.nodes["boutique"]["meta"]["mapped"] = now
    b.dirty = True
counters = KEPT in ctx(hook("session-start", "b3"))
check(tampered and kept and counters, "index du démarrage gardé tant que rien de ce qu'il montre ne change (ni les "
      "compteurs de rappel ni la date de la carte ne le font refaire)", f"gardé {tampered} {kept} · compteurs {counters}")
add("feedback", "Emballer chaque bol dans du papier kraft", "Jamais de plastique dans les colis.")
text = ctx(hook("session-start", "b4"))
check(kept and KEPT not in text and "Emballer chaque bol dans du papier kraft" in text,
      "index du démarrage refait quand un souvenir change", text[:300])
c, out = brain("index", "--auto", "-p", "boutique", "-p", "potager")  # la tâche de fond, lancée à la main : attendue
got = entry("boutique")
check(c == 0 and analysis_sig() == current_sig() and got.get("stale") is False and entry("potager").get("text")
      and "Emballer chaque bol" in (got.get("text") or "") and INDEX_FILE.exists(),
      "brain index --auto : analyse, BRAIN.md et index du démarrage des projets demandés refaits", out[-300:])

hook("session-start", "c1")
tampered = tamper("boutique")
other = ctx(hook("session-start", "c2", cwd=WORK2))
back = ctx(hook("session-start", "c3"))
check(tampered and KEPT not in other and "Projet courant : Potager du jardin" in other and KEPT in back,
      "index du démarrage propre à chaque projet : un autre projet a le sien, celui du premier reste gardé",
      f"{tampered} · {other[:200]} · {back[-200:]}")


class Tomorrow(dt.date):
    @classmethod
    def today(cls):
        return dt.date.today() + dt.timedelta(days=1)


today_text = index.session_context(Brain.load(), str(WORK), load_config())[0]
saved, index._dt = index._dt, types.SimpleNamespace(date=Tomorrow, datetime=dt.datetime, timedelta=dt.timedelta)
try:
    tomorrow_text = index.session_context(Brain.load(), str(WORK), load_config())[0]
finally:
    index._dt = saved
check(KEPT in today_text and KEPT not in tomorrow_text and "Projet courant : Boutique Atelier" in tomorrow_text,
      "index du démarrage refait le lendemain (« dans 3 j » change chaque jour)", tomorrow_text[:200])

# Hors projet, BRAIN.md : régénéré quand graph.json est plus récent (test_noyau), sans être refait si seuls les compteurs
# ont bougé.
index.rebuild(Brain.load())
tampered = tamper("")
old = time.time() - 30
os.utime(INDEX_FILE, (old, old))
store.bump_hits(["p1"])
again = index.ensure_index(Brain.load())
check(tampered and KEPT in again and INDEX_FILE.read_text(encoding="utf-8") == again,
      "hors projet : BRAIN.md plus vieux que graph.json à cause des compteurs → réécrit tel quel, pas refait", again[-200:])
idle()

# ------------------------------------------------------------------ 3. fin de session et compaction : en arrière-plan
transcript = TMP / "claude" / "projects" / "-boutique" / "s1.jsonl"
transcript.parent.mkdir(parents=True)
transcript.write_text("\n".join(json.dumps(x) for x in [
    {"type": "user", "cwd": str(WORK), "message": {"role": "user", "content": "règle le thème de la boutique"}},
    {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "Fait."}]}},
]) + "\n", encoding="utf-8")
store.bump_hits(["b5"])  # graph.json plus récent que la visualisation : elle est à refaire
viz_before = VIZ.stat().st_mtime_ns if VIZ.exists() else None
with FileLock(LOCK, timeout=180):
    if MARK.exists():
        MARK.unlink()
    os.utime(INDEX_FILE, (old, old))
    index_before = INDEX_FILE.stat().st_mtime_ns
    hook("session-end", "e1", transcript_path=str(transcript))
    viz_kept = (VIZ.stat().st_mtime_ns if VIZ.exists() else None) == viz_before
    index_kept = INDEX_FILE.stat().st_mtime_ns == index_before
    sessions = (read_json(TMP / "brain" / "journal" / "sessions.json", {}) or {}).get("sessions") or {}
    check(viz_kept and index_kept and MARK.is_file() and "e1" in sessions,
          "fin de session : ni visualisation ni index refaits dans le hook (le journal, lui, y est écrit), la tâche "
          "de fond est lancée", f"viz {viz_kept} · index {index_kept} · lancé {MARK.is_file()} · {list(sessions)}")
done = wait(lambda: VIZ.exists() and VIZ.stat().st_mtime_ns != viz_before)
check(viz_kept and done, "fin de session : la tâche de fond refait la visualisation (cerveau.html)", VIZ.exists())
idle()

with FileLock(LOCK, timeout=180):
    if MARK.exists():
        MARK.unlink()
    os.utime(INDEX_FILE, (old, old))
    index_before = INDEX_FILE.stat().st_mtime_ns
    hook("pre-compact", "e2", transcript_path=str(transcript))
    check(INDEX_FILE.stat().st_mtime_ns == index_before and MARK.is_file(),
          "avant une compaction : l'index n'est pas refait dans le hook, la tâche de fond le prépare", MARK.is_file())
idle()

spec = json.loads((CODE / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
flags = {event: [h.get("async") for e in entries for h in e["hooks"]] for event, entries in spec.items()}
check(flags.get("PreCompact") == [True] and all(v == [None] for k, v in flags.items() if k != "PreCompact"),
      "hooks.json : PreCompact lancé sans être attendu (async : sa sortie ne sert à rien), les autres attendus", flags)
mine = install.merged_settings({})["hooks"]
flags = {event: [h.get("async") for e in entries for h in e["hooks"]] for event, entries in mine.items()}
check(flags.get("PreCompact") == [True] and all(v == [None] for k, v in flags.items() if k != "PreCompact"),
      "installation classique (settings.json) : les mêmes hooks sans attente que le plugin", flags)

# ------------------------------------------------------------------ 4. mémoire de Claude Code : pas de fichier énorme
mem = TMP / "claude" / "projects" / "-notes" / "memory"
mem.mkdir(parents=True)
(mem / "petit.md").write_text("---\nname: petit\ndescription: Préférence de café\ntype: user\n---\nCafé serré le matin.\n",
                              encoding="utf-8")
(mem / "enorme.md").write_text("---\nname: enorme\ndescription: Journal collé\ntype: reference\n---\n"
                               + "Une ligne de journal collée par erreur dans la mémoire.\n" * 1300, encoding="utf-8")
warn = hook("session-start", "i1").get("systemMessage") or ""
origins = {(n.get("meta") or {}).get("origin") for n in Brain.load().nodes.values()}
again = hook("session-start", "i2").get("systemMessage") or ""
check("enorme.md" in warn and "brain import --max-ko 0" in warn and "enorme.md" not in again
      and str(mem / "petit.md") in origins and str(mem / "enorme.md") not in origins,
      "mémoire de Claude Code : un fichier de plus de 64 Ko n'est pas importé, dit une fois (lequel, et comment "
      "l'importer quand même), les autres le sont", f"{warn} · {again}")
c, out = brain("import", "--max-ko", "0")
origins = {(n.get("meta") or {}).get("origin") for n in Brain.load().nodes.values()}
check(c == 0 and str(mem / "enorme.md") in origins, "brain import --max-ko 0 : le fichier énorme importé quand même",
      out[-300:])
idle()

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
