"""Le travail d'un ami est toujours enregistré, et il peut le vérifier : `doctor` signale la commande `python` introuvable
(les hooks du plugin la lancent) et les sessions de Claude Code absentes du journal, `journal --backfill` les importe, le
démarrage les rattrape tout seul (au plus une fois par jour), et « retiens que… » est enregistré par le hook lui-même
(sans doublon, jamais un secret).

Lancement : python tests/test_enregistrement.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-enreg-test-"))
CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_HOME", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(k, None)
POSIX = os.name != "nt"  # faux `python` = petits scripts sh


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


class World:
    """Un faux PC : ~/.claude (réglages, transcripts) et ~/.claude/brain (souvenirs, configuration)."""

    def __init__(self, name, code=CODE):
        self.root = TMP / name
        self.home, self.brain_dir, self.work = self.root / "claude", self.root / "brain", self.root / "work"
        for d in (self.home, self.brain_dir, self.work):
            d.mkdir(parents=True, exist_ok=True)
        self.code = Path(code)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "BRAIN_HOME": str(self.brain_dir)}

    def run(self, *args, inp=None, path=None):
        env = dict(self.env, PATH=str(path)) if path is not None else self.env
        r = subprocess.run([sys.executable, "-I", "-S", str(self.code / "brain.py"), *map(str, args)], capture_output=True,
                           timeout=180, input=(inp or "").encode("utf-8"), cwd=str(self.root), env=env)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    def hook(self, event, sid="s1", **payload):
        c, out = self.run("hook", event, inp=json.dumps({"session_id": sid, "cwd": str(self.work), **payload}))
        try:  # la sortie du hook est UN objet JSON (une tâche de fond peut écrire après)
            return c, json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
        except ValueError:
            return c, None

    def prompt(self, text, sid="s1"):
        c, msg = self.hook("prompt", sid=sid, prompt=text)
        return c, ((msg or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")

    def config(self, key=None):
        f = self.brain_dir / "config.json"
        cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        for part in (key or "").split("."):
            cfg = cfg.get(part) if part and isinstance(cfg, dict) else cfg
        return cfg

    def set_config(self, key, value):
        f = self.brain_dir / "config.json"
        cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        cur = cfg
        for part in key.split(".")[:-1]:
            cur = cur.setdefault(part, {})
        cur[key.split(".")[-1]] = value
        f.write_text(json.dumps(cfg), encoding="utf-8")

    def journal(self):
        f = self.brain_dir / "journal" / "sessions.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("sessions", {})
        except (OSError, ValueError):
            return {}

    def memories(self):
        f = self.brain_dir / "graph.json"
        nodes = json.loads(f.read_text(encoding="utf-8"))["nodes"].values() if f.exists() else []
        return [n for n in nodes if n["type"] != "project" and n.get("status", "active") == "active"]

    def transcript(self, sid, prompts=("Corrige le bug de connexion",), hours=2.0, sub="-projet-demo"):
        """Transcript d'une session de Claude Code, modifié il y a `hours` heures."""
        f = self.home / "projects" / sub / f"{sid}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - hours * 3600))
        lines = []
        for text in prompts:
            lines.append({"type": "user", "timestamp": stamp, "cwd": str(self.work),
                          "message": {"role": "user", "content": text}})
            lines.append({"type": "assistant", "timestamp": stamp, "message": {
                "role": "assistant", "content": [{"type": "text", "text": "C'est corrigé, voici ce qui a changé."}]}})
        f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
        t = time.time() - hours * 3600
        os.utime(f, (t, t))
        return f


def wait_for(cond, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.25)
    return cond()


def fake_python(folder, body):
    """Dossier du PATH qui ne contient qu'un faux `python` (script sh)."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "python"
    exe.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    exe.chmod(0o755)
    return folder


# ------------------------------------------------------------------ 1. doctor : la commande `python` des hooks
W = World("python")
VIDE = TMP / "path-vide"
VIDE.mkdir()
c, out = W.run("doctor", path=VIDE)
check(c == 0 and "✗ les hooks du plugin lancent `python`, introuvable ici → rien n'est enregistré automatiquement" in out,
      "doctor : `python` introuvable → ✗ rien n'est enregistré automatiquement", out[-900:])
check('ln -sf "$(command -v python3)" ~/.local/bin/python' in out and "mkdir -p ~/.local/bin" in out
      and "sudo apt install python-is-python3" in out and "Add python.exe to PATH" in out,
      "doctor : un remède d'une ligne par système (macOS, Debian/Ubuntu, Windows)", out[-900:])
if POSIX:
    c, out = W.run("doctor", path=fake_python(TMP / "py-ancien", 'echo "3.8.1"'))
    check("✗ les hooks du plugin lancent `python`" in out and "version 3.8.1 trop ancienne" in out
          and "rien n'est enregistré automatiquement" in out, "doctor : `python` trop ancien (3.8.1) → ✗", out[-900:])
    c, out = W.run("doctor", path=fake_python(TMP / "py-casse", "exit 9"))
    check("✗ les hooks du plugin lancent `python`" in out and "ne se lance pas" in out,
          "doctor : `python` qui ne se lance pas (alias du Store…) → ✗", out[-900:])
    c, out = W.run("doctor", path=fake_python(TMP / "py-ok", f'exec "{sys.executable}" "$@"'))
    check(c == 0 and "✓ commande `python` des hooks : " in out and "lancent `python`" not in out,
          "doctor : `python` en état de marche → ✓", out[-900:])

# plugin installé mais code classique aux commandes (avant la bascule) : les hooks du plugin lancent `python` aussi
CLASSIQUE = TMP / "code-classique"
CLASSIQUE.mkdir()
shutil.copy2(CODE / "brain.py", CLASSIQUE / "brain.py")
shutil.copytree(CODE / "brainkit", CLASSIQUE / "brainkit", ignore=shutil.ignore_patterns("__pycache__"))
WC = World("classique", code=CLASSIQUE)
c, out = WC.run("doctor", path=VIDE)
check(c == 0 and "lancent `python`" not in out, "doctor (cerveau classique, plugin absent) : pas de contrôle de `python`", out[-600:])
(WC.home / "plugins").mkdir()
(WC.home / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"cerveau@cerveau": [
    {"scope": "user", "installPath": str(TMP / "absent")}]}}), encoding="utf-8")
c, out = WC.run("doctor", path=VIDE)
check(c == 0 and "✗ les hooks du plugin lancent `python`, introuvable ici" in out,
      "doctor (cerveau classique, plugin installé) : `python` introuvable → ✗", out[-600:])

# ------------------------------------------------------------------ 2. doctor : sessions absentes du journal
W = World("journal")
W.transcript("recente-a", ("Corrige le bug de connexion", "Ajoute un test"), hours=2)
W.transcript("recente-b", ("Prépare la page d'accueil",), hours=30)
W.transcript("trop-vieille", hours=24 * 10)  # plus de 7 jours : hors contrôle
W.transcript("en-cours", hours=0)  # modifiée à l'instant : session encore active, le journal se remplit en fin de tour
sous = W.home / "projects" / "-projet-demo" / "recente-a" / "subagents"
sous.mkdir(parents=True)
(sous / "agent-1.jsonl").write_text(json.dumps({"type": "user", "isSidechain": True, "message": {
    "role": "user", "content": "tâche d'un sous-agent"}}) + "\n", encoding="utf-8")
(W.home / "projects" / "-projet-demo" / "agent-zz.jsonl").write_text(json.dumps({"type": "user", "isSidechain": True, "message": {
    "role": "user", "content": "ancien format de sous-agent"}}) + "\n", encoding="utf-8")
W.transcript("sans-demande", prompts=(), hours=3)  # aucune demande de l'utilisateur : l'import l'ignorerait
c, out = W.run("doctor")
check(c == 0 and "⚠ 2 session(s) de Claude Code absentes du journal → `brain journal --backfill` les importe" in out,
      "doctor : 2 sessions récentes absentes du journal (ni sous-agents, ni vieilles, ni session active)", out[-900:])
c, out = W.run("journal", "--backfill")
check(c == 0 and "session(s) importée(s) dans le journal" in out, "journal --backfill : sessions importées", out[-400:])
check({"recente-a", "recente-b"} <= set(W.journal()), "journal : les sessions manquantes y sont maintenant", list(W.journal()))
check("agent-1" not in W.journal() and "agent-zz" not in W.journal(), "journal : jamais de transcript de sous-agent")
c, out = W.run("doctor")
check(c == 0 and "absentes du journal" not in out and "✓ sessions des 7 derniers jours : 2 dans le journal, aucune manquante" in out,
      "doctor après import : plus d'alerte, sessions récentes confirmées", out[-900:])
W.set_config("journal.enabled", False)
W.transcript("recente-c", hours=2)
c, out = W.run("doctor")
check(c == 0 and "absentes du journal" not in out, "doctor : journal désactivé → pas de contrôle", out[-400:])

# ------------------------------------------------------------------ 3. démarrage : rattrapage quotidien du journal
W = World("rattrapage")
W.transcript("r1", ("Refais la page de contact",), hours=3)
W.transcript("r2", ("Vérifie les accents",), hours=5)
W.transcript("r-vieille", hours=24 * 12)
check(W.config("journal.rattrapage_le") in (None, ""), "rattrapage : aucun contrôle fait avant le premier démarrage")
c, msg = W.hook("session-start", sid="s1", source="startup")
stamp = W.config("journal.rattrapage_le")
check(c == 0 and stamp and stamp[:10] == time.strftime("%Y-%m-%d"), "démarrage : jour du contrôle noté dans la configuration", stamp)
check(wait_for(lambda: {"r1", "r2"} <= set(W.journal())), "démarrage : sessions manquantes importées en arrière-plan",
      list(W.journal()))
W.transcript("r3", ("Ajoute la FAQ",), hours=2)
c, msg = W.hook("session-start", sid="s2", source="startup")
time.sleep(4)  # le temps qu'une relance (qui n'aurait pas dû partir) ait fini
check(c == 0 and W.config("journal.rattrapage_le") == stamp and "r3" not in W.journal(),
      "2e démarrage le même jour : pas de nouveau rattrapage", list(W.journal()))
W.set_config("journal.rattrapage_le", "2020-01-01T00:00:00")  # il y a plus d'un jour
c, msg = W.hook("session-start", sid="s3", source="resume")
check(c == 0 and W.config("journal.rattrapage_le")[:4] != "2020" and wait_for(lambda: "r3" in W.journal()),
      "lendemain : le démarrage (même une reprise) rattrape la session manquante", list(W.journal()))
W.set_config("journal.rattrapage_le", "2020-01-01T00:00:00")
W.set_config("journal.enabled", False)
W.transcript("r4", ("Change la couleur du bouton",), hours=2)
c, msg = W.hook("session-start", sid="s4", source="startup")
time.sleep(3)
check(c == 0 and W.config("journal.rattrapage_le") == "2020-01-01T00:00:00" and "r4" not in W.journal(),
      "journal désactivé : aucun rattrapage", list(W.journal()))
# rien à rattraper : la session qui reprend (elle s'inscrit à la fin de son tour), une session sans demande de
# l'utilisateur (l'import l'ignorerait) et une session de plus de 7 jours → aucun import lancé (sinon l'ancienne y serait)
W = World("rattrapage-seul")
W.transcript("moi", ("Reprends le devis",), hours=2)
W.transcript("vide", prompts=(), hours=3)
W.transcript("ancienne", ("Un vieux sujet",), hours=24 * 10)
c, msg = W.hook("session-start", sid="moi", source="resume")
time.sleep(3)
check(c == 0 and W.config("journal.rattrapage_le") and not W.journal(),
      "rattrapage : ni la session qui démarre, ni une session vide, ni une vieille ne déclenchent d'import", list(W.journal()))

# ------------------------------------------------------------------ 4. « retiens que… » : enregistré par le hook lui-même
W = World("retiens")
(W.work / "package.json").write_text("{}", encoding="utf-8")
c, out = W.run("map", W.work, "--quiet")
projets = [n for n in json.loads((W.brain_dir / "graph.json").read_text(encoding="utf-8"))["nodes"].values()
           if n["type"] == "project"]
check(c == 0 and len(projets) == 1, "projet courant connu du cerveau", out[-300:])
PROJET = projets[0]["id"] if projets else None

c, ctx = W.prompt("retiens que je préfère les réponses courtes")
mem = W.memories()
check(c == 0 and len(mem) == 1 and mem[0]["type"] == "feedback" and mem[0]["title"] == "Je préfère les réponses courtes",
      "« retiens que je préfère… » : une règle (feedback) créée par le hook", mem)
check(mem and mem[0]["source"] == "auto" and "noté le" in mem[0]["body"] and "préfère les réponses courtes" in mem[0]["body"]
      and mem[0]["project"] is None, "souvenir : source automatique, phrase entière + date, règle globale", mem)
ID = mem[0]["id"] if mem else "?"
check(f"Déjà enregistré tel quel (`{ID}`)" in ctx and "edit" in ctx and "seulement si c'est utile" in ctx
      and "enregistre-le avec" not in ctx, "Claude reçoit « Déjà enregistré tel quel » au lieu d'avoir à faire `add`", ctx)
check("Souvenirs pertinents" not in ctx, "le souvenir tout juste créé n'est pas aussi « rappelé »", ctx)
c, ctx = W.prompt("retiens que je préfère les réponses courtes")
check(c == 0 and len(W.memories()) == 1 and "Déjà enregistré" in ctx and ID in ctx,
      "même demande redite : aucun doublon, toujours « Déjà enregistré »", W.memories())
c, ctx = W.prompt("Retiens que je préfère les réponses courtes.")
check(len(W.memories()) == 1, "même demande, casse et point final différents : aucun doublon", W.memories())

c, ctx = W.prompt("n'oublie pas que le client veut des factures en PDF")
fait = [n for n in W.memories() if n["type"] == "fact"]
check(len(W.memories()) == 2 and len(fait) == 1 and fait[0]["title"] == "Le client veut des factures en PDF"
      and fait[0]["project"] == PROJET and "Déjà enregistré" in ctx,
      "« n'oublie pas que… » : un fait, rangé dans le projet courant", W.memories())

avant = len(W.memories())
c, ctx = W.prompt("retiens mon mot de passe: hunter2")
tout = "".join(p.read_text(encoding="utf-8", errors="replace") for p in W.brain_dir.rglob("*")
               if p.is_file() and p.suffix in (".json", ".md", ".html", ".log", ""))
check(c == 0 and len(W.memories()) == avant and "Déjà enregistré" not in ctx and "Secret probable" in ctx
      and "non enregistré" in ctx, "mot de passe : rien d'enregistré, Claude est prévenu", ctx)
check("hunter2" not in tout, "mot de passe : nulle part dans le cerveau")
c, ctx = W.prompt("retiens que la clé est " + "sk-" + "ant-" + "a1b2c3d4e5" * 4)  # fausse clé, jamais écrite en clair ici
check(len(W.memories()) == avant and "Secret probable" in ctx, "clé d'API : rien d'enregistré", ctx)

for texte, pourquoi in (("n'oublie pas de lancer les tests avant de valider", "simple rappel pour la tâche en cours"),
                        ("ne retiens pas ça, c'est un test", "demande de ne PAS retenir"),
                        ("retiens ça", "renvoie à autre chose : Claude seul sait quoi"),
                        ("mémorise les résultats du calcul dans un dictionnaire", "du code (memoize), pas une demande"),
                        ("est-ce que tu retiens bien ce que je dis ?", "une question")):
    c, ctx = W.prompt(texte)
    check(c == 0 and len(W.memories()) == avant, f"pas enregistré par le hook : {pourquoi}", W.memories())
c, ctx = W.prompt("retiens ça")
check("L'utilisateur demande de mémoriser" in ctx and "add" in ctx,
      "quand le hook ne peut pas, Claude reçoit la consigne d'avant (faire `add`)", ctx)
c, ctx = W.prompt("/brain retiens que ceci ne compte pas pour le hook")
check(len(W.memories()) == avant, "commande /… : rien d'enregistré")

c, ctx = W.prompt("Retiens que le site est en français. N'oublie pas que le panier minimum est de 25 euros.")
check(len(W.memories()) == avant + 2 and "Déjà enregistrés tels quels" in ctx, "deux demandes dans un message : deux souvenirs", W.memories())
avant = len(W.memories())
W.set_config("recall.enabled", False)
c, ctx = W.prompt("retiens que les devis sont valables 30 jours")
check(len(W.memories()) == avant + 1 and "Déjà enregistré" in ctx, "rappel automatique coupé : la demande est quand même enregistrée", ctx)
W.set_config("recall.enabled", True)
avant = len(W.memories())
c, out = W.run("recall", "retiens que cette phrase ne doit pas être enregistrée pour de vrai")
check(c == 0 and "simulation" in out and len(W.memories()) == avant, "`brain recall` : simule sans rien enregistrer", out)
c, out = W.run("doctor")
check(c == 0 and "aucun secret stocké" in out, "doctor : aucun secret stocké après tout ça", out[-600:])

# fin de tâche : le rappel ne redemande pas ce que le hook a déjà enregistré, mais garde les autres candidats
lignes = [{"type": "user", "message": {"role": "user", "content": "retiens que je préfère les réponses courtes"}},
          {"type": "user", "message": {"role": "user", "content": "toujours utiliser pnpm dans ce projet"}}]
for i in range(16):
    lignes.append({"type": "assistant", "message": {"id": f"m{i}", "role": "assistant", "content": [
        {"type": "text", "text": "ok"}, {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls"}}]}})
tr = W.home / "projects" / "-projet-demo" / "s1.jsonl"
tr.parent.mkdir(parents=True, exist_ok=True)
tr.write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")
c, msg = W.hook("stop", sid="s1", transcript_path=str(tr))
raison = (msg or {}).get("reason", "")
check(c == 0 and "Candidats repérés" in raison and "pnpm" in raison and "réponses courtes" not in raison,
      "fin de tâche : candidats = ce que le hook n'a pas déjà enregistré", raison[-400:])

# ------------------------------------------------------------------ 5. le README le dit
from brainkit import publish  # noqa: E402

page = publish.readme("Auteur", "proprietaire/depot")
bloc = page.split("## Prérequis", 1)[-1].split("\n## ", 1)[0].strip().splitlines()
check(len(bloc) <= 6 and "Python 3.10" in page and "la commande `python`" in page and "python-is-python3" in page
      and 'ln -sf "$(command -v python3)" ~/.local/bin/python' in page and "Add python.exe to PATH" in page
      and "doctor" in page and "brain.py journal" in page, "README : prérequis (Python 3.10+, `python`, vérification), court", bloc)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
