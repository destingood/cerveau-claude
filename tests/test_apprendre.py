"""Apprentissage du cerveau (apprendre.py) sur de faux PC : erreurs résolues lues dans le transcript et jointes au rappel
de fin de tâche, déclencheurs manqués puis appris tout seuls, skills jamais suivies, méthodes répétées, dossier
d'apprentissage et sa ligne au démarrage, skill apprise, retours techniques sans rien de privé.

Lancement : python tests/test_apprendre.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-apprendre-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "CLAUDE_CODE_SUBAGENT_MODEL", "BRAIN_PLUS", "BRAIN_IMPL"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "unite" / "claude")  # import en direct : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "unite" / "brain")
sys.path.insert(0, str(CODE))


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-900:]}" if detail else ""))


class World:
    def __init__(self, name, **cfg):
        self.root = TMP / name
        self.home, self.brain_dir, self.work = self.root / "claude", self.root / "brain", self.root / "work"
        for d in (self.home, self.brain_dir, self.work):
            d.mkdir(parents=True, exist_ok=True)
        (self.brain_dir / "config.json").write_text(json.dumps({"pc": {"enabled": False}, "eco": {"auto": False}, **cfg}),
                                                    encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "BRAIN_HOME": str(self.brain_dir)}
        self.tp = self.root / "transcript.jsonl"
        self.n = 0

    def run(self, *args, inp=None):
        r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                           timeout=180, input=(inp or "").encode("utf-8"), cwd=str(self.work), env=self.env)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    def hook(self, event, sid="s1", **payload):
        data = {"session_id": sid, "cwd": str(self.work), "transcript_path": str(self.tp), **payload}
        c, out = self.run("hook", event, inp=json.dumps(data))
        try:
            return json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
        except ValueError:
            return {"illisible": out}

    def add(self, *lines):
        with open(self.tp, "a", encoding="utf-8") as fh:
            for x in lines:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")

    def say(self, text):
        self.add({"type": "user", "message": {"role": "user", "content": text}})

    def tool(self, name, inp, result="ok", error=False, sidechain=False):
        self.n += 1
        tid = f"toolu_{self.n:04d}"
        self.add({"type": "assistant", "isSidechain": sidechain,
                  "message": {"id": f"m{self.n}", "role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}},
                 {"type": "user", "isSidechain": sidechain,
                  "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": result}]}})

    def bash(self, cmd, result="ok", error=False, **kw):
        self.tool("Bash", {"command": cmd, "description": "x"}, ("Exit code 1\n" + result) if error else result, error, **kw)

    def state(self, name="apprendre.json"):
        p = self.brain_dir / "state" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def config(self):
        return json.loads((self.brain_dir / "config.json").read_text(encoding="utf-8"))


from brainkit import apprendre, plus  # noqa: E402

# ------------------------------------------------------------------ 1. lecture du transcript : erreurs résolues
W = World("erreurs")
W.say("lance le build et corrige ce qui casse")
W.bash("ls /dossier/absent", "ls: cannot access", error=True)           # exploration : jamais une erreur à apprendre
W.bash("ls /tmp")
W.bash("grep -c TODO src/app.py", "", error=True)                      # idem (grep sans résultat)
W.bash("npm run build", "Error: Cannot find module 'vite'\n    at Module._resolve", error=True)
W.bash("cat package.json")
W.bash("npm install && npm run build -- --mode production", "built in 3.2s")
W.bash("git push origin main", "The user doesn't want to proceed with this tool use.", error=True)  # refus : pas une panne
W.bash("git push origin main --force-with-lease", "ok")
W.bash("pytest tests/test_a.py", "1 failed", error=True)
W.bash("pytest tests/test_a.py", "1 passed")                            # même commande relancée : rien à apprendre
W.bash("python manage.py migrate", "django.db.utils.OperationalError: no such table", error=True, sidechain=True)
W.bash("python manage.py migrate --run-syncdb", "ok", sidechain=True)   # dans un sous-agent : pas la conversation
st = {}
found = apprendre.scan(W.tp, st)
check(len(found["erreurs"]) == 1 and found["erreurs"][0]["p"] == "npm run build"
      and found["erreurs"][0]["a"] == "npm run build" and "Cannot find module 'vite'" in found["erreurs"][0]["err"]
      and found["erreurs"][0]["b"].startswith("npm install && npm run build"),
      "lecture : un seul échec résolu (même programme relancé autrement) ; exploration, refus, relance identique et "
      "sous-agent écartés", found["erreurs"])
check(st["ap_off"] == W.tp.stat().st_size and apprendre.scan(W.tp, st) == {"erreurs": [], "skills": [], "lues": []},
      "lecture incrémentale : rien n'est relu deux fois")
W.bash("docker compose up -d", "error: port is already allocated", error=True)
for i in range(apprendre.WINDOW + 2):
    W.bash(f"echo étape {i}")
W.bash("docker compose up -d --force-recreate", "started")
check(apprendre.scan(W.tp, st)["erreurs"] == [], f"lecture : une réussite plus de {apprendre.WINDOW} appels après l'échec ne compte pas")
KEY = "sk-ant-" + "abcdefghijklmnopqrstuvwxyz123456"  # en deux morceaux : ce fichier est publié, jamais de clé entière
W.bash(f"curl -H 'Authorization: Bearer {KEY}' https://api.exemple.org/v1", "401", error=True)
W.bash(f"curl -H 'Authorization: Bearer {KEY}' https://api.exemple.org/v2", "200")
pair = apprendre.scan(W.tp, st)["erreurs"]
check(len(pair) == 1 and "sk-ant-" not in json.dumps(pair, ensure_ascii=False) and "masqué" in pair[0]["a"],
      "lecture : un secret dans une commande n'est jamais gardé", pair)

# ------------------------------------------------------------------ 2. jointes au rappel de fin de tâche
S = World("rappel")
S.say("installe les dépendances et lance les tests")
S.bash("pip install -r requirements.txt", "ERROR: Could not find a version that satisfies the requirement foo==9", error=True)
S.bash("pip install -r requirements.txt --pre", "Successfully installed foo-9.0rc1")
for i in range(16):
    S.tool("Read", {"file_path": f"/projet/src/f{i}.py"})
out = S.hook("stop", "r1")
reason = out.get("reason", "")
check(out.get("decision") == "block" and reason.startswith(plus.STOP_MARK) and "Erreur(s) résolue(s) repérée(s)" in reason
      and "`pip install -r requirements.txt` échouait" in reason and "--pre` a marché" in reason and "add -t learning" in reason,
      "fin de tâche : l'erreur résolue est jointe au rappel du cerveau (Claude juge si c'est un piège durable)", reason[-500:])
for i in range(160):
    S.tool("Read", {"file_path": f"/projet/src/g{i}.py"})
out = S.hook("stop", "r1")
check(out.get("decision") == "block" and "Erreur(s) résolue(s)" not in out.get("reason", ""),
      "rappel suivant : une erreur déjà montrée n'est pas redite", out.get("reason", "")[-300:])
S.hook("session-end", "r1")
check(not S.state().get("erreurs"), "fin de session : une erreur déjà montrée ne va pas au dossier", S.state())

Q = World("dossier", stop_reminder={"enabled": False})
Q.say("déploie le site")
Q.bash("vercel deploy --prod", "Error: No existing credentials found", error=True)
Q.bash("vercel deploy --prod --token-file .vercel-token", "Production: https://exemple.vercel.app")
check(Q.hook("stop", "q1") == {}, "sans rappel de fin de tâche : rien n'est dit à ce tour")
Q.hook("session-end", "q1")
errs = Q.state().get("erreurs") or []
check(len(errs) == 1 and errs[0]["p"] == "vercel deploy" and not errs[0].get("fait"),
      "fin de session : l'erreur résolue jamais montrée va au dossier d'apprentissage", errs)
Q.hook("session-end", "q1")
check(len(Q.state().get("erreurs") or []) == 1, "fin de session relancée : pas de doublon au dossier")
c, out = Q.run("apprendre")
check(c == 0 and "## Erreurs résolues" in out and "`vercel deploy --prod` échouait" in out and "No existing credentials" in out
      and "apprendre --fait" in out and "1 point(s)" in out, "brain apprendre : le dossier montre l'erreur et la commande à lancer", out)

# ------------------------------------------------------------------ 3. usage des skills : déclencheurs manqués puis appris
U = World("skills")
skill_dir = U.home / "skills" / "ma-compta"
skill_dir.mkdir(parents=True)
(skill_dir / "SKILL.md").write_text(
    "---\nname: ma-compta\ndescription: \"À utiliser pour la comptabilité de la micro-entreprise : « déclaration urssaf », "
    "« livre des recettes ». Ne pas utiliser pour les impôts personnels.\"\n---\n\n# ma-compta\n\n1. Ouvrir le tableur.\n",
    encoding="utf-8")
other = U.home / "skills" / "relance-clients"
other.mkdir(parents=True)
(other / "SKILL.md").write_text(
    "---\nname: relance-clients\ndescription: \"À utiliser pour relancer un client : « relance la facture impayée », "
    "« mail de relance ». Ne pas utiliser pour la prospection.\"\n---\n\n# relance-clients\n\n1. Retrouver la facture.\n",
    encoding="utf-8")
U.say("prépare le bilan trimestriel des encaissements de la boutique")
U.tool("Skill", {"skill": "ma-compta"})
U.say("/ma-compta fais le point")
U.tool("Skill", {"skill": "ma-compta"})                 # tapée en commande : rien à apprendre
U.say("utilise ma-compta pour ce mois")
U.tool("Skill", {"skill": "ma-compta"})                 # nommée par l'utilisateur : idem
U.say("déclaration urssaf du mois")
(U.brain_dir / "state" / "sessions").mkdir(parents=True, exist_ok=True)
(U.brain_dir / "state" / "sessions" / "u1.json").write_text(json.dumps({"skills_hinted": ["relance-clients"]}), encoding="utf-8")
U.tool("Skill", {"skill": "relance-clients"})           # soufflée par le réflexe : idem
U.hook("stop", "u1")
rows = U.state().get("declencheurs") or []
check(len(rows) == 1 and rows[0]["skill"] == "ma-compta" and "bilan trimestriel des encaissements" in rows[0]["msg"],
      "skill chargée sans avoir été soufflée : le message d'avant est gardé (pas une commande, un nom cité ni une skill soufflée)", rows)
c, out = U.run("apprendre", "--entretien")
check(c == 0 and "0 déclencheur(s) appris" in out and not (U.config().get("skills") or {}).get("triggers"),
      "un seul message : rien n'est appris tout seul (il va au dossier)", out)
c, out = U.run("apprendre")
check("## Déclencheurs manqués" in out and "`ma-compta` après « prépare le bilan trimestriel" in out and "skill trig ma-compta" in out,
      "brain apprendre : le déclencheur manqué est au dossier, avec la commande", out)
U2 = "u2"
U.tp = U.root / "transcript2.jsonl"
U.say("fais-moi le bilan trimestriel de l'activité s'il te plaît")
U.tool("Skill", {"skill": "ma-compta"})
U.hook("stop", U2)
c, out = U.run("apprendre", "--entretien")
trig = ((U.config().get("skills") or {}).get("triggers") or {}).get("ma-compta") or []
check(c == 0 and "1 déclencheur(s) appris" in out and trig == ["bilan trimestriel"],
      "deux messages qui partagent une tournure : le déclencheur est appris tout seul", (out, trig))
c, out = U.run("skill", "test", "il me faut le bilan trimestriel pour demain")
check("ma-compta" in out and "bilan trimestriel" in out, "le réflexe de skills reconnaît le déclencheur appris", out)
ctx = (U.hook("prompt", "u3", prompt="bonjour, on reprend le travail d'hier").get("hookSpecificOutput") or {}).get("additionalContext", "")
check("🎓 Déclencheur appris pour la skill `ma-compta` : « bilan trimestriel »" in ctx and "apprendre oublier ma-compta" in ctx,
      "le déclencheur appris est annoncé une fois, avec la commande pour le retirer", ctx)
ctx = (U.hook("prompt", "u3", prompt="et ensuite on fait quoi ?").get("hookSpecificOutput") or {}).get("additionalContext", "")
check("🎓" not in ctx, "l'annonce n'est faite qu'une fois", ctx)
c, out = U.run("apprendre", "etat")
check("1 déclencheur(s) appris" in out and "`ma-compta` : « bilan trimestriel »" in out, "brain apprendre etat : ce qui a été appris", out)
c, out = U.run("apprendre", "oublier", "ma-compta", "bilan trimestriel")
check(c == 0 and "retiré" in out and not ((U.config().get("skills") or {}).get("triggers") or {}).get("ma-compta"),
      "brain apprendre oublier : le déclencheur est retiré de la config", out)
U.tp = U.root / "transcript3.jsonl"
U.say("encore un bilan trimestriel à sortir")
U.tool("Skill", {"skill": "ma-compta"})
U.say("prépare le bilan trimestriel du magasin")
U.tool("Skill", {"skill": "ma-compta"})
U.hook("stop", "u4")
c, out = U.run("apprendre", "--entretien")
check("0 déclencheur(s) appris" in out and not ((U.config().get("skills") or {}).get("triggers") or {}).get("ma-compta"),
      "un déclencheur oublié n'est jamais réappris", out)
check(apprendre.common_phrase(["relance la facture du client Durand", "il faut relancer la facture de mars"]) == "relance facture"
      or "facture" in apprendre.common_phrase(["relance la facture du client Durand", "il faut relancer la facture de mars"]),
      "tournure commune : les mots porteurs partagés, dans l'ordre du message")
check(apprendre.common_phrase(["fais le site", "corrige la page"]) == "", "tournure commune : rien quand deux messages ne partagent pas deux mots")
A = World("ambigu")
for name, trig in (("ma-compta", "déclaration urssaf"), ("relance-clients", "relance la facture impayée")):
    d = A.home / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: \"À utiliser quand : « {trig} ». Ne pas utiliser pour le reste.\"\n"
                                f"---\n\n# {name}\n\n1. Étape.\n", encoding="utf-8")
A.say("relance la facture impayée du trimestre")
A.tool("Skill", {"skill": "ma-compta"})
A.say("pour la facture impayée, relance et note-le")
A.tool("Skill", {"skill": "ma-compta"})
(A.brain_dir / "state" / "sessions").mkdir(parents=True, exist_ok=True)
A.hook("stop", "a1")
c, out = A.run("apprendre", "--entretien")
check("0 déclencheur(s) appris" in out, "tournure qui désigne déjà une autre skill : pas de déclencheur ambigu", (out, A.state()))

# ------------------------------------------------------------------ 4. skills soufflées jamais suivies, méthodes répétées
M = World("methodes")
(M.brain_dir / "state").mkdir(parents=True, exist_ok=True)
(M.brain_dir / "state" / "skills.json").write_text(json.dumps({
    "cerveau:youtube": {"hinted": 7}, "cerveau:ecommerce": {"hinted": 9, "used": 3, "used_after_hint": 2},
    "ma-compta": {"hinted": 2}}), encoding="utf-8")


def day(n):
    return time.strftime("%Y-%m-%dT10:00:00", time.localtime(time.time() - n * 86400))


sessions = {}
for i, (text, tools, ago) in enumerate([
        ("publie la nouvelle version du plugin sur le dépôt", 22, 1), ("publie la nouvelle version du plugin et vérifie", 31, 3),
        ("publie la nouvelle version du plugin sur github", 18, 6), ("corrige le bug du panier", 40, 2),
        ("refais le logo de la boutique", 12, 4), ("publie la nouvelle version du plugin", 3, 5),
        ("fais le point de la semaine sur la boutique", 15, 2), ("fais le point de la semaine sur la boutique", 15, 2)]):
    sessions[f"s{i}"] = {"id": f"s{i}", "project": "cerveau-dev", "first": text, "last": text, "tools": tools, "prompts": 2,
                         "start": day(ago), "end": day(ago)}
(M.brain_dir / "journal").mkdir(parents=True, exist_ok=True)
(M.brain_dir / "journal" / "sessions.json").write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
c, out = M.run("apprendre")
check("## Skills soufflées sans jamais servir" in out and "`cerveau:youtube` soufflée 7 fois" in out and "cerveau:ecommerce" not in out
      and "`ma-compta` soufflée" not in out, "dossier : une skill soufflée 5 fois et plus sans jamais servir est signalée", out)
check("## Méthodes répétées" in out and "publie la nouvelle version du plugin" in out and "3 sessions" in out
      and "projet `cerveau-dev`" in out and "apprendre skill <nom>" in out,
      "dossier : la même demande dans 3 sessions de travail, sur plusieurs jours → skill candidate", out)
check("fais le point de la semaine" not in out and "corrige le bug du panier" not in out,
      "dossier : ni une demande vue un seul jour, ni une demande isolée")
pub = M.home / "skills" / "publier-plugin"
pub.mkdir(parents=True)
(pub / "SKILL.md").write_text("---\nname: publier-plugin\ndescription: \"À utiliser pour publier le plugin : « publie la nouvelle "
                              "version », « publie le plugin ». Ne pas utiliser pour un simple commit.\"\n---\n\n# publier\n\n1. Tests.\n",
                              encoding="utf-8")
c, out = M.run("apprendre")
check("## Méthodes répétées" not in out, "dossier : une demande déjà couverte par une skill n'est plus proposée", out)

# ------------------------------------------------------------------ 5. ligne 🎓 au démarrage, clôture
N = World("notice", stop_reminder={"enabled": False})
for cmd_a, cmd_b in (("npm run build", "npm run build -- --force"), ("cargo test", "cargo test -- --test-threads=1"),
                     ("terraform plan", "terraform plan -lock=false")):
    N.bash(cmd_a, "error: something failed", error=True)
    N.bash(cmd_b, "ok")
N.hook("session-end", "n1")
c, out = N.run("apprendre", "--entretien")
check(N.state().get("attente") == 3, "entretien du jour : le compte du dossier est gardé pour la ligne du démarrage", (out, N.state()))
ctx = (N.hook("session-start", "n2").get("hookSpecificOutput") or {}).get("additionalContext", "")
line = next((ln for ln in ctx.splitlines() if ln.startswith("🎓")), "")
check("3 point(s) à trancher" in line and "`cerveau:archiviste`" in line and "apprendre --fait" in line,
      "démarrage : la ligne 🎓 confie le dossier à l'agent archiviste (modèle moins cher)", ctx[-700:])
ctx = (N.hook("session-start", "n3").get("hookSpecificOutput") or {}).get("additionalContext", "")
check("🎓" not in ctx, "démarrage : au plus une fois par jour")
c, out = N.run("apprendre", "--fait")
c2, out2 = N.run("apprendre")
check(c == 0 and "✓ dossier d'apprentissage clos" in out and "0 point(s)" in out2 and "Rien à trancher" in out2,
      "brain apprendre --fait : le dossier est clos, ses points ne reviennent pas", out2)
N.run("config", "delegation.mode", "off")
d = N.state()
d.update(attente=4, notifie_le=None)
(N.brain_dir / "state" / "apprendre.json").write_text(json.dumps(d), encoding="utf-8")
ctx = (N.hook("session-start", "n4").get("hookSpecificOutput") or {}).get("additionalContext", "")
check("🎓" in ctx and "traite-le toi-même" in ctx and "archiviste" not in ctx.split("🎓")[-1],
      "délégation coupée : la ligne 🎓 demande à Claude de le traiter lui-même", ctx[-400:])
N.run("config", "apprendre.enabled", "false")
d.update(notifie_le=None)
(N.brain_dir / "state" / "apprendre.json").write_text(json.dumps(d), encoding="utf-8")
N.bash("make build", "error", error=True)
N.bash("make build -j1", "ok")
N.hook("session-end", "n5")
ctx = (N.hook("session-start", "n6").get("hookSpecificOutput") or {}).get("additionalContext", "")
check("🎓" not in ctx and not [e for e in N.state().get("erreurs") or [] if e.get("p") == "make build"],
      "apprendre.enabled false : plus de lecture, plus de ligne au démarrage")

# ------------------------------------------------------------------ 6. skill apprise
L = World("skill")
body = L.root / "corps.md"
body.write_text("# Publier le plugin\n\n1. Lancer les tests.\n2. Monter la version.\n3. `brain publish --push`.\n", encoding="utf-8")
c, out = L.run("apprendre", "skill", "publier-le-plugin", "-d",
               "À utiliser pour publier une version du plugin : « publie la nouvelle version », « sors une version ». Ne pas "
               "utiliser pour un simple commit.", "--body-file", body)
made = L.home / "skills" / "publier-le-plugin"
check(c == 0 and (made / "SKILL.md").is_file() and (made / apprendre.MARK).is_file() and "✓ skill apprise" in out
      and "fiche dans le cerveau" in out, "brain apprendre skill : skill créée, marquée « apprise », fiche en mémoire", out)
check("Monter la version" in (made / "SKILL.md").read_text(encoding="utf-8"), "skill apprise : son corps vient du fichier donné")
c, out = L.run("skill", "test", "publie la nouvelle version s'il te plaît")
check("publier-le-plugin" in out, "skill apprise : elle se déclenche sur ses propres mots", out)
c, out = L.run("apprendre", "skill", "publier-le-plugin", "-d", "x")
check(c != 0 and "existe déjà" in out, "skill apprise : jamais écrasée sans --force", out)
c, out = L.run("apprendre", "skill", "Nom Invalide", "-d", "À utiliser quand…")
check(c != 0 and "nom invalide" in out, "skill apprise : nom invalide refusé", out)
tool = L.root / "compte.py"
tool.write_text("import sys\nprint(len(open(sys.argv[1]).read().split()))\n", encoding="utf-8")
c, out = L.run("apprendre", "skill", "compter-les-mots", "-d",
               "À utiliser pour compter les mots d'un texte : « compte les mots », « nombre de mots ». Ne pas utiliser pour traduire.",
               "-b", "# Compter\n\n1. `python scripts/compte.py <fichier>`\n", "--script", tool)
check(c == 0 and (L.home / "skills" / "compter-les-mots" / "scripts" / "compte.py").read_text(encoding="utf-8") == tool.read_text(encoding="utf-8")
      and "✓ outil : scripts/compte.py" in out, "skill apprise avec un outil : le script est copié dans scripts/", out)
c, out = L.run("apprendre", "skill", "autre-outil", "-d", "À utiliser quand : « autre outil ». Ne pas utiliser sinon.", "--script", L.root / "absent.py")
check(c != 0 and "script introuvable" in out and not (L.home / "skills" / "autre-outil").exists(),
      "skill apprise : un script introuvable arrête tout avant de créer la skill", out)

# ------------------------------------------------------------------ 7. retours techniques : des compteurs, rien de privé
F = World("retours")
state_dir = F.brain_dir / "state"
state_dir.mkdir(parents=True, exist_ok=True)
now = time.strftime("%Y-%m-%dT%H:%M:%S")
old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 40 * 86400))
(state_dir / "brain.log").write_text("\n".join([
    f"{now} hook prompt ERREUR ValueError('mot de passe de Jean: hunter2 dans C:/Users/jean/secret.txt')",
    "Traceback (most recent call last):",
    '  File "C:/Users/jean/.claude/plugins/cache/cerveau/cerveau/8.21.0/brainkit/hooks.py", line 1320, in _run',
    "    handler(data, load_config())",
    '  File "C:/Users/jean/.claude/plugins/cache/cerveau/cerveau/8.21.0/brainkit/search.py", line 88, in search_memories',
    "ValueError: mot de passe de Jean: hunter2",
    f"{now} hook prompt ERREUR ValueError('autre chose')",
    "Traceback (most recent call last):",
    '  File "/home/x/brainkit/search.py", line 88, in search_memories',
    f"{now} hook session-start lent : 3.42s",
    f"{now} hook session-start lent : 2.10s",
    f"{now} plus (échange) : OSError(13, 'Permission denied: /home/jean/prive')",
    f"{old} hook stop ERREUR KeyError('vieux')",
    f"{now} commun : à jour"]) + "\n", encoding="utf-8")
(state_dir / "skills.json").write_text(json.dumps({"cerveau:youtube": {"hinted": 6}, "ma-skill-perso": {"hinted": 9}}), encoding="utf-8")
c, out = F.run("apprendre", "retours")
check(c == 0 and "prompt:ValueError (search.py:88:search_memories) ×2" in out and "session-start ×2" in out
      and "cerveau:youtube (6×)" in out, "retours : pannes regroupées par endroit du code, hooks lents, skills du plugin jamais suivies", out)
check(all(x not in out for x in ("hunter2", "jean", "Jean", "secret.txt", "C:/Users", "/home/", "ma-skill-perso", "vieux", "prive")),
      "retours : ni message d'erreur, ni chemin, ni nom, ni skill personnelle, ni panne trop ancienne", out)
os.environ["BRAIN_HOME"] = str(F.brain_dir)
from brainkit import common  # noqa: E402

fb = None
r = subprocess.run([sys.executable, "-I", "-S", "-c",
                    "import sys, json; sys.path.insert(0, sys.argv[1]); from brainkit import apprendre; "
                    "print(json.dumps(apprendre.feedback()))", str(CODE)], capture_output=True, env=F.env, timeout=60)
fb = json.loads(r.stdout.decode("utf-8"))
check(set(fb) == {"v", "version", "systeme", "python", "moteur", "jours", "le", "pannes", "lents", "reflexe", "delegation"}
      and fb["systeme"] in ("windows", "macos", "linux") and "hunter2" not in json.dumps(fb),
      "retours : la fiche partagée ne contient que des compteurs et des versions", fb)

print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
if FAIL or os.environ.get("KEEP"):
    print(f"(dossier gardé : {TMP})")
else:
    common.remove_tree(TMP, wait=30)
sys.exit(1 if FAIL else 0)
