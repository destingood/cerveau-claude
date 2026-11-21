"""Ne plus perdre de souvenir (étape 7 du plan, partie graphe, sauvegarde et mise à jour) :
1. un graph.json abîmé (coupé au milieu, octets nuls, ajout au bout, mauvaise forme, vide) se répare sans perdre les
   souvenirs écrits après le dernier instantané : version d'avant la dernière écriture, écritures récentes, et ce qui
   se lit encore du fichier abîmé ; une suppression définitive ne revient pas ; le fichier abîmé est gardé ;
2. l'utilisateur l'apprend une fois, au démarrage suivant, avec les nombres ;
3. sans second disque (macOS, Linux, Windows à un disque), la sauvegarde du jour va dans ~/Sauvegardes-cerveau-Claude,
   dite une fois (décision E7) ;
4. `self-update` revient en arrière sur toute erreur (pas seulement du disque), même une interruption, et ne touche à
   rien si la sauvegarde du code échoue.

Lancement : python tests/test_pertes.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-pertes-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
HOME = TMP / "home"  # dossier personnel du test : ~/Sauvegardes-cerveau-Claude y tombe, jamais dans le vrai
SEED = HOME / ".claude" / "brain"
os.environ.update(HOME=str(HOME), USERPROFILE=str(HOME), CLAUDE_CONFIG_DIR=str(HOME / ".claude"),
                  BRAIN_HOME=str(SEED), BRAIN_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
WORK = TMP / "travail"
WORK.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))
QUIET = {"auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
         "journal": {"enabled": False}, "commun": {"propose": False}}
SEED.mkdir(parents=True)
(SEED / "config.json").write_text(json.dumps(QUIET), encoding="utf-8")

from brainkit import backup, history, selfupdate  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402
from brainkit.store import Brain  # noqa: E402


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


def brain(*args, home=SEED, stdin=None):
    env = dict(os.environ, BRAIN_HOME=str(home))
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       cwd=str(WORK), env=env, timeout=300, input=stdin.encode("utf-8") if stdin else None)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def wait_views(home):
    brain("vues", "--attendre", home=home)


def graph_of(home):
    try:
        return json.loads((home / "graph.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ 1. un cerveau, un instantané, puis des écritures
with Brain.edit() as b:
    for i in range(40):
        b.add("fact", f"Souvenir numéro {i} du test des pertes", f"Corps du souvenir {i} : " + "détail " * 30)
OLD = sorted(Brain.load().nodes)
EARLY, LATE, GONE = OLD[3], OLD[-3], OLD[10]  # un souvenir du début du fichier, un de la fin, un à supprimer
history.snapshot("dernier-instantane", force=True)  # le dernier instantané : tout ce qui suit est « plus récent »
time.sleep(1.1)  # les écritures suivantes ont une date d'après l'instantané
with Brain.edit() as b:
    b.update(EARLY, body="Corps modifié après l'instantané (début du fichier).")
with Brain.edit() as b:
    b.update(LATE, body="Corps modifié après l'instantané (fin du fichier).")
with Brain.edit() as b:
    b.remove(GONE, purge=True)
NEW = []
for title, text in (("Transporteur des colis : Colissimo", "Choisi pour les colis de moins de 2 kg."),
                    ("Thème de la boutique : Dawn", "Gratuit, rapide, gardé tel quel jusqu'en mars."),
                    ("Horaires du service client", "Réponses du lundi au vendredi, de 9 h à 17 h.")):
    code, out = brain("add", "-t", "decision", "-T", title, "-b", text)
    check(code == 0, f"brain add « {title} »", out)
NEW = sorted(set(Brain.load().nodes) - set(OLD))
check(len(NEW) == 3, "trois souvenirs ajoutés après le dernier instantané", NEW)
wait_views(SEED)
GOOD = (SEED / "graph.json").read_bytes()
WANT = set(OLD) - {GONE} | set(NEW)
check(len(history.snapshots()) >= 1 and all(n not in history.load(history.snapshots()[0])["nodes"] for n in NEW),
      "le dernier instantané ne contient pas les souvenirs ajoutés après lui")


def case(name, damage, drop=()):
    """Copie du cerveau, graph.json abîmé par `damage(octets)`, fichiers de `drop` retirés, puis une commande qui lit le
    cerveau. → (dossier, code, sortie, graphe relu)."""
    home = TMP / "cas" / name
    shutil.copytree(SEED, home, ignore=shutil.ignore_patterns("*.tmp", "*.lock", ".graph.lock"))
    for rel in drop:
        (home / rel).unlink(missing_ok=True)
    bad = damage(GOOD)
    (home / "graph.json").write_bytes(bad)
    code, out = brain("todo", home=home)
    return home, bad, code, out, graph_of(home)


def body(g, nid):
    return (((g or {}).get("nodes") or {}).get(nid) or {}).get("body", "")


def expect(name, damage, drop=(), whole=False):
    home, bad, code, out, g = case(name, damage, drop)
    ids = set((g or {}).get("nodes") or {})
    check(code == 0 and g is not None, f"{name} : le cerveau se lit après réparation", out)
    check(WANT <= ids, f"{name} : aucun souvenir perdu, les 3 écrits après le dernier instantané compris",
          sorted(WANT - ids))
    check(GONE not in ids, f"{name} : le souvenir supprimé pour de bon ne revient pas")
    check("modifié après l'instantané (début" in body(g, EARLY) and "modifié après l'instantané (fin" in body(g, LATE),
          f"{name} : les modifications faites après l'instantané sont gardées", (body(g, EARLY), body(g, LATE)))
    kept = sorted(home.glob("graph.corrupt-*.json"))
    check(kept and kept[-1].read_bytes() == bad, f"{name} : le fichier abîmé est gardé à côté, tel quel",
          [p.name for p in kept])
    note = home / "state" / "a-dire" / "reparation.txt"
    text = note.read_text(encoding="utf-8") if note.exists() else ""
    check(f"{len(WANT)} souvenir" in text and "gardé" in text, f"{name} : le compte rendu de la réparation attend le "
          "démarrage suivant, avec les nombres", text)
    edges = (g or {}).get("edges") or []
    check(all(e["from"] in ids and e["to"] in ids for e in edges), f"{name} : aucun lien vers un souvenir absent")
    return home, text


half = len(GOOD) // 2
home_cut, text_cut = expect("coupé au milieu", lambda raw: raw[:half])
expect("octets nuls au milieu", lambda raw: raw[:half] + b"\x00" * 4096 + raw[half + 4096:])
expect("ajout au bout", lambda raw: raw + b"\n\x00\x00{{ octets en trop")
# Octets qui ne sont plus de l'UTF-8 dans un souvenir : sa version intacte (copie d'avant) l'emporte sur la version abîmée
home_bad, _ = expect("octets invalides dans un souvenir", lambda raw: raw.replace(
    "Corps modifié après l'instantané (début du fichier)".encode("utf-8"),
    "Corps modifié après l'instantané (début du fichier)".encode("utf-8") + b"\xff\xfe", 1))
check("�" not in body(graph_of(home_bad), EARLY), "octets invalides : la version abîmée ne remplace pas la bonne",
      body(graph_of(home_bad), EARLY))
expect("mauvaise forme (liste de souvenirs)", lambda raw: json.dumps(
    {"nodes": list(json.loads(raw)["nodes"].values()), "edges": json.loads(raw)["edges"]}).encode("utf-8"))
expect("fichier vide", lambda raw: b"")
# Sans la version d'avant la dernière écriture : la base est le dernier instantané, le journal des écritures récentes
# rejoue tout ce qui a suivi (ajouts, modifications, suppression définitive).
expect("coupé, sans version précédente", lambda raw: raw[:half], drop=("history/precedent.json",))
check("journal des écritures récentes" in text_cut or "fichier abîmé" in text_cut,
      "compte rendu : dit d'où viennent les souvenirs", text_cut)

# Après `brain restore` (revenir à l'instantané), une réparation ne rejoue pas les écritures qu'on vient d'annuler.
home = TMP / "cas" / "après une restauration"
shutil.copytree(SEED, home, ignore=shutil.ignore_patterns("*.tmp", "*.lock", ".graph.lock"))
code, out = brain("restore", "dernier-instantane", home=home)
restored = set((graph_of(home) or {}).get("nodes") or {})
check(code == 0 and GONE in restored and not set(NEW) & restored, "brain restore : l'état de l'instantané revient", out)
(home / "graph.json").write_bytes((home / "graph.json").read_bytes()[:half])
code, out = brain("todo", home=home)
ids = set((graph_of(home) or {}).get("nodes") or {})
check(code == 0 and ids == restored, "après une restauration : la réparation ne rejoue pas les écritures annulées",
      (sorted(ids ^ restored), out[-300:]))

# Sans aucune copie (ni version précédente, ni écritures récentes, ni instantané) : ce qui se lit du fichier abîmé
# suffit à ne pas repartir d'un cerveau vide.
home, bad, code, out, g = case("coupé, sans aucune copie", lambda raw: raw[:half],
                               drop=("history/precedent.json", "history/recents.jsonl"))
for snap in (home / "history").glob("graph-*.json.gz"):
    snap.unlink()
(home / "graph.json").write_bytes(bad)
code, out = brain("todo", home=home)
g = graph_of(home)
n = len((g or {}).get("nodes") or {})
check(code == 0 and 10 < n < len(WANT), "sans aucune copie : les souvenirs lisibles du fichier abîmé, pas un cerveau vide",
      (code, n, out[-300:]))

# Le compte rendu, une fois, au démarrage suivant
start = json.dumps({"session_id": "pertes-1", "cwd": str(WORK), "source": "startup"})
code, out = brain("hook", "session-start", home=home_cut, stdin=start)
try:
    shown = json.loads(out.strip().splitlines()[-1]).get("systemMessage", "") if out.strip() else ""
except ValueError:
    shown = ""
check("graph.json était abîmé" in shown and f"{len(WANT)} souvenir" in shown,
      "démarrage suivant : l'utilisateur apprend la réparation (message à lui seul, aucun token)", out[-500:])
code, out = brain("hook", "session-start", home=home_cut,
                  stdin=start.replace("pertes-1", "pertes-2"))
check("graph.json était abîmé" not in out, "le compte rendu n'est dit qu'une fois", out[-300:])

# ------------------------------------------------------------------ 2. ce que garde chaque écriture
for i in range(5):
    with Brain.edit() as b:
        b.add("fact", f"Mesure {i}", "Corps.")
prev = SEED / "history" / "precedent.json"
recents = SEED / "history" / "recents.jsonl"
verify("chaque écriture garde la version d'avant (history/precedent.json)", lambda: prev.exists() and json.loads(
    prev.read_text(encoding="utf-8"))["nodes"].keys() < Brain.load().nodes.keys())
verify("les écritures récentes restent bornées en taille",
       lambda: (recents.exists() and recents.stat().st_size < history.RECENT_MAX, recents.exists()))

# ------------------------------------------------------------------ 3. sauvegarde sans second disque (décision E7)
want_dir = HOME / backup.FOLDER
real_second = getattr(backup, "second_disk", None)
no_disk = (lambda: None) if real_second else None


def default_without_disk():
    backup.second_disk = no_disk  # machine sans second disque, sous Windows aussi
    try:
        return backup.default_dir() == want_dir, backup.default_dir()
    finally:
        backup.second_disk = real_second


def beside_brain():
    saved_dir = backup.BRAIN_DIR
    backup.BRAIN_DIR = TMP / "ailleurs" / "brain"
    try:
        return backup.home_dir() == TMP / "ailleurs" / backup.FOLDER, backup.home_dir()
    finally:
        backup.BRAIN_DIR = saved_dir


verify("sans second disque : ~/Sauvegardes-cerveau-Claude", default_without_disk)
if os.name != "nt":
    verify("macOS et Linux : pas de recherche de disque D:, E:…", lambda: real_second() is None)
verify("cerveau rangé hors du dossier personnel : ses sauvegardes à côté de lui", beside_brain)
from brainkit import hooks  # noqa: E402
from brainkit.common import load_config  # noqa: E402

cfg = load_config()
cfg["backup"]["enabled"] = True
due = hooks.daily_due(cfg)
check(["backup", "--auto"] in due, "la sauvegarde du jour est due, quel que soit le système", due)

if os.name != "nt" or (real_second and real_second() is None):  # la vraie commande, sans second disque (un poste
    # Windows avec D: y écrirait : la commande n'y est pas lancée, le choix du dossier est vérifié plus haut)
    home = HOME / "cas" / "sauvegarde"  # dans le dossier personnel, comme ~/.claude/brain
    shutil.copytree(SEED, home, ignore=shutil.ignore_patterns("*.tmp", "*.lock", ".graph.lock"))
    code, out = brain("backup", "--auto", home=home)
    zips = sorted(want_dir.glob("cerveau-*.zip"))
    check(code == 0 and len(zips) == 1, "sauvegarde automatique faite dans ~/Sauvegardes-cerveau-Claude", (code, out))
    note = home / "state" / "a-dire" / "sauvegarde.txt"
    text = note.read_text(encoding="utf-8") if note.exists() else ""
    check(str(want_dir) in text and "réinstallation" in text and "backup.dir" in text and "--to" in text,
          "le dossier choisi est annoncé : où, le risque d'une réinstallation, comment en changer", text)
    code, out = brain("hook", "session-start", home=home, stdin=start.replace("pertes-1", "sauvegarde-1"))
    check(str(want_dir) in out and "réinstallation" in out, "annonce montrée au démarrage suivant", out[-400:])
    note.unlink(missing_ok=True)
    code, out = brain("backup", home=home)
    check(code == 0 and "Sauvegardes-cerveau-Claude" in out and "réinstallation" not in out and not note.exists(),
          "l'annonce n'est faite qu'une fois", out)
    home2 = HOME / "cas" / "sauvegarde-reglee"
    shutil.copytree(SEED, home2, ignore=shutil.ignore_patterns("*.tmp", "*.lock", ".graph.lock"))
    brain("config", "backup.dir", str(TMP / "mes-sauvegardes"), home=home2)
    code, out = brain("backup", home=home2)
    check(code == 0 and list((TMP / "mes-sauvegardes").glob("cerveau-*.zip")) and "réinstallation" not in out,
          "dossier réglé (backup.dir) : utilisé, sans annonce", out)

# ------------------------------------------------------------------ 4. self-update : retour arrière sur toute erreur
selfupdate.PLUGIN = False


def tree(root, version, extra=None):
    files = {"brain.py": "print('cerveau')\n", "brainkit/__init__.py": f'__version__ = "{version}"\n',
             "brainkit/a.py": f"A = '{version}'\n", "brainkit/b.py": f"B = '{version}'\n",
             "tests/test_x.py": f"X = '{version}'\n", **(extra or {})}
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def snapshot_of(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def deploy_case(name, **kw):
    base = TMP / "maj" / name
    src = tree(base / "src", "9.1.0", {"brainkit/nouveau.py": "N = 1\n"})
    dst = tree(base / "dst", "9.0.0")
    selfupdate.target_dir = lambda: dst
    before = snapshot_of(dst)
    logs = []
    try:
        code = selfupdate.deploy(src, log=logs.append, **kw)
        raised = None
    except BaseException as exc:  # noqa: BLE001 — l'interruption doit ressortir, et rien d'autre
        code, raised = None, exc
    return before, snapshot_of(dst), code, raised, "\n".join(logs)


def boom(_target):
    raise RuntimeError("vérification qui plante")


before, after, code, raised, out = deploy_case("vérification qui plante", verifier=boom)
check(raised is None and code == 1 and after == before,
      "self-update : une vérification qui plante (pas une erreur du disque) défait tout", (code, raised, out))
check("restauration" in out and "revenu au code 9.0.0" in out, "self-update : le retour arrière est dit", out)


def interrupt(_target):
    raise KeyboardInterrupt


before, after, code, raised, out = deploy_case("interruption", verifier=interrupt)
check(isinstance(raised, KeyboardInterrupt) and after == before,
      "self-update : Ctrl+C pendant la vérification — tout défait, puis l'interruption ressort", (code, raised, out))

real_copy = shutil.copy2
failed = []


def copy_then_fail(src, dst, *a, **k):
    if not failed and "dst" in Path(dst).parts and Path(dst).name == "b.py":  # 3e copie vers la cible : à moitié faite
        failed.append(dst)
        raise ValueError("copie interrompue (erreur simulée qui n'est pas du disque)")
    return real_copy(src, dst, *a, **k)


selfupdate.shutil.copy2 = copy_then_fail
before, after, code, raised, out = deploy_case("copie interrompue", verify=False)
selfupdate.shutil.copy2 = real_copy
check(raised is None and code == 1 and after == before,
      "self-update : une copie interrompue au milieu (erreur quelconque) est défaite, fichier ajouté compris",
      (code, raised, sorted(set(after) ^ set(before)), out))

real_backup = selfupdate._make_backup


def backup_fails(target, dest):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "brain.py").write_text("moitié", encoding="utf-8")
    raise OSError(28, "No space left on device")


selfupdate._make_backup = backup_fails
before, after, code, raised, out = deploy_case("sauvegarde impossible")
selfupdate._make_backup = real_backup
check(raised is None and code == 1 and after == before and "rien n'a été modifié" in out,
      "self-update : sauvegarde du code impossible — rien n'est touché, et c'est dit", (code, raised, out))

real_restore = selfupdate._restore


def restore_fails(*_a):
    raise OSError(13, "Permission denied")


selfupdate._restore = restore_fails
before, after, code, raised, out = deploy_case("retour arrière impossible", verifier=boom)
selfupdate._restore = real_restore
check(raised is None and code == 1 and "retour arrière a échoué" in out and "brain-code-v9.0.0" in out
      and "copie son contenu" in out,
      "self-update : retour arrière impossible — où est la sauvegarde et comment finir à la main", (code, raised, out))

real_remember = selfupdate._remember


def remember_fails(*_a):
    raise OSError(30, "Read-only file system")


selfupdate._remember = remember_fails
before, after, code, raised, out = deploy_case("config non écrite", verify=False)
selfupdate._remember = real_remember
check(raised is None and code == 1 and after == before, "self-update : échec en notant la source — tout défait",
      (code, raised, out))
before, after, code, raised, out = deploy_case("mise à jour normale", verify=False)
check(code == 0 and after.get("brainkit/__init__.py") == b'__version__ = "9.1.0"\n' and "brainkit/nouveau.py" in after,
      "self-update : sans erreur, la mise à jour est faite (non-régression)", out)

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
