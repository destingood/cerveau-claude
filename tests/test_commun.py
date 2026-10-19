"""Vérifications du cerveau commun (commun.py) — deux amis, un dépôt « GitHub » local, des dossiers temporaires.

Le plus important : rien de privé n'entre JAMAIS dans le dépôt commun (tout son historique git est fouillé).
Lancement : python tests/test_commun.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-commun-test-"))
CODE = Path(__file__).resolve().parent.parent
BARE = TMP / "cerveau-commun.git"
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "BRAIN_HOME", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(k, None)


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def env(who, fg=True, **extra):
    e = dict(os.environ, CLAUDE_CONFIG_DIR=str(TMP / who / "claude"), BRAIN_HOME=str(TMP / who / "brain"),
             BRAIN_COMMUN_DELAY="2")  # envoi différé de 2 s (15 s en vrai) : les vraies tâches de fond restent rapides
    e.update(extra)
    if fg:
        e["BRAIN_COMMUN_FG"] = "1"  # synchronisations immédiates (déterministes) ; sans : en arrière-plan, comme en vrai
    else:
        e.pop("BRAIN_COMMUN_FG", None)
    return e


def brain(who, *args, inp=None, fg=True, cwd=None, xenv=None):
    (TMP / who / "work").mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *args], input=(inp or "").encode("utf-8"),
                       capture_output=True, cwd=str(cwd or TMP / who / "work"), env=env(who, fg, **(xenv or {})),
                       timeout=180)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def hook(who, event, payload, fg=True):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", event],
                       input=json.dumps(payload).encode(), capture_output=True, cwd=str(TMP / who / "work"),
                       env=env(who, fg), timeout=180)
    return r.stdout.decode("utf-8", "replace")


def bare_files():
    r = subprocess.run(["git", "-C", str(BARE), "ls-tree", "-r", "-z", "--name-only", "HEAD"], capture_output=True)
    return [f for f in r.stdout.decode("utf-8", "replace").split("\0") if f]


def bare_history():
    """Tout ce qui est jamais entré dans le dépôt commun : contenu de chaque version de chaque fichier."""
    r = subprocess.run(["git", "-C", str(BARE), "log", "--all", "-p", "--no-color"], capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def graph(who):
    p = TMP / who / "brain" / "graph.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(BARE)], check=True)

# ------------------------------------------------------------------ 1. Alice et ce qu'elle sait (privé et partageable)
(TMP / "alice" / "projets" / "fleurs").mkdir(parents=True)
(TMP / "alice" / "projets" / "site").mkdir(parents=True)
A = "alice"
FAKE_KEY = "sk-" + "ant-api03-" + "abcdefghijklmnopqrstuvwxyz123456"  # fausse clé, assemblée ici : pas de secret dans le fichier
steps = [
    ["add", "-t", "user", "-T", "Alice, fleuriste", "-b", "Vit à Lyon, 34 ans."],
    ["add", "-t", "feedback", "-T", "Toujours vouvoyer", "-b", "Préférence d'Alice."],
    ["proj", "add", str(TMP / "alice" / "projets" / "fleurs"), "-T", "Boutique fleurs", "-b", "La boutique d'Alice."],
    ["proj", "add", str(TMP / "alice" / "projets" / "site"), "-T", "Site commun", "-b", "Le site fait à plusieurs."],
    ["add", "-t", "fact", "-T", "Marge fleurs quarante pour cent", "-b", "Marge brute des bouquets.", "-p", "boutique-fleurs"],
    ["add", "-t", "todo", "-T", "Refaire la page d'accueil", "-b", "Avec les nouvelles photos.", "-p", "site-commun",
     "--due", "dans 2 semaines"],
    ["add", "-t", "learning", "-T", "Les robots faussent les stats Shopify", "-b",
     "Filtrer par pays. Contact : jean.dupont@example.org, 06 12 34 56 78. Fichier C:\\Users\\Alice\\Documents\\stats.xlsx. "
     "Voir [[marge-fleurs-quarante-pour-cent]] et [[site-commun]].", "-p", "none"],
    ["add", "-t", "learning", "-T", "Conseil sur le thé vert", "-b", "Mon médecin le conseille pour mon traitement.", "-p", "none"],
    ["add", "-t", "concept", "-T", "Dropshipping", "-b", "Vendre sans stock.", "-p", "none"],
    ["add", "-t", "concept", "-T", "Recette maison des bouquets", "-b", "Le secret des bouquets.", "-p", "none", "--commun", "non"],
    ["add", "-t", "fact", "-T", "Le marché aux fleurs ouvre à cinq heures", "-b", "À Rungis.", "-p", "none", "--commun", "oui"],
    ["add", "-t", "entity", "-T", "Jean Dupont", "-b", "Fournisseur de roses.", "-p", "none", "--tags", "contact"],
    ["add", "-t", "decision", "-T", "Passer à Colissimo", "-b", "Moins cher pour les envois.", "-p", "none"],
    ["add", "-t", "learning", "-T", "Clé de la boutique", "-b", "api_key = " + FAKE_KEY,
     "-p", "none"],
    ["add", "-t", "reference", "-T", "Tableau de bord des ventes", "-b", "Sur le grafana interne.", "-p", "none"],
    ["add", "-t", "entity", "-T", "Shopify", "-b", "Plateforme de boutiques en ligne.", "-p", "none", "--tags", "plateforme"],
    ["add", "-t", "entity", "-T", "Marie Lefèvre", "-b", "Rencontrée au salon.", "-p", "none"],
    ["add", "-t", "learning", "-T", "Photos produits sur fond blanc", "-b",
     "Exemples : https://docs.google.com/presentation/d/1AbCdEfGh/edit et https://fr.wikipedia.org/wiki/Photographie. "
     "Réunion : https://meet.google.com/abc-defg-hij.", "-p", "none", "--tags", "boutique-fleurs,photo"],
    ["add", "-t", "concept", "-T", "Ancien nom confidentiel", "-b", "Garder ses clients.", "-p", "none"],
    ["edit", "ancien-nom-confidentiel", "-T", "Fidélisation client"],
    ["add", "-t", "learning", "-T", "Mon budget du mois", "-b", "Mes dépenses ont doublé.", "-p", "none"],
    ["add", "-t", "concept", "-T", "Routine du matin", "-b", "Méditation dix minutes.", "-p", "none", "--domaine", "perso"],
]
for args in steps:
    code, out = brain(A, *args)
    check(code == 0, f"alice : {' '.join(args[:4])}", out)

PRIVATE = ["fleuriste", "Lyon", "34 ans", "vouvoyer", "Marge fleurs", "Marge brute", "médecin", "traitement",
           "Recette maison", "secret des bouquets", "Jean Dupont", "roses", "Colissimo", "jean.dupont@example.org",
           "06 12 34 56 78", "Alice\\Documents", "C:\\Users", "sk-ant", "masqué", "Boutique fleurs",
           "La boutique d'Alice", "Clé de la boutique", "Tableau de bord", "grafana", "Marie Lefèvre", "Rencontrée",
           "docs.google.com", "1AbCdEfGh", "meet.google.com", "abc-defg-hij", "boutique-fleurs", "ancien-nom",
           "Ancien nom", "Mon budget", "dépenses", "Routine du matin", "Méditation"]

# ------------------------------------------------------------------ 2. aperçu, accord, adhésion
code, out = brain(A, "config", "commun.repo", str(BARE))
code, out = brain(A, "commun", "apercu")
check("Les robots faussent les stats Shopify" in out and "Dropshipping" in out and "marché aux fleurs" in out
      and "Alice, fleuriste" not in out and "Conseil sur le thé vert" not in out, "aperçu : ce qui partirait, sans le privé", out)
check("Boutique fleurs" in out and "Site commun" in out and "privés tant que" in out, "aperçu : projets privés par défaut", out)
code, out = brain(A, "commun", "rejoindre", "--nom", "alice")
check(code == 0 and "--oui" in out and not (TMP / A / "brain" / "commun" / ".git").exists() and not bare_files(),
      "rejoindre sans --oui : aperçu seulement, rien d'envoyé", out)
code, out = brain(A, "commun", "projet", "site-commun")
check(code == 0 and "commun" in out, "partager un projet", out)
code, out = brain(A, "commun", "rejoindre", "--oui", "--nom", "alice")
check(code == 0 and "membre « alice »" in out, "alice rejoint le cerveau commun", out)
files = bare_files()
expect = ["membres/alice/wiki/Apprentissages/Les robots faussent les stats Shopify.md", "membres/alice/wiki/Concepts/Dropshipping.md",
          "membres/alice/wiki/Faits/Le marché aux fleurs ouvre à cinq heures.md",
          "membres/alice/wiki/À faire/Refaire la page d'accueil.md", "membres/alice/wiki/Projets/Site commun.md",
          "membres/alice/wiki/Entités/Shopify.md", "membres/alice/wiki/Apprentissages/Photos produits sur fond blanc.md",
          "membres/alice/wiki/Concepts/Fidélisation client.md", "CLAUDE.md", "README.md", ".cerveau-commun"]
for f in expect:
    check(f in files, f"dépôt commun : {f}", "\n".join(files))
pages = [f for f in files if f.startswith("membres/alice/wiki/")]
check(len(pages) == 8, "dépôt commun : exactement 8 pages partagées par alice", "\n".join(pages))
hist = bare_history()
for word in PRIVATE:
    check(word not in hist, f"vie privée : « {word} » n'est jamais entré dans le dépôt commun")
learn = subprocess.run(["git", "-C", str(BARE), "show", "HEAD:membres/alice/wiki/Apprentissages/Les robots faussent les stats Shopify.md"],
                       capture_output=True).stdout.decode("utf-8")
check("«e-mail»" in learn and "«téléphone»" in learn and "[chemin]" in learn, "coordonnées et chemins retirés", learn)
check("[privé]" in learn and "[[Site commun]]" in learn, "lien vers une page privée → [privé] ; vers un projet commun : gardé", learn)
check("par: alice" in learn and "chemin:" not in hist.split("membres/alice/wiki/Projets/Site commun.md")[-1][:600],
      "auteur indiqué, aucun chemin de projet", learn)


def shown(rel):
    return subprocess.run(["git", "-C", str(BARE), "show", f"HEAD:{rel}"], capture_output=True).stdout.decode("utf-8")


photo = shown("membres/alice/wiki/Apprentissages/Photos produits sur fond blanc.md")
check(photo.count("[lien privé]") == 2 and "https://fr.wikipedia.org/wiki/Photographie" in photo and "photo" in photo,
      "liens d'accès (Drive, Meet) retirés, lien public gardé", photo)
fid = shown("membres/alice/wiki/Concepts/Fidélisation client.md")
check("id: p-" in fid, "renommé : l'id qui garde l'ancien titre est remplacé par une empreinte", fid)
code, out = brain(A, "commun", "apercu")
check("référence" not in out.split("Reste privé")[0] and "entité sans source publique" in out and "domaine perso" in out
      and "sensible" in out, "aperçu : raisons de ce qui reste privé", out)

# ------------------------------------------------------------------ 3. Bob (cerveau en wiki) reçoit les pages d'Alice
B = "bob"
code, out = brain(B, "add", "-t", "user", "-T", "Bob, cuisinier", "-b", "Vit à Nantes.")
code, out = brain(B, "add", "-t", "learning", "-T", "Les robots faussent les stats Shopify", "-b", "Ma version : exclure les USA.",
                  "-p", "none")
code, out = brain(B, "wiki", "init", str(TMP / B / "wiki"), "--no-push")
check(code == 0, "bob : cerveau en wiki", out)
code, out = brain(B, "config", "commun.repo", str(BARE))
code, out = brain(B, "commun", "rejoindre", "--oui", "--nom", "bob")
check(code == 0 and "alice" in out and "membre « bob »" in out, "bob rejoint et voit alice", out)
code, out = brain(B, "q", "dropshipping vendre sans stock")
check("🤝 alice" in out and "Dropshipping" in out, "bob : la page d'alice dans sa recherche (🤝 alice)", out)
o = hook(B, "prompt", {"session_id": "b1", "cwd": str(TMP / B / "work"), "prompt": "comment vendre sans stock en dropshipping ?"})
check("🤝 alice" in o and "Dropshipping" in o, "bob : rappel automatique d'une page d'alice", o)
o = hook(B, "session-start", {"session_id": "b2", "cwd": str(TMP / B / "work")})
check("🤝 Cerveau commun" in o and "alice" in o, "bob : démarrage avec le cerveau commun", o[-800:])
code, out = brain(B, "show", "Les robots faussent les stats Shopify")
check("Ma version" in out and "🤝" not in out.splitlines()[0], "bob : un titre partagé avec alice → sa propre page d'abord", out)
code, out = brain(B, "edit", "c--alice--dropshipping", "-a", "Ajout de Bob")
check(code != 0 and "lecture seule" in out and "Traceback" not in out, "bob : page d'alice en lecture seule", out)
code, out = brain(B, "rm", "c--alice--dropshipping")
check(code != 0 and "lecture seule" in out, "bob : impossible d'archiver une page d'alice", out)
code, out = brain(B, "add", "-t", "concept", "-T", "Dropshipping", "-b", "Vendre sans stock. Version de Bob.", "-p", "none")
gb = graph(B)
check("dropshipping" in gb.get("nodes", {}) and "Version de Bob" in gb["nodes"]["dropshipping"]["body"],
      "bob : même titre qu'alice → sa propre page (pas de fusion chez alice)", out)
check(not any(k.startswith("c--") for k in gb.get("nodes", {})), "bob : son cache ne garde aucune page d'alice")
check(not list((TMP / B / "wiki" / "wiki").rglob("*Marché*")) and "marché aux fleurs" not in
      (TMP / B / "wiki" / "index.md").read_text(encoding="utf-8").lower(), "bob : son wiki perso ne contient pas les pages d'alice")
code, out = brain(B, "add", "-t", "learning", "-T", "Le marché ouvre à quatre heures", "-b", "Selon Bob.", "-p", "none",
                  "--replaces", "c--alice--le-marche-aux-fleurs-ouvre-a-cinq-heures")
check(code == 0 and "remplacement ignoré" in out and "le-marche-ouvre-a-quatre-heures" in graph(B).get("nodes", {})
      and "Le marché aux fleurs ouvre à cinq heures" in subprocess.run(
          ["git", "-C", str(BARE), "show", "HEAD:membres/alice/wiki/Faits/Le marché aux fleurs ouvre à cinq heures.md"],
          capture_output=True).stdout.decode("utf-8"), "bob : « remplace » une page d'alice → ignoré, sa page est créée", out)
code, out = brain(B, "consolidate")
check(code == 0 and subprocess.run(["git", "-C", str(BARE), "show", "HEAD:membres/alice/wiki/Concepts/Dropshipping.md"],
                                   capture_output=True).stdout.decode("utf-8").count("Version de Bob") == 0,
      "bob : la consolidation ne touche pas aux pages d'alice", out)
files = bare_files()
check("membres/bob/wiki/Concepts/Dropshipping.md" in files and "membres/bob/wiki/Apprentissages/Les robots faussent les stats Shopify.md"
      in files, "bob partage aussi (son dossier à lui)", "\n".join(files))
check("Bob, cuisinier" not in bare_history() and "Nantes" not in bare_history(), "vie privée de bob : profil jamais envoyé")
code, out = brain(A, "commun", "sync")
code, out = brain(A, "q", "dropshipping version de bob")
check("🤝 bob" in out, "alice voit les pages de bob", out)

# ------------------------------------------------------------------ 3b. sources : le web part, les documents perso non
code, out = brain(B, "wiki", "add", "-", "-T", "Guide public des pâtes", "--url", "https://example.org/guide-pates",
                  inp="Cuire al dente, saler l'eau.")
check(code == 0, "bob : source web ajoutée", out)
code, out = brain(B, "wiki", "add", "-", "-T", "Contrat de location", "--url", "https://drive.google.com/file/d/XyZ123/view",
                  inp="Loyer neuf cents euros.")
notes = TMP / B / "notes-perso.md"
notes.write_text("# Carnet\nMes recettes de famille.\n", encoding="utf-8")
code, out = brain(B, "wiki", "add", str(notes), "-T", "Carnet de Bob")
code, out = brain(B, "add", "-t", "concept", "-T", "Plan de repas", "-b", "Tiré du carnet.", "-p", "none",
                  "--sources", "[[Carnet de Bob]]")
code, out = brain(B, "add", "-t", "concept", "-T", "Cuisson al dente", "-b", "Croquant au centre.", "-p", "none",
                  "--sources", "[[Guide public des pâtes]], [[Carnet de Bob]]")
files = bare_files()
check("membres/bob/wiki/Sources/Guide public des pâtes.md" in files, "source web : partagée", "\n".join(files))
check(not any("Contrat de location" in f or "Carnet de Bob" in f or "Plan de repas" in f for f in files),
      "document perso, lien Drive, page tirée seulement d'eux : privés", "\n".join(files))
cuis = shown("membres/bob/wiki/Concepts/Cuisson al dente.md")
check("Guide public des pâtes" in cuis and "Carnet" not in cuis, "sources d'une page : seules les publiques sont citées", cuis)

# ------------------------------------------------------------------ 4. temps réel (vraies tâches de fond)
t0 = time.time()
code, out = brain(A, "add", "-t", "learning", "-T", "Arroser les pivoines le matin", "-b", "Moins d'évaporation.", "-p", "none", fg=False)
target = "membres/alice/wiki/Apprentissages/Arroser les pivoines le matin.md"
while time.time() - t0 < 60 and target not in bare_files():
    time.sleep(0.5)
sent = time.time() - t0
check(target in bare_files(), f"temps réel : l'ajout d'alice part tout seul ({sent:.1f} s)")
cstate = TMP / B / "brain" / "state" / "commun.json"
st = json.loads(cstate.read_text(encoding="utf-8"))
st["pull_asked"] = None
cstate.write_text(json.dumps(st), encoding="utf-8")
t1 = time.time()
hook(B, "prompt", {"session_id": "b3", "cwd": str(TMP / B / "work"), "prompt": "bonjour, on continue ?"}, fg=False)
clone_b = TMP / B / "brain" / "commun" / target
while time.time() - t1 < 60 and not clone_b.exists():
    time.sleep(0.5)
got = time.time() - t1
code, out = brain(B, "q", "arroser pivoines matin évaporation")
check(clone_b.exists() and "Arroser les pivoines le matin" in out, f"temps réel : bob la reçoit au message suivant ({got:.1f} s)", out)
check(sent + got < 120, f"temps réel : moins de 2 minutes de bout en bout ({sent + got:.1f} s)")



def bob_state(**kw):
    st = json.loads(cstate.read_text(encoding="utf-8"))
    st.update(kw)
    cstate.write_text(json.dumps(st), encoding="utf-8")


def alice_sends(title, body):
    brain(A, "add", "-t", "learning", "-T", title, "-b", body, "-p", "none", fg=False)
    f = f"membres/alice/wiki/Apprentissages/{title}.md"
    t = time.time()
    while time.time() - t < 60 and f not in bare_files():
        time.sleep(0.3)
    return f


# bob revient après une pause : son message attend la récupération (brève) et voit déjà la nouveauté d'alice
f = alice_sends("Tailler les hortensias en mars", "Juste au-dessus des bourgeons.")
bob_state(pull_asked=None, pulled="2020-01-01T00:00:00")
t3 = time.time()
o = hook(B, "prompt", {"session_id": "b4", "cwd": str(TMP / B / "work"), "prompt": "quand faut-il tailler les hortensias ?"}, fg=False)
check("🤝 alice" in o and "Tailler les hortensias en mars" in o,
      f"temps réel : après une pause, le message voit déjà la nouveauté ({time.time() - t3:.1f} s)", o)
# fin de tour : récupération en arrière-plan pendant que l'utilisateur lit (sortie du hook : JSON valide ou rien)
f = alice_sends("Pailler les fraisiers", "Garde l'humidité.")
bob_state(pull_asked=None)
tp = TMP / B / "transcript.jsonl"
tp.write_text("", encoding="utf-8")
o = hook(B, "stop", {"session_id": "b4", "transcript_path": str(tp), "cwd": str(TMP / B / "work")}, fg=False)
t4 = time.time()
while time.time() - t4 < 60 and not (TMP / B / "brain" / "commun" / f).exists():
    time.sleep(0.3)
check((TMP / B / "brain" / "commun" / f).exists() and (not o.strip() or json.loads(o)),
      f"temps réel : récupéré en fin de tour ({time.time() - t4:.1f} s)", o)
bob_state(pull_asked=None)
o = hook(B, "stop", {"session_id": "b4", "transcript_path": str(tp), "cwd": str(TMP / B / "work")})
check(not o.strip() or isinstance(json.loads(o), dict), "fin de tour : sortie du hook intacte (synchro au premier plan)", o)

# envoi différé : un « garde ça pour moi » juste après l'ajout, et le premier jet ne part jamais
slow = {"BRAIN_COMMUN_DELAY": "8"}
code, out = brain(A, "add", "-t", "learning", "-T", "Astuce du fournisseur", "-b", "Prix cassés le lundi.", "-p", "none",
                  fg=False, xenv=slow)
code, out = brain(A, "edit", "astuce-du-fournisseur", "--commun", "non", fg=False, xenv=slow)
code, out = brain(A, "add", "-t", "learning", "-T", "Rempoter en avril", "-b", "Avant la reprise.", "-p", "none",
                  fg=False, xenv=slow)
t5 = time.time()
f = "membres/alice/wiki/Apprentissages/Rempoter en avril.md"
while time.time() - t5 < 60 and f not in bare_files():
    time.sleep(0.3)
check(f in bare_files() and "Astuce du fournisseur" not in bare_history() and "Prix cassés" not in bare_history(),
      "envoi différé : gardé privé juste après l'ajout → jamais parti ; l'ajout suivant part avec le lot", "\n".join(bare_files()))

# ------------------------------------------------------------------ 5. retirer, devenir sensible, projet redevenu privé
code, out = brain(A, "edit", "les-robots-faussent-les-stats-shopify", "--commun", "non")
check("membres/alice/wiki/Apprentissages/Les robots faussent les stats Shopify.md" not in bare_files(),
      "marqué privé après coup → retiré du dépôt commun", out)
code, out = brain(A, "edit", "dropshipping", "-a", "Mon salaire en dépend en partie.")
check("membres/alice/wiki/Concepts/Dropshipping.md" not in bare_files() and "Mon salaire" not in bare_history(),
      "devenu sensible → retiré, et le texte sensible n'est jamais parti", out)
code, out = brain(A, "commun", "projet", "site-commun", "--non")
code, out = brain(A, "commun", "sync")
check(not any(f.startswith("membres/alice/wiki/À faire/") or f.startswith("membres/alice/wiki/Projets/") for f in bare_files()),
      "projet redevenu privé → ses pages quittent le dépôt commun", "\n".join(bare_files()))
code, out = brain(B, "commun", "sync", "--no-push")
code, out = brain(B, "q", "refaire la page d'accueil nouvelles photos")
check("Refaire la page d'accueil" not in out and "Site commun" not in out, "bob ne voit plus ce qu'alice a rendu privé", out)

# ------------------------------------------------------------------ 6. envois simultanés (pas de conflit)
code, out = brain(A, "add", "-t", "learning", "-T", "Couper les tiges en biais", "-b", "Elles boivent mieux.", "-p", "none", fg=False)
code, out = brain(B, "add", "-t", "learning", "-T", "Saler l'eau des pâtes", "-b", "Dix grammes par litre.", "-p", "none", fg=False)
pa = subprocess.Popen([sys.executable, "-I", "-S", str(CODE / "brain.py"), "commun", "sync"], env=env(A), cwd=str(TMP / A / "work"),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
pb = subprocess.Popen([sys.executable, "-I", "-S", str(CODE / "brain.py"), "commun", "sync"], env=env(B), cwd=str(TMP / B / "work"),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
oa, ob = pa.communicate(timeout=180)[0].decode("utf-8", "replace"), pb.communicate(timeout=180)[0].decode("utf-8", "replace")
t2 = time.time()
want = {"membres/alice/wiki/Apprentissages/Couper les tiges en biais.md", "membres/bob/wiki/Apprentissages/Saler l'eau des pâtes.md"}
while time.time() - t2 < 60 and not want <= set(bare_files()):
    time.sleep(0.5)
check(want <= set(bare_files()), "envois simultanés : les deux arrivent, sans conflit", oa + ob)

# ------------------------------------------------------------------ 6b. un git interrompu (PC éteint) ne bloque rien
lock = TMP / A / "brain" / "commun" / ".git" / "index.lock"
lock.write_text("", encoding="utf-8")
os.utime(lock, (time.time() - 3600, time.time() - 3600))
code, out = brain(A, "add", "-t", "learning", "-T", "Changer l'eau des vases", "-b", "Tous les deux jours.", "-p", "none")
t2 = time.time()  # une synchro encore en cours (étape précédente) reprend ce changement en arrière-plan : on l'attend
while time.time() - t2 < 60 and "membres/alice/wiki/Apprentissages/Changer l'eau des vases.md" not in bare_files():
    time.sleep(0.5)
check("membres/alice/wiki/Apprentissages/Changer l'eau des vases.md" in bare_files() and not lock.exists(),
      "verrou git abandonné : retiré, la synchro passe", out)

# ------------------------------------------------------------------ 7. quitter
code, out = brain(B, "commun", "quitter")
check(code == 0 and not any(f.startswith("membres/bob/") for f in bare_files()), "bob quitte : ses pages sont retirées", out)
code, out = brain(B, "q", "couper les tiges en biais")
check("🤝" not in out, "bob ne reçoit plus les pages des amis", out)
code, out = brain(B, "show", "Bob, cuisinier")
check(code == 0 and "Bob, cuisinier" in out, "bob garde tout son cerveau", out)
code, out = brain(A, "commun", "sync")
code, out = brain(A, "q", "saler l'eau des pâtes")
check("🤝 bob" not in out, "alice ne voit plus les pages de bob", out)

# ------------------------------------------------------------------ 7b. identité git : le pseudo seulement, heures en UTC
real = {"GIT_AUTHOR_NAME": "Alice Martin", "GIT_AUTHOR_EMAIL": "alice.martin@example.com", "GIT_COMMITTER_NAME": "Alice Martin",
        "GIT_COMMITTER_EMAIL": "alice.martin@example.com", "TZ": "Europe/Paris"}
code, out = brain(A, "add", "-t", "learning", "-T", "Hydrater les bulbes", "-b", "Une nuit dans l'eau.", "-p", "none", xenv=real)
code, out = brain(A, "commun", "sync", xenv=real)
idents = subprocess.run(["git", "-C", str(BARE), "log", "--all", "--format=%an|%ae|%cn|%ce|%ad|%cd", "--date=iso"],
                        capture_output=True).stdout.decode("utf-8")
check("Hydrater les bulbes" in " ".join(bare_files()) and "Martin" not in idents and "example.com" not in idents
      and all(line.endswith("+0000") for line in idents.splitlines()), "commits : pseudo seulement, heures en UTC", idents[:600])
E = "eve"
code, out = brain(E, "add", "-t", "learning", "-T", "Greffer les pommiers au printemps", "-b", "En fente.", "-p", "none")
code, out = brain(E, "config", "commun.repo", str(BARE))
code, out = brain(E, "commun", "rejoindre", "--oui", "--nom", "alice")
check(code != 0 and "déjà pris" in out and "Traceback" not in out and "Greffer" not in bare_history(),
      "pseudo déjà pris par un ami : refusé, rien d'envoyé", out)

# ------------------------------------------------------------------ 8. la proposition à un ami (accord)
C = "chloe"
code, out = brain(C, "add", "-t", "learning", "-T", "Torréfier le café à 220 degrés", "-b", "Pour un café clair.", "-p", "none")
code, out = brain(C, "config", "commun.repo", str(BARE))
o = hook(C, "session-start", {"session_id": "c1", "cwd": str(TMP / C / "work")})
check("Le cerveau commun de tes amis" not in o, "chloé : pas de proposition avant d'avoir vérifié l'accès", o[-400:])
o = hook(C, "session-start", {"session_id": "c2", "cwd": str(TMP / C / "work")})
check("Le cerveau commun de tes amis" in o and "commun apercu" in o and "commun rejoindre --oui" in o,
      "chloé : proposition au démarrage (accès vérifié)", o[-600:])
o = hook(C, "session-start", {"session_id": "c3", "cwd": str(TMP / C / "work")})
check("Le cerveau commun de tes amis" not in o, "chloé : proposition une fois par jour seulement", o[-400:])
code, out = brain(C, "commun", "non")
st = TMP / C / "brain" / "state" / "commun.json"
d = json.loads(st.read_text(encoding="utf-8"))
d["offered"] = None
st.write_text(json.dumps(d), encoding="utf-8")
o = hook(C, "session-start", {"session_id": "c4", "cwd": str(TMP / C / "work")})
check("Le cerveau commun de tes amis" not in o and "Torréfier" not in bare_history(),
      "chloé refuse : plus de proposition, rien d'envoyé", o[-400:])
D = "dan"
code, out = brain(D, "config", "commun.repo", str(TMP / "inexistant.git"))
hook(D, "session-start", {"session_id": "d1", "cwd": str(TMP / D / "work")})
o = hook(D, "session-start", {"session_id": "d2", "cwd": str(TMP / D / "work")})
check("Le cerveau commun de tes amis" not in o and "accès pas encore vérifié" in o and "invitation" in o,
      "accès pas vérifié : simple mention, une fois", o[-600:])
o = hook(D, "session-start", {"session_id": "d3", "cwd": str(TMP / D / "work")})
check("cerveau commun" not in o.lower(), "accès pas vérifié : plus rien ensuite", o[-400:])
code, out = brain(D, "commun", "rejoindre", "--oui")
check(code != 0 and "invitation" in out and "Traceback" not in out, "rejoindre sans accès : message clair", out)

# ------------------------------------------------------------------ 9. bilan vie privée sur tout l'historique
hist = bare_history()
for word in PRIVATE + ["Vit à Nantes", "Torréfier", "Greffer", "Contrat de location", "XyZ123", "drive.google.com", "Carnet de Bob",
                       "recettes de famille", "Plan de repas", "Loyer"]:
    check(word not in hist, f"bilan : « {word} » absent de tout l'historique du dépôt commun")

print("\n".join(f"  {label}" for label in OK if label.startswith(("temps réel", "fin de tour"))))
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
(shutil.rmtree(TMP, ignore_errors=True) if not FAIL and not os.environ.get("KEEP") else print(f"(dossier gardé : {TMP})"))
sys.exit(1 if FAIL else 0)
