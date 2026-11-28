"""Oublier une session (étape 21 du plan, provenance.py et oubli.py) : la session qui écrit un souvenir est notée
(`meta.sessions`, bornée) par chaque chemin d'écriture — commande lancée par Claude (CLAUDE_CODE_SESSION_ID), hook
(`session_id` de son entrée), serveur MCP — et jamais par une tâche de fond ; le journal garde l'ancien et le nouveau
texte (borné, secrets masqués, effacé par une suppression définitive) et `show --history` le montre ;
`oublier-session` montre d'abord, n'agit qu'avec --oui, archive ce que la session a seule créé, remet comme avant ce
qu'elle seule a changé, garde et dit le reste, s'annule par `restore` ; aller-retour page ↔ graphe en mode wiki ;
compatibilité avec la 8.43.0 dans les deux sens (son code est tiré de l'historique git) ; rien de plus dans les hooks.
Tout se passe dans un dossier temporaire.

Lancement : python tests/test_oubli_session.py   (sortie : « N vérifications OK, M échec(s) »)"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-oubli-test-"))
CODE = Path(__file__).resolve().parent.parent
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK",
          "CLAUDE_CODE_SESSION_ID"):
    os.environ.pop(k, None)
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "BRAIN_HOME": str(TMP / "brain"), "PYTHONUTF8": "1"})
WORK = TMP / "travail"
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))
OK, FAIL = [], []

from brainkit import common, mcp_server, provenance  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402
from brainkit.store import Brain  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-900:]}" if detail else ""))


def run(code_dir, *args, sid=None, home=None, stdin=None, extra=None):
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    if sid:
        env["CLAUDE_CODE_SESSION_ID"] = sid
    if home:
        env["BRAIN_HOME"] = str(home)
    env.update(extra or {})
    r = subprocess.run([sys.executable, "-I", "-S", str(code_dir / "brain.py"), *args], capture_output=True,
                       cwd=str(WORK), env=env, timeout=120, input=stdin)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def brain(*args, **kw):
    return run(CODE, *args, **kw)


def graph(home=None):
    return json.loads(((home or TMP / "brain") / "graph.json").read_text(encoding="utf-8"))


def sess(nid, home=None):
    return graph(home)["nodes"][nid].get("meta", {}).get("sessions")


def journal(home=None):
    f = (home or TMP / "brain") / "history" / "textes.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


A, B, C = "aaaa1111-2222-4333-8444-555566667777", "bbbb1111-2222-4333-8444-555566667777", "cccc0000-1"

# ------------------------------------------------------------------ 1. d'où vient la session
check(provenance.current() is None, "hors de Claude Code (ni hook ni CLAUDE_CODE_SESSION_ID) : aucune session")
os.environ["CLAUDE_CODE_SESSION_ID"] = A
check(provenance.current() == A, "CLAUDE_CODE_SESSION_ID (outil Bash, serveur MCP) : la session courante")
common.SESSION = B
check(provenance.current() == B, "dans un hook : le session_id de son entrée passe avant la variable")
common.SESSION = None
os.environ["BRAIN_BG"] = "1"
check(provenance.current() is None, "tâche de fond (BRAIN_BG) : aucune session, même si la variable est héritée")
os.environ.pop("BRAIN_BG")
os.environ.pop("CLAUDE_CODE_SESSION_ID")
check(provenance.clean_id("../x y;rm") == "xyrm" and provenance.clean_id("  ") is None and len(provenance.clean_id("a" * 200)) == 80,
      "id de session nettoyé (lettres, chiffres, - et _ ; 80 caractères au plus)")

# ------------------------------------------------------------------ 2. un graphe d'avant : lu tel quel, rien de réécrit
GRAPH = TMP / "brain" / "graph.json"
GRAPH.parent.mkdir(parents=True)
SECRET = "sk-ant-" + "Q" * 32
old = {"version": 1, "created": "2026-01-01T00:00:00", "nodes": {
    "vieux": {"id": "vieux", "type": "fact", "title": "Ancien souvenir", "body": f"Clé collée autrefois : {SECRET}",
              "tags": [], "project": None, "importance": 3, "created": "2026-01-01T00:00:00",
              "updated": "2026-01-01T00:00:00", "hits": 0, "last_hit": None, "source": "claude", "status": "active",
              "meta": {}}}, "edges": []}
GRAPH.write_text(json.dumps(old), encoding="utf-8")
raw = GRAPH.read_bytes()
c, out = brain("show", "vieux", sid=A)
check(c == 0 and GRAPH.read_bytes() == raw and "écrit par les sessions" not in out,
      "souvenir d'avant : lu sans réécriture, aucune session déduite", out)
check(provenance.sessions_of(old["nodes"]["vieux"]) == [] and provenance.sessions_of({"meta": {"sessions": "x1, x2"}}) == ["x1", "x2"]
      and provenance.sessions_of({"meta": {"sessions": [12345, "12345", None]}}) == ["12345"],
      "meta.sessions absent → liste vide ; écrit à la main (texte, nombre) → relu en ids")

# ------------------------------------------------------------------ 3. chaque chemin d'écriture note la session
c, out = brain("add", "-t", "fact", "-T", "Le serveur de dev écoute le port 8080", "-b", "Port HTTP du serveur.",
               "-p", "none", "--id", "port", sid=A)
check(c == 0 and sess("port") == [A], "brain add (commande de Claude) : la session notée", out)
brain("add", "-t", "decision", "-T", "La base principale est PostgreSQL 16", "-b", "Choisie pour le JSONB.",
      "-p", "none", "--id", "base", sid=A)
brain("add", "-t", "fact", "-T", "Le cache des pages est Redis", "-b", "Durée de vie : 10 minutes.", "-p", "none",
      "--id", "cache", sid=B)
brain("add", "-t", "fact", "-T", "Le transporteur est Colissimo", "-b", "Pour tous les colis.", "-p", "none",
      "--id", "colissimo", sid=B)
brain("add", "-t", "fact", "-T", "Les factures partent le lundi", "-b", "Envoi groupé.", "-p", "none", "--id", "factures")
check(sess("factures") is None, "écrit hors de Claude Code : aucune session (jamais retiré par oublier-session)")
c, out = brain("edit", "cache", "-b", "Durée de vie : 1 heure.", sid=A)
check(c == 0 and sess("cache") == [B, A], "brain edit : la session ajoutée après celle qui l'a créé", out)
brain("edit", "base", "-a", "Réplique en lecture seule.", sid=B)
brain("add", "-t", "fact", "-T", "Le transporteur est Mondial Relay", "-b", "Pour tous les colis, désormais.",
      "-p", "none", "--id", "mondial", "--replaces", "colissimo", sid=A)
check(graph()["nodes"]["colissimo"]["status"] == "archived" and A in sess("colissimo"),
      "add --replaces : l'ancien, archivé, porte la session qui l'a remplacé")
brain("link", "factures", "port")
c, out = brain("hook", "prompt", sid=None, stdin=json.dumps({"session_id": C, "cwd": str(WORK), "hook_event_name":
               "UserPromptSubmit", "prompt": "retiens que le dépôt de nuit ferme à 22 heures"}).encode())
brain("vues", "--attendre")  # (le hook met le souvenir en attente, la tâche de fond le fait entrer dans graph.json)
hooked = [n for n in graph()["nodes"].values() if "22 heures" in n.get("body", "")]
check(len(hooked) == 1 and hooked[0]["meta"].get("sessions") == [C],
      "hook « retiens que… » : la session de son entrée JSON (session_id)", out[-500:])
os.environ["CLAUDE_CODE_SESSION_ID"] = A
res = mcp_server.call_tool("memory_add", {"type": "fact", "title": "Le stock est compté le vendredi",
                                          "body": "Inventaire hebdomadaire.", "project": "none"})
os.environ.pop("CLAUDE_CODE_SESSION_ID")
mcp = [n for n in graph()["nodes"].values() if n["title"].startswith("Le stock est compté")]
check(len(mcp) == 1 and mcp[0]["meta"].get("sessions") == [A], "serveur MCP : la session de son lancement",
      json.dumps(res, ensure_ascii=False)[:300])
for i in range(7):
    brain("edit", "factures", "-i", str(1 + i % 5), sid=f"s{i}-borne")
check(sess("factures") == ["s0-borne", "s3-borne", "s4-borne", "s5-borne", "s6-borne"],
      f"au plus {provenance.SESSIONS_MAX} sessions par souvenir : la première, puis les plus récentes", sess("factures"))

# ------------------------------------------------------------------ 4. le journal des textes
rows = journal()
mod = [r for r in rows if r["id"] == "cache" and r["op"] == "modif"]
check(mod and mod[-1]["avant"] == {"body": "Durée de vie : 10 minutes."} and mod[-1]["apres"] == {"body": "Durée de vie : 1 heure."}
      and mod[-1]["s"] == A, "journal : ancien et nouveau texte, la session, seulement les champs changés", mod)
check(all(r["op"] == "ajout" and "avant" not in r for r in rows if r["id"] == "port"),
      "journal : une création est notée sans recopier son texte (il est dans le graphe)")
c, out = brain("show", "cache", "--history")
check(c == 0 and "Journal des textes" in out and "10 minutes" in out and "1 heure" in out and "session aaaa1111" in out
      and "écrit par les sessions : bbbb1111 · aaaa1111" in out, "show --history : chaque écriture, sa session, l'ancien texte", out)
brain("edit", "vieux", "-b", "Clé retirée.", sid=A)
text = (TMP / "brain" / "history" / "textes.jsonl").read_text(encoding="utf-8")
check(SECRET not in text and "masqué" in text, "journal : un secret d'un ancien texte y est masqué", text[-400:])
brain("rm", "vieux", "--purge", sid=A)
text = (TMP / "brain" / "history" / "textes.jsonl").read_text(encoding="utf-8")
check("Clé retirée" not in text and "Clé collée" not in text and any(r["id"] == "vieux" and r["op"] == "purge" for r in journal()),
      "suppression définitive : son texte quitte aussi le journal", text[-400:])
fake = [{"le": f"2026-11-01T00:00:{i:02d}", "id": "x", "op": "modif", "avant": {"body": str(i)}, "apres": {"body": str(i + 1)}}
        for i in range(25)] + [{"le": "2026-11-01T00:00:00", "id": "x", "op": "ajout"}]
kept = provenance.prune(fake)
check(len([r for r in kept if r["op"] == "modif"]) == provenance.VERSIONS_MAX and kept[-1]["op"] == "ajout"
      and kept[-2]["avant"] == {"body": "24"}, f"journal borné : {provenance.VERSIONS_MAX} modifications par souvenir, "
      "les plus récentes ; la création reste", kept[:2])
big = [{"le": "2026-11-01T00:00:00", "id": f"n{i}", "op": "modif", "avant": {"body": "x" * 5000}, "apres": {"body": "y"}}
       for i in range(600)]
check(sum(len(json.dumps(r)) for r in provenance.prune(big)) <= provenance.JOURNAL_MAX // 2,
      "journal borné en taille : les modifications les plus anciennes partent")

# ------------------------------------------------------------------ 5. oublier-session : montrer d'abord
c, out = brain("oublier-session")
check(c == 0 and A in out and B in out and C in out, "oublier-session sans id : les sessions qui ont écrit", out)
before = GRAPH.read_bytes()
c, out = brain("oublier-session", "aaaa")
check(c == 0 and GRAPH.read_bytes() == before, "aperçu (début de l'id) : rien n'est touché sans --oui", out)
part = lambda title: out.split(title, 1)[1].split("\n\n")[0] if title in out else ""  # noqa: E731
check("`port`" in part("À retirer") and "`mondial`" in part("À retirer") and "← lié depuis `factures`" in out,
      "à retirer : ce que la session a seule créé ; un lien qui y mène depuis un autre souvenir est dit", out)
check("`cache`" in part("À remettre") and "`colissimo`" in part("À remettre") and "--oui" in out,
      "à remettre comme avant : ce qu'elle seule a changé (contenu, remplacement)", out)
check("`base`" in part("Gardés") and "repris ensuite par la session bbbb1111" in out,
      "gardé et dit : créé par elle mais repris par une autre session", out)
check("- `factures`" not in out and "- `vieux`" not in out,
      "écrit sans session, ou par d'autres : jamais retiré", out)
c, out = brain("oublier-session", "zzzz9999")
check(c == 0 and "Rien d'écrit" in out, "session inconnue : rien à faire, et c'est dit", out)
brain("add", "-t", "fact", "-T", "Note de la session jumelle", "-b", "Pour le préfixe.", "-p", "none", sid="aaaa1111-other")
c, out = brain("oublier-session", "aaaa1111")
check(c != 0 and "désigne 2 sessions" in out, "début d'id ambigu : refusé, les sessions citées", out)

# ------------------------------------------------------------------ 6. … puis faire, sur accord
g = graph()
g["nodes"]["port"]["body"] = "Port HTTP du serveur."  # (inchangé)
GRAPH.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
c, out = brain("oublier-session", A, "--oui", sid=B)
g = graph()
check(c == 0 and g["nodes"]["port"]["status"] == "archived" and g["nodes"]["mondial"]["status"] == "archived"
      and "port" in g["nodes"], "--oui : créés par elle seule → archivés (réversibles), comme `brain rm`", out)
check(g["nodes"]["cache"]["body"] == "Durée de vie : 10 minutes." and A not in (g["nodes"]["cache"]["meta"].get("sessions") or []),
      "--oui : son changement d'un souvenir d'une autre session est défait, et la session n'y est plus notée",
      g["nodes"]["cache"])
check(g["nodes"]["colissimo"]["status"] == "active" and not g["nodes"]["colissimo"]["meta"].get("superseded_by"),
      "--oui : le souvenir qu'elle avait remplacé redevient actif", g["nodes"]["colissimo"])
check("Réplique en lecture" in g["nodes"]["base"]["body"] and g["nodes"]["base"]["status"] == "active",
      "--oui : ce qu'une autre session a repris reste tel quel", g["nodes"]["base"])
check(B not in (g["nodes"]["port"]["meta"].get("sessions") or []) and any(r.get("oubli") == A for r in journal()),
      "l'oubli est noté au journal comme tel : la session qui le lance n'en devient pas l'auteur")
c, out = brain("oublier-session", A)
check(c == 0 and "À retirer" not in out and "À remettre" not in out, "second passage : rien à refaire", out)
c, out = brain("restore", "1")
g = graph()
check(c == 0 and g["nodes"]["port"]["status"] == "active" and g["nodes"]["cache"]["body"] == "Durée de vie : 1 heure.",
      "`brain restore 1` annule l'oubli (instantané pris avant)", out)

# texte changé hors du cerveau (Obsidian, rêve) après la session : gardé, dit
g["nodes"]["cache"]["body"] = "Durée de vie : 2 heures (écrit dans Obsidian)."
GRAPH.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
c, out = brain("oublier-session", A)
check("`cache`" in part("Gardés") and "changé depuis hors du cerveau" in out,
      "changé depuis hors du journal (Obsidian, rêve…) : gardé, jamais écrasé", out)
c, out = brain("oublier-session", C, "--oui", "--purge")
check(c == 0 and not [n for n in graph()["nodes"].values() if "22 heures" in n.get("body", "")],
      "--purge : supprimé définitivement (comme `rm --purge`)", out)
brain("add", "-t", "project", "-T", "Projet Atelier", "-b", "Dossier atelier.", "-p", "none", "--id", "atelier", sid="dddd-projet")
c, out = brain("oublier-session", "dddd-projet")
check("`atelier`" in part("Gardés") and "projet créé" in out, "un projet n'est jamais retiré : gardé et dit", out)

# ------------------------------------------------------------------ 7. mode wiki : aller-retour page ↔ graphe
WHOME, WIKI = TMP / "brain-wiki", TMP / "wiki"
c, out = brain("wiki", "init", str(WIKI), home=WHOME)
check(c == 0, "wiki : créé", out)
brain("add", "-t", "fact", "-T", "Le local ouvre à 8 heures", "-b", "Du lundi au samedi.", "-p", "none", "--id", "local",
      sid="12345678", home=WHOME)
brain("edit", "local", "-a", "Fermé le dimanche.", sid=A, home=WHOME)
page = next(WIKI.rglob("Le local ouvre*.md")).read_text(encoding="utf-8")
check("sessions:" in page and "12345678" in page and A in page, "page : propriété « sessions »", page[:600])
want = graph(WHOME)["nodes"]["local"]["meta"]
(WHOME / "graph.json").unlink()
for f in WHOME.rglob("wiki-pages.json"):
    f.unlink()
c, out = brain("show", "local", home=WHOME)
got = graph(WHOME)["nodes"]["local"]["meta"]
check(got.get("sessions") == ["12345678", A] == want.get("sessions") and "écrit par les sessions : 12345678" in out,
      "cache refait depuis les seules pages : les sessions reviennent, en texte (même un id tout en chiffres)", (want, got))
c, out = brain("oublier-session", "12345678", home=WHOME)
check("`local`" in out and "Gardés" in out, "wiki : oublier-session lit la provenance des pages", out)

# ------------------------------------------------------------------ 8. la 8.43.0 et un graphe récent, dans les deux sens
OLD_REFS = ("cerveau--v8.43.0", "91bcddc")


def old_code():
    for ref in OLD_REFS:
        if subprocess.run(["git", "-C", str(CODE), "cat-file", "-e", f"{ref}:brainkit/provenance.py"],
                          capture_output=True).returncode == 0:
            continue  # pas la 8.43.0
        r = subprocess.run(["git", "-C", str(CODE), "archive", ref, "brain.py", "brainkit"], capture_output=True)
        if r.returncode == 0:
            dest = TMP / "v843"
            dest.mkdir()
            with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
                try:
                    tar.extractall(dest, filter="data")
                except TypeError:  # Python 3.10 et 3.11 sans le filtre
                    tar.extractall(dest)
            return dest
    sys.exit("✗ code de la 8.43.0 introuvable dans ce dépôt (" + ", ".join(OLD_REFS) + ") : `git fetch --unshallow`")


V843 = old_code()
c, out = run(V843, "show", "base")
check(c == 0 and "PostgreSQL 16" in out, "8.43.0 : lit un souvenir du graphe récent", out)
c, out = run(V843, "add", "-t", "fact", "-T", "Écrit par la 8.43.0", "-b", "Un fait de l'ancienne version.", "-p", "none",
             "--id", "ancien-code", sid=B)
g = graph()
check(c == 0 and g["nodes"]["base"]["meta"].get("sessions") == [A, B] and "sessions" not in g["nodes"]["ancien-code"].get("meta", {}),
      "8.43.0 : son écriture garde les sessions des autres souvenirs (elle n'en note pas)", out)
c, out = brain("show", "ancien-code")
check(c == 0 and "Écrit par la 8.43.0" in out and "écrit par les sessions" not in out,
      "souvenir écrit par la 8.43.0 : lu tel quel, sans session", out)
c, out = run(V843, "edit", "local", "-a", "Ouvert les jours fériés.", home=WHOME)
page = next(WIKI.rglob("Le local ouvre*.md")).read_text(encoding="utf-8")
c2, out2 = brain("show", "local", home=WHOME)
check(c == 0 and "12345678" in page and "écrit par les sessions : 12345678" in out2,
      "wiki : une page réécrite par la 8.43.0 garde ses sessions", page[:600])

# ------------------------------------------------------------------ 9. budgets : rien de plus dans les hooks
r = subprocess.run([sys.executable, "-I", "-S", "-X", "importtime", str(CODE / "brain.py"), "hook", "prompt"],
                   input=json.dumps({"session_id": C, "cwd": str(WORK), "prompt": "ok merci"}).encode(),
                   capture_output=True, cwd=str(WORK), env=dict(os.environ), timeout=60)
check("brainkit.provenance" not in r.stderr.decode("utf-8", "replace"),
      "hook d'un message sans écriture : provenance.py n'est pas chargé")
NB = 3000
data = {"version": 1, "nodes": {f"m{i}": {"id": f"m{i}", "type": "fact", "title": f"Souvenir numéro {i}",
                                          "body": f"Texte du souvenir {i} " * 8, "tags": ["essai"], "project": None,
                                          "importance": 3, "created": "2026-11-01T00:00:00",
                                          "updated": "2026-11-01T00:00:00", "status": "active",
                                          "meta": {"sessions": [A]}} for i in range(NB)}, "edges": []}
b = Brain(data)
calls = []
real_rows, provenance.rows = provenance.rows, lambda *a: calls.append(1) or real_rows(*a)
t0 = time.perf_counter()
b.update("m7", body="Texte changé.")
provenance.on_save(b)
spent = (time.perf_counter() - t0) * 1000
provenance.rows = real_rows
check(spent < 15 and not calls, f"écriture d'un souvenir parmi {NB} : provenance et journal en {spent:.1f} ms, sans relire "
      "le journal", spent)
check(len(json.dumps(data["nodes"]["m7"]["meta"])) < 200, "meta.sessions bornée : le graphe ne grossit pas avec les sessions")

remove_tree(TMP)
print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
