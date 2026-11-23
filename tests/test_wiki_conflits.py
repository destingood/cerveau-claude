"""Wiki sur deux PC par git, et coffre Obsidian : aucune modification perdue (étape 7 du plan).

Un dépôt « GitHub » (dépôt nu dans un dossier temporaire, sans réseau) et deux PC, chacun avec son cerveau isolé et son
clone du wiki : ils écrivent et se synchronisent tour à tour, sans jamais rester bloqués. Puis un verrou git oublié,
un envoi qui échoue (jamais affiché ✓), un coffre Obsidian modifié des deux côtés, et (étape 8) le journal du wiki,
un dossier par PC : les mois des deux PC restent sur GitHub, ceux d'avant la 8.31.0 sont gardés.

Lancement : python tests/test_wiki_conflits.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-conflits-")).resolve()
CODE = Path(__file__).resolve().parent.parent
IDENT = "pc" + "@" + "example.com"  # en morceaux : le contrôle des adresses de `brain publish` lit ce fichier
GITENV = {"GIT_AUTHOR_NAME": "PC", "GIT_AUTHOR_EMAIL": IDENT, "GIT_COMMITTER_NAME": "PC", "GIT_COMMITTER_EMAIL": IDENT,
          "GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
          "GIT_CONFIG_KEY_1": "init.defaultBranch", "GIT_CONFIG_VALUE_1": "main",
          "GIT_CONFIG_KEY_2": "core.autocrlf", "GIT_CONFIG_VALUE_2": "false"}
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-1500:]}" if detail else ""))


def env(who):
    e = {k: v for k, v in os.environ.items()
         if k not in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_PLUS", "BRAIN_IMPL")
         and not k.startswith("GIT_")}
    home = TMP / who / "home"
    home.mkdir(parents=True, exist_ok=True)
    e.update(GITENV, CLAUDE_CONFIG_DIR=str(TMP / who / "claude"), BRAIN_HOME=str(TMP / who / "brain"), HOME=str(home),
             USERPROFILE=str(home), COMPUTERNAME=who.upper(), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return e


def brain(who, *args):
    (TMP / who / "work").mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       cwd=str(TMP / who / "work"), env=env(who), timeout=240, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def hook(who, event, payload):
    (TMP / who / "work").mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", event],
                       input=json.dumps(payload).encode("utf-8"), capture_output=True, cwd=str(TMP / who / "work"),
                       env=env(who), timeout=240)
    return r.stdout.decode("utf-8", "replace")


def nodes(who) -> dict:
    """Souvenirs actifs du PC : {titre: corps}."""
    code = ("import json, sys\nsys.path.insert(0, %r)\nfrom brainkit.store import Brain\nb = Brain.load()\n"
            "print(json.dumps([[n['title'], n.get('body') or ''] for n in b.nodes.values() "
            "if n.get('status', 'active') == 'active'], ensure_ascii=False))" % str(CODE))
    r = subprocess.run([sys.executable, "-I", "-S", "-X", "utf8", "-c", code], capture_output=True,
                       cwd=str(TMP / who / "work"), env=env(who), timeout=120)
    try:
        rows = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(r.stderr.decode("utf-8", "replace")[-800:])
        return {}
    out = {}
    for title, body in rows:
        out.setdefault(title, []).append(body)
    return out


def git(*args, cwd=None):
    r = subprocess.run(["git", *map(str, args)], cwd=str(cwd) if cwd else None, capture_output=True,
                       env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **GITENV})
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def on_github(rel) -> str:
    code, out = git("show", f"main:{rel}", cwd=BARE)
    return out if code == 0 else ""


def github_files() -> str:
    return git("-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "main", cwd=BARE)[1]


def tracked(rel) -> bool:
    return git("cat-file", "-e", f"main:{rel}", cwd=BARE)[0] == 0


def page_of(root, title):
    hits = [p for p in (root / "wiki").rglob("*.md") if p.stem == title]
    return hits[0] if hits else None


def synced_ok(code, out):
    return code == 0 and "✗" not in out and "conflit, la même page" not in out


# ------------------------------------------------------------------ 1. le wiki sur le PC 1, envoyé sur « GitHub »
BARE = TMP / "github.git"
git("init", "-q", "--bare", "-b", "main", BARE)
W1, W2 = TMP / "pc1" / "wiki", TMP / "pc2" / "wiki"
W1.mkdir(parents=True)
git("init", "-q", "-b", "main", cwd=W1)
for k, v in (("user.name", "PC 1"), ("user.email", IDENT), ("core.autocrlf", "false")):
    git("config", k, v, cwd=W1)
git("remote", "add", "origin", BARE, cwd=W1)
brain("pc1", "add", "-t", "fact", "-T", "Fournisseur principal", "-b", "Rungis, ouvre à 5 h.", "-p", "none")
brain("pc1", "add", "-t", "fact", "-T", "Tarif livraison", "-b", "Colissimo 7 euros.", "-p", "none")
code, out = brain("pc1", "wiki", "init", W1)
check(code == 0 and "✓ push" in out, "PC 1 : wiki créé et envoyé sur GitHub", out)
# un wiki d'avant (8.29.0) suivait index.md dans git : on le remet dans cet état pour vérifier la migration
gi = (W1 / ".gitignore").read_text(encoding="utf-8")
(W1 / ".gitignore").write_text("\n".join(x for x in gi.splitlines() if x.strip() != "/index.md") + "\n", encoding="utf-8")
ga = (W1 / ".gitattributes").read_text(encoding="utf-8")
(W1 / ".gitattributes").write_text("\n".join(x for x in ga.splitlines() if "merge=union" not in x) + "\n",
                                   encoding="utf-8")
OLD_MONTH = ("# 🗓️ Journal — octobre 2026\n\n_Généré par le cerveau._\n\n## mercredi 14 octobre\n\n"
             "- 💬 09:15 « Ancienne session d'octobre sur les étiquettes » — projet vitrine\n")
(W1 / "journal").mkdir(exist_ok=True)
(W1 / "journal" / "2026-10.md").write_text(OLD_MONTH, encoding="utf-8")  # journal d'avant la 8.31.0 : un seul dossier
git("add", "-f", "index.md", ".gitignore", ".gitattributes", "journal/2026-10.md", cwd=W1)
git("commit", "-qm", "wiki d'avant : index.md suivi, journal/AAAA-MM.md", cwd=W1)
git("push", "-q", "origin", "HEAD", cwd=W1)
check(tracked("index.md"), "départ : index.md suivi dans git (comme un wiki créé avant la 8.30.0)")

# ------------------------------------------------------------------ 2. le PC 2 clone le wiki et y migre son cerveau
git("clone", "-q", BARE, W2)
for k, v in (("user.name", "PC 2"), ("user.email", IDENT), ("core.autocrlf", "false")):
    git("config", k, v, cwd=W2)
brain("pc2", "add", "-t", "fact", "-T", "Seulement PC 2", "-b", "Écrit sur le PC 2 avant de rejoindre le wiki.",
      "-p", "none")
code, out = brain("pc2", "wiki", "init", W2)
check(code == 0, "PC 2 : wiki rejoint (son cerveau y est migré)", out)
for who in ("pc1", "pc2"):
    brain(who, "config", "wiki.auto_sync", "false")  # pas de synchro en arrière-plan pendant le test

# ------------------------------------------------------------------ 3. chacun écrit, synchros à tour de rôle
brain("pc1", "add", "-t", "fact", "-T", "Seulement PC 1", "-b", "Écrit sur le PC 1.", "-p", "none")
brain("pc1", "wiki", "log", "note", "Note du PC 1", "le PC 1 écrit au journal")
brain("pc2", "wiki", "log", "note", "Note du PC 2", "le PC 2 écrit au journal")
code1, out1 = brain("pc1", "wiki", "sync")
check(synced_ok(code1, out1) and "✓ push" in out1, "PC 1 : synchro (après la migration du PC 2)", out1)
check(not tracked("index.md") and "/index.md" in on_github(".gitignore"),
      "index.md n'est plus suivi dans git (chaque PC régénère le sien) ; le fichier reste dans le dossier",
      on_github(".gitignore"))
check((W1 / "index.md").is_file(), "index.md toujours là sur le PC 1 (pas effacé du dossier)")
check(re.search(r"^log\.md\s+merge=union", on_github(".gitattributes"), re.M),
      "log.md fusionné des deux côtés (merge=union dans .gitattributes)", on_github(".gitattributes"))
brain("pc2", "add", "-t", "fact", "-T", "Encore PC 2", "-b", "Ajouté après la migration.", "-p", "none")
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2) and "✓ push" in out2,
      "PC 2 : synchro sans blocage (avant : conflit sur index.md, puis plus aucune synchro)", out2)
code1, out1 = brain("pc1", "wiki", "sync")
check(synced_ok(code1, out1), "PC 1 : synchro suivante", out1)
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2), "PC 2 : synchro suivante", out2)
n1, n2 = nodes("pc1"), nodes("pc2")
want = ("Fournisseur principal", "Tarif livraison", "Seulement PC 1", "Seulement PC 2", "Encore PC 2")
check(all(t in n1 for t in want) and all(t in n2 for t in want),
      "les deux PC ont les souvenirs de l'un et de l'autre", (sorted(n1), sorted(n2)))
for who, root in (("pc1", W1), ("pc2", W2)):
    log_md = (root / "log.md").read_text(encoding="utf-8")
    check("Note du PC 1" in log_md and "Note du PC 2" in log_md,
          f"{who} : log.md garde les entrées des deux PC", log_md[-600:])
    check("<<<<<<<" not in log_md and ">>>>>>>" not in log_md, f"{who} : log.md sans marques de conflit", log_md[-400:])
    check(git("status", "--porcelain", "-uno", cwd=root)[1].strip() == ""
          and not (root / ".git" / "rebase-merge").exists(), f"{who} : dépôt propre, aucun rebase laissé en plan",
          git("status", cwd=root)[1])

# ------------------------------------------------------------------ 4. la même page modifiée sur les deux PC
brain("pc1", "edit", "fournisseur-principal", "-b", "Rungis, ouvre à 4 h (PC 1).")
brain("pc2", "edit", "fournisseur-principal", "-b", "Rungis, ouvre à 6 h (PC 2).")
code1, out1 = brain("pc1", "wiki", "sync")
check(synced_ok(code1, out1), "PC 1 : envoie sa version de la page", out1)
code2, out2 = brain("pc2", "wiki", "sync")
check(code2 == 0 and "copie" in out2 and "✓ push" in out2 and "rebase annulé" not in out2,
      "PC 2 : conflit réglé seul (version de GitHub en place, la sienne en copie) et envoyé", out2)
copies = sorted(p for p in (W2 / "wiki").rglob("*.md") if "(conflit" in p.name)
check(len(copies) == 1 and "PC2" in copies[0].name and re.search(r"\d{4}-\d{2}-\d{2}", copies[0].name)
      and "6 h (PC 2)" in copies[0].read_text(encoding="utf-8"),
      "copie de conflit à côté de la page : nom avec le PC et la date, version du PC 2 dedans",
      [p.name for p in copies])
page = page_of(W2, "Fournisseur principal")
check(page is not None and "4 h (PC 1)" in page.read_text(encoding="utf-8")
      and copies and copies[0].parent == page.parent, "la page garde la version de GitHub (PC 1)",
      page.read_text(encoding="utf-8") if page else "")
n2 = nodes("pc2")
check(n2.get("Fournisseur principal") == ["Rungis, ouvre à 4 h (PC 1)."] and not any("conflit" in t for t in n2),
      "la copie n'est pas lue comme un souvenir (pas de doublon dans le cerveau)", n2.get("Fournisseur principal"))
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2), "PC 2 : la synchro suivante est verte", out2)
code1, out1 = brain("pc1", "wiki", "sync")
check(synced_ok(code1, out1) and any("(conflit" in p.name for p in (W1 / "wiki").rglob("*.md")),
      "PC 1 : reçoit la copie de conflit (rien de perdu, visible des deux PC)", out1)
o = hook("pc2", "session-start", {"session_id": "s1", "cwd": str(TMP / "pc2" / "work")})
check("Fournisseur principal (conflit PC2" in o, "démarrage suivant du PC 2 : la copie à relire est signalée",
      o[-800:])
o = hook("pc2", "session-start", {"session_id": "s2", "cwd": str(TMP / "pc2" / "work")})
check("(conflit" not in o, "… une seule fois", o[-800:])
code, out = brain("pc2", "wiki", "status")
check("conflit à régler à la main" not in out, "état du wiki : plus de conflit en attente", out)

# ------------------------------------------------------------------ 5. page supprimée d'un côté, modifiée de l'autre
p1 = page_of(W1, "Tarif livraison") or W1 / "wiki" / "Faits" / "Tarif livraison.md"
if p1.is_file():
    p1.unlink()  # supprimée à la main dans Obsidian sur le PC 1
code1, out1 = brain("pc1", "wiki", "sync")
brain("pc2", "edit", "tarif-livraison", "-b", "Colissimo 8 euros depuis novembre (PC 2).")
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2) and "8 euros" in on_github(f"wiki/{p1.parent.name}/{p1.name}"),
      "supprimée sur le PC 1, modifiée sur le PC 2 : la version modifiée est gardée et repart sur GitHub",
      out1 + out2)
brain("pc1", "edit", "seulement-pc-1", "-b", "Écrit sur le PC 1, puis complété (PC 1).")
q = page_of(W2, "Seulement PC 1") or W2 / "wiki" / "Faits" / "Seulement PC 1.md"
code1, out1 = brain("pc1", "wiki", "sync")
if q.is_file():
    q.unlink()
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2) and "complété (PC 1)" in on_github(f"wiki/{q.parent.name}/{q.name}")
      and q.is_file(), "modifiée sur le PC 1, supprimée sur le PC 2 : la version modifiée reste", out2)

# ------------------------------------------------------------------ 6. verrou git oublié, envoi raté : jamais « ✓ »
lock = W2 / ".git" / "index.lock"
lock.write_text("", encoding="utf-8")
os.utime(lock, (time.time() - 3600, time.time() - 3600))  # git tué il y a une heure (PC éteint)
brain("pc2", "add", "-t", "fact", "-T", "Après le verrou", "-b", "Écrit alors qu'un verrou git traînait.", "-p", "none")
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2) and "✓ commit" in out2 and not lock.exists()
      and "Après le verrou" in github_files(),
      "verrou git abandonné : retiré, la page part sur GitHub (avant : « ✗ commit » puis « ✓ push », pour toujours)",
      out2)
lock.write_text("", encoding="utf-8")  # verrou tout frais : un git travaille peut-être encore, on n'y touche pas
brain("pc2", "add", "-t", "fact", "-T", "Pendant un git", "-b", "Écrit pendant qu'un autre git travaille.", "-p", "none")
code2, out2 = brain("pc2", "wiki", "sync")
check(code2 == 1 and "✓ commit" not in out2 and "✓ push" not in out2 and "✓ pull" not in out2 and lock.exists()
      and "rien n'est perdu" in out2,
      "verrou récent : ni commit, ni pull, ni envoi affichés ✓, code de sortie 1", out2)
code, out = brain("pc2", "wiki", "status")
check("⚠" in out and "synchro" in out.lower() and "ratée" in out, "état du wiki : la synchro ratée est dite", out)
brain("pc2", "config", "wiki.auto_sync", "true")  # la veille (`brain auto`), sans session ouverte
for f in (TMP / "pc2" / "brain" / "state" / "sessions").glob("*.json"):
    os.utime(f, (time.time() - 7200, time.time() - 7200))
code, out = brain("pc2", "auto")
brain("pc2", "config", "wiki.auto_sync", "false")
check("✗ synchro du wiki" in out and "✓ synchro du wiki" not in out,
      "veille : la synchro ratée est affichée ✗ (avant : « ✓ synchro du wiki »)", out)
lock.unlink()
git("remote", "set-url", "origin", TMP / "absent.git", cwd=W2)
brain("pc2", "add", "-t", "fact", "-T", "Sans GitHub", "-b", "Écrit quand le dépôt est injoignable.", "-p", "none")
code2, out2 = brain("pc2", "wiki", "sync")
check(code2 == 1 and "✓ push" not in out2 and "✗" in out2, "dépôt injoignable : code 1, jamais « ✓ push »", out2)
git("remote", "set-url", "origin", BARE, cwd=W2)
code2, out2 = brain("pc2", "wiki", "sync")
check(synced_ok(code2, out2) and "✓ push" in out2 and "Sans GitHub" in github_files(),
      "dépôt revenu : tout part à la synchro suivante", out2)
code, out = brain("pc2", "wiki", "status")
check("ratée" not in out, "état du wiki : plus d'échec signalé après une synchro réussie", out)

# ------------------------------------------------------------------ 7. coffre Obsidian (cerveau classique) : rien de perdu
V = TMP / "coffre"
for t, b in (("Note Bateau", "corps bateau"), ("Note Girafe", "corps girafe"), ("Note Violon", "corps violon"),
             ("Note Pomme", "corps pomme"), ("Note Lune", "corps lune")):
    brain("pc3", "add", "-t", "learning", "-T", t, "-b", b, "-p", "none")
code, out = brain("pc3", "export", "--vault", V)
check(code == 0, "coffre exporté", out)
files = {p.stem: p for p in V.rglob("Note *.md")}


def edit_note(name, old, new):
    p = files[name]
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


brain("pc3", "edit", "note-bateau", "-b", "corps bateau, modifié dans le cerveau")
time.sleep(1.2)
edit_note("Note Bateau", "corps bateau", "corps bateau, modifié dans Obsidian")  # Obsidian après le cerveau
edit_note("Note Girafe", "corps girafe", "corps girafe, modifié dans Obsidian")
time.sleep(1.2)
brain("pc3", "edit", "note-girafe", "-b", "corps girafe, modifié dans le cerveau")  # le cerveau après Obsidian
edit_note("Note Violon", "corps violon", "corps violon, modifié sur l'autre PC")
brain("pc3", "edit", "note-violon", "-b", "corps violon, modifié dans le cerveau")
os.utime(files["Note Violon"], (time.time() + 3600, time.time() + 3600))  # horloge de l'autre PC en avance d'une heure
edit_note("Note Pomme", "corps pomme", "corps pomme, modifié dans Obsidian seulement")
brain("pc3", "edit", "note-lune", "-b", "corps lune, modifié dans le cerveau seulement")
code, out = brain("pc3", "export", "--vault", V)
n3 = nodes("pc3")
kept = "\n".join(p.read_text(encoding="utf-8") for p in (V / "Conflits").glob("*.md")) if (V / "Conflits").is_dir() else ""
vault_text = "\n".join(p.read_text(encoding="utf-8") for p in V.rglob("Note *.md"))
everywhere = "\n".join(b for bodies in n3.values() for b in bodies) + "\n" + kept + "\n" + vault_text
for t in ("corps bateau, modifié dans le cerveau", "corps bateau, modifié dans Obsidian",
          "corps girafe, modifié dans le cerveau", "corps girafe, modifié dans Obsidian",
          "corps violon, modifié dans le cerveau", "corps violon, modifié sur l'autre PC"):
    check(t in everywhere, f"coffre : « {t} » n'est pas perdu", (n3, kept))
check("corps bateau, modifié dans le cerveau" in kept and "Bateau" in out and "conflit" in out,
      "coffre : Obsidian plus récent → sa version en place, celle du cerveau gardée dans Conflits/ et signalée",
      out + "\n" + kept)
check("corps violon, modifié dans le cerveau" in kept or "corps violon, modifié sur l'autre PC" in kept,
      "coffre : horloge de l'autre PC en avance → l'autre version gardée quand même dans Conflits/", out + "\n" + kept)
check(n3.get("Note Pomme") == ["corps pomme, modifié dans Obsidian seulement"]
      and n3.get("Note Lune") == ["corps lune, modifié dans le cerveau seulement"]
      and "pomme" not in kept and "lune" not in kept,
      "coffre : un seul côté modifié → comme avant, sans copie de conflit", (n3.get("Note Pomme"), n3.get("Note Lune")))

# ------------------------------------------------------------------ 8. journal du wiki : un dossier par PC (étape 8)
def add_session(who, sid, end, title, last=""):
    f = TMP / who / "brain" / "journal" / "sessions.json"
    j = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"sessions": {}}
    j.setdefault("sessions", {})[sid] = {"id": sid, "start": end, "end": end, "title": title, "first": title,
                                         "last": last or f"{title}, la suite"}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")


def session_end(who, sid, extra=None):
    e = env(who)
    e.update(extra or {})
    subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "hook", "session-end"],
                   input=json.dumps({"session_id": sid, "cwd": str(TMP / who / "work")}).encode("utf-8"),
                   capture_output=True, cwd=str(TMP / who / "work"), env=e, timeout=240)
    # page Cerveau, index.md et carte : refaits par la tâche de fond des vues ; on l'attend
    subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "vues", "--attendre"], capture_output=True,
                   cwd=str(TMP / who / "work"), env=e, timeout=240)


add_session("pc1", "j-pc1-a", "2026-11-03T09:10:00", "Comparer les transporteurs du PC 1")
add_session("pc2", "j-pc2-a", "2026-11-03T16:40:00", "Préparer la newsletter du PC 2")
session_end("pc1", "fin-pc1-a")
code1, out1 = brain("pc1", "wiki", "sync")
session_end("pc2", "fin-pc2-a")
code2, out2 = brain("pc2", "wiki", "sync")
code1b, out1b = brain("pc1", "wiki", "sync")
check(synced_ok(code1, out1) and synced_ok(code2, out2) and synced_ok(code1b, out1b),
      "journal : les deux PC écrivent le même mois et se synchronisent sans conflit", out1 + out2 + out1b)
files = github_files()
check("journal/PC1/2026-11.md" in files and "journal/PC2/2026-11.md" in files and "journal/2026-11.md" not in files,
      "journal : un dossier par PC sur GitHub (journal/PC1/, journal/PC2/), plus de journal/AAAA-MM.md commun", files)
check("Comparer les transporteurs du PC 1" in on_github("journal/PC1/2026-11.md")
      and "Préparer la newsletter du PC 2" in on_github("journal/PC2/2026-11.md"),
      "journal : chaque PC a ses sessions du mois sur GitHub")
add_session("pc1", "j-pc1-b", "2026-11-05T11:00:00", "Relancer le fournisseur depuis le PC 1")
session_end("pc1", "fin-pc1-b")
code1, out1 = brain("pc1", "wiki", "sync")
add_session("pc2", "j-pc2-b", "2026-11-05T18:20:00", "Corriger les fiches produit sur le PC 2")
session_end("pc2", "fin-pc2-b")
code2, out2 = brain("pc2", "wiki", "sync")
code1, out1b = brain("pc1", "wiki", "sync")
m1, m2 = on_github("journal/PC1/2026-11.md"), on_github("journal/PC2/2026-11.md")
check(all(x in m1 for x in ("Comparer les transporteurs", "Relancer le fournisseur"))
      and all(x in m2 for x in ("Préparer la newsletter", "Corriger les fiches produit")),
      "journal : après d'autres synchros, aucun mois ne passe d'un PC à l'autre (avant : le dernier PC écrasait)",
      m1 + "\n----\n" + m2)
check(not any("(conflit" in p.name for p in (W1 / "journal").rglob("*.md"))
      and not any("(conflit" in p.name for p in (W2 / "journal").rglob("*.md")),
      "journal : aucune copie de conflit")
code, out = brain("pc1", "q", "newsletter")
check("Préparer la newsletter du PC 2" in out and "[PC2]" in out, "`brain q` sur le PC 1 trouve une session du PC 2", out)
code, out = brain("pc2", "q", "transporteurs")
check("Comparer les transporteurs du PC 1" in out and "[PC1]" in out,
      "`brain q` sur le PC 2 trouve une session du PC 1", out)
code, out = brain("pc2", "q", "newsletter")
check(out.count("« Préparer la newsletter du PC 2 »") == 1, "`brain q` : la session du PC lui-même n'est pas en double", out)
check("journal/ancien/2026-10.md" in files and "journal/2026-10.md" not in files
      and "Ancienne session d'octobre sur les étiquettes" in on_github("journal/ancien/2026-10.md"),
      "journal d'avant la 8.31.0 : rangé dans journal/ancien/, rien de perdu", files)
code, out = brain("pc1", "q", "étiquettes octobre")
check("Ancienne session d'octobre" in out and "avant la 8.31" in out,
      "`brain q` trouve aussi les sessions d'avant la 8.31.0", out)
# un PC pas encore à jour réécrit l'ancien journal/2026-10.md : remis dans journal/ancien/, les deux versions fusionnées
git("pull", "-q", "--rebase", cwd=W2)
(W2 / "journal" / "2026-10.md").write_text(OLD_MONTH.replace(
    "\n## mercredi 14 octobre", "\n## mardi 13 octobre\n\n- 💬 08:05 « Session d'un PC pas à jour »\n"
    "\n## mercredi 14 octobre"), encoding="utf-8")
git("add", "journal/2026-10.md", cwd=W2)
git("commit", "-qm", "ancienne version du cerveau : journal/2026-10.md réécrit", cwd=W2)
git("push", "-q", "origin", "HEAD", cwd=W2)
session_end("pc1", "fin-pc1-c")
code1, out1 = brain("pc1", "wiki", "sync")
old = on_github("journal/ancien/2026-10.md")
check(synced_ok(code1, out1) and "journal/2026-10.md" not in github_files() and "Session d'un PC pas à jour" in old
      and "Ancienne session d'octobre" in old and old.count("## mercredi 14 octobre") == 1,
      "un PC pas à jour réécrit l'ancien mois : rangé à nouveau, les deux versions fusionnées jour par jour", out1 + old)
status = (W1 / "Cerveau.md").read_text(encoding="utf-8") if (W1 / "Cerveau.md").is_file() else ""
check("[[journal/PC1/2026-11|PC1]]" in status and "[[journal/PC2/2026-11|PC2]]" in status
      and "Préparer la newsletter du PC 2" in status,
      "page Cerveau d'Obsidian : liens vers le journal de chaque PC, et les dernières sessions de tous les PC", status[-1200:])
schema = (W1 / "CLAUDE.md").read_text(encoding="utf-8")
check("journal/<PC>/AAAA-MM.md" in schema, "CLAUDE.md du wiki : le journal par PC est décrit")
# session cloud (conteneur jetable) : un seul dossier journal/cloud/, fusionné d'une session à l'autre
cloud = {"CERVEAU_CLOUD": "1"}
add_session("pc2", "j-cloud-a", "2026-11-07T10:00:00", "Session cloud numéro un")
session_end("pc2", "fin-cloud-a", cloud)
(TMP / "pc2" / "brain" / "journal" / "sessions.json").unlink()  # nouveau conteneur : journal local vide
add_session("pc2", "j-cloud-b", "2026-11-07T15:00:00", "Session cloud numéro deux")
session_end("pc2", "fin-cloud-b", cloud)
c = (W2 / "journal" / "cloud" / "2026-11.md").read_text(encoding="utf-8") if (W2 / "journal" / "cloud" / "2026-11.md").is_file() else ""
check("Session cloud numéro un" in c and "Session cloud numéro deux" in c and c.count("## samedi 7 novembre") == 1,
      "session cloud : journal/cloud/ garde les sessions des conteneurs successifs (fusionné, pas réécrit)", c)

print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
