"""Veille automatique (`brain auto`) : le cerveau et le coffre Obsidian tenus à jour sans session de Claude, toutes les
30 min (Planificateur de tâches de Windows ; ailleurs, une ligne cron). Zéro token : aucune étape n'appelle de modèle.

Une passe fait ce qui est dû, une étape après l'autre (jamais deux git en même temps) : notes du jour → souvenirs,
entretien et sauvegarde du jour, index.md, synchronisation git du wiki (pas pendant une session de Claude : elle s'en
charge), garde de consommation, cerveau commun, rattrapage du journal, puis page Cerveau, carte et vue 3D. L'ingestion des
sources de raw/ reste à la demande : il faut un modèle pour les lire et la validation de l'utilisateur (étape 3 du schéma
du wiki)."""
from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .common import (BRAIN_DIR, BRAIN_PY, PLUGIN, SESSIONS_DIR, STATE_DIR, FileLock, load_config, log, now_iso,
                     read_json, set_config, short, write_json)

TASK = "Cerveau (veille automatique)"
EVERY = 30  # min entre deux passes
STEP_TIMEOUT = 600  # s : une étape bloquée (réseau) n'empêche pas les suivantes
ACTIVE = 1800  # s : une session de Claude qui a bougé depuis moins longtemps synchronise le wiki elle-même
LOCK = STATE_DIR / "auto.lock"
LAST = STATE_DIR / "auto.json"
# CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS : console cachée (git y répond, pas sous pythonw), priorité basse
NO_WINDOW = 0x08000000 | 0x00004000


def _python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        exe = exe.parent / "python.exe"
    return str(exe)


def _hidden() -> dict:
    return {"creationflags": NO_WINDOW} if os.name == "nt" else {}


def run(args, timeout=STEP_TIMEOUT) -> tuple:
    """`brain.py <args>` jusqu'au bout, sans fenêtre et en priorité basse. → (code, première ligne de la sortie)."""
    try:
        r = subprocess.run([_python(), "-I", "-S", str(BRAIN_PY), *args], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=timeout, cwd=str(BRAIN_DIR), env={**os.environ, "BRAIN_BG": "1"}, **_hidden())
    except subprocess.TimeoutExpired:
        return 124, f"arrêtée après {timeout} s"
    except Exception as exc:
        return 1, short(repr(exc), 160)
    lines = (r.stdout or r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return r.returncode, short(lines[0], 160) if lines else ""


def session_active(now=None) -> bool:
    """Une session de Claude a-t-elle bougé (démarrage, message, fin de tour) depuis moins de 30 min ?"""
    now = now or time.time()
    try:
        return any(now - f.stat().st_mtime < ACTIVE for f in SESSIONS_DIR.glob("*.json"))
    except OSError:
        return False


def run_pass(cfg=None) -> list:
    """Une passe : ce qui est dû, dans l'ordre. → lignes du compte rendu {etape, code, texte}."""
    from . import commun, hooks, obsidian, viz, wiki
    from .store import Brain
    cfg = cfg or load_config()
    rows = []

    def step(name, args):
        code, text = run(args)
        rows.append({"etape": name, "code": code, "texte": text})
        return code == 0

    def here(name, fn):  # étape rapide faite dans ce processus ; notée seulement si elle a fait quelque chose
        try:
            text = fn()
            if text:
                rows.append({"etape": name, "code": 0, "texte": text})
        except Exception as exc:
            rows.append({"etape": name, "code": 1, "texte": short(repr(exc), 160)})
            log(f"auto : {name} : {exc!r}")

    brain = Brain.load()
    w = brain.data.get("wiki") or {}
    root = w.get("root") if w.get("root") and not w.get("missing") else None
    if root and obsidian.captures(root):
        step("notes du jour", ["wiki", "capture"])
    for args in hooks.daily_due(cfg):
        step({"consolidate": "entretien du jour", "backup": "sauvegarde du jour"}[args[0]], args)
    brain = Brain.load()
    if root:
        here("index.md", lambda: "réécrit" if wiki.write_index(brain, root) else "")
        if hooks._auto_sync(brain, cfg):
            if not session_active():
                step("synchro du wiki", ["wiki", "sync", "--auto"])
            else:  # session ouverte (elle se ferme rarement dans l'app) : ses commits partent quand même sur GitHub
                here("envoi du wiki", lambda: wiki.push_pending(root))
    if hooks.garde_due(cfg):
        step("garde de consommation", ["tokens", "--garde"])
    if commun.member():
        step("cerveau commun", ["commun", "sync", "--auto"])
    hooks.journal_catchup(cfg, None, launch=lambda args: step("rattrapage du journal", args))
    brain = Brain.load()
    if root:
        def vault():
            made = obsidian.setup(root)
            made += [f for f, ok in ((obsidian.STATUS, obsidian.write_status(brain, root)),
                                     (obsidian.CARD, obsidian.write_canvas(brain, root))) if ok]
            return ", ".join(made)
        here("coffre Obsidian", vault)

    def view():
        if not viz.is_stale():
            return ""
        viz.render(brain)
        return "régénérée"
    here("vue 3D", view)
    write_json(LAST, {"le": now_iso(), "etapes": rows})
    log("auto : " + (" | ".join(f"{r['etape']} {'✓' if r['code'] == 0 else '✗'}" for r in rows) or "rien de dû"))
    return rows


def main() -> list:
    """`brain auto` : une passe. Lancée par le Planificateur sous pythonw (aucune fenêtre), elle se relance une fois
    sous python.exe avec une console cachée : sans console, git ne répond plus (Git 2.56, Windows 11)."""
    if os.environ.get("CLAUDE_CODE_REMOTE"):
        return ["· session cloud : pas de veille automatique"]
    if not (load_config().get("auto") or {}).get("enabled", True):
        return ["· veille automatique coupée (`brain config auto.enabled true` la rallume)"]
    if os.name == "nt" and Path(sys.executable).name.lower() == "pythonw.exe" and os.environ.get("BRAIN_BG") != "1":
        from .hooks import spawn_background
        spawn_background(["auto"])
        return []
    try:
        with FileLock(LOCK, timeout=0, stale=3600):
            rows = run_pass()
    except TimeoutError:
        return ["· une passe est déjà en cours"]
    return [f"{'✓' if r['code'] == 0 else '✗'} {r['etape']}" + (f" : {r['texte']}" if r["texte"] else "")
            for r in rows] or ["✓ rien de dû"]


# ------------------------------------------------------------------------------------------ tâche planifiée
def launcher() -> Path:
    """Script lancé par la tâche : le lanceur stable du plugin (~/.claude/brain/brain.py, il suit les mises à jour),
    sinon le brain.py de cette installation."""
    stable = BRAIN_DIR / "brain.py"
    return stable if PLUGIN and stable.is_file() else BRAIN_PY


def pythonw() -> Path:
    exe = Path(sys.executable)
    return exe if exe.name.lower() == "pythonw.exe" else exe.with_name("pythonw.exe")


def task_xml(start=None) -> str:
    """Définition de la tâche : toutes les 30 min, session ouverte seulement (aucun mot de passe gardé), droits
    limités, aussi sur batterie, passe manquée rattrapée au réveil, jamais deux à la fois."""
    from xml.sax.saxutils import escape
    start = start or (_dt.datetime.now() + _dt.timedelta(minutes=1)).replace(second=0, microsecond=0)
    user = os.environ.get("USERNAME")
    user = f"{os.environ['USERDOMAIN']}\\{user}" if user and os.environ.get("USERDOMAIN") else user
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Cerveau de Claude : notes du jour, wiki, page Cerveau d'Obsidian, entretien du jour. Zéro token. Retirer : brain auto --retirer</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>PT{EVERY}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
{f"      <UserId>{escape(user)}</UserId>" + chr(10) if user else ""}      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(pythonw()))}</Command>
      <Arguments>{escape(f'"{launcher()}" auto')}</Arguments>
      <WorkingDirectory>{escape(str(BRAIN_DIR))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(*args) -> tuple:
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True, timeout=60, **_hidden())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, repr(exc)
    return r.returncode, (r.stdout + r.stderr).decode("oem" if os.name == "nt" else "utf-8", "replace").strip()


def install(dry=False) -> list:
    """Pose la tâche planifiée (Windows) ; ailleurs, montre la ligne cron à ajouter sans rien modifier."""
    if os.name != "nt":
        return ["· hors Windows : ajoute cette ligne à ta crontab (`crontab -e`), le cerveau ne la pose pas lui-même :",
                f'*/{EVERY} * * * * "{sys.executable}" "{launcher()}" auto >/dev/null 2>&1']
    if not pythonw().is_file():
        return [f"✗ pythonw.exe introuvable à côté de {sys.executable} : sans lui, une fenêtre s'ouvrirait à chaque passe"]
    xml = task_xml()
    if dry:
        return [f"· tâche « {TASK} » à poser (rien n'est fait) : toutes les {EVERY} min, "
                f"\"{pythonw()}\" \"{launcher()}\" auto", xml]
    p = STATE_DIR / "auto-tache.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(xml, encoding="utf-16")
    code, text = _schtasks("/Create", "/TN", TASK, "/XML", str(p), "/F")
    try:
        p.unlink()
    except OSError:
        pass
    if code:
        return [f"✗ tâche planifiée non posée : {short(text, 300)}"]
    set_config("auto.tache", now_iso())
    set_config("auto.coupe", None)
    return [f"✓ tâche planifiée « {TASK} » posée : une passe toutes les {EVERY} min, sans fenêtre, zéro token",
            "  état : brain auto --etat · retirer : brain auto --retirer"]


def uninstall() -> list:
    if os.name != "nt":
        return ["· hors Windows : retire la ligne `… brain.py\" auto` de ta crontab (`crontab -e`)"]
    code, text = _schtasks("/Delete", "/TN", TASK, "/F")
    set_config("auto.tache", None)
    set_config("auto.coupe", now_iso())  # choix de l'utilisateur : la réparation automatique ne la remet pas
    return ["✓ tâche planifiée retirée" if code == 0 else f"· aucune tâche à retirer ({short(text, 200)})"]


def task_action():
    """(programme, arguments) de la tâche posée ; None s'il n'y a pas de tâche."""
    from html import unescape
    code, text = _schtasks("/Query", "/TN", TASK, "/XML")
    if code:
        return None
    cmd, args = (re.search(rf"<{t}>(.*?)</{t}>", text, re.S) for t in ("Command", "Arguments"))
    return unescape(cmd.group(1).strip()) if cmd else "", unescape(args.group(1).strip()) if args else ""


def wanted() -> bool:
    """Veille voulue : posée un jour par `--installer` (accord donné une fois) et jamais retirée par `--retirer`."""
    cfg = load_config().get("auto") or {}
    return os.name == "nt" and bool(cfg.get("tache")) and not cfg.get("coupe") and cfg.get("enabled", True)


def broken(action) -> str:
    """Raison pour laquelle la tâche ne peut plus tourner ('' si elle est saine)."""
    if action is None:
        return "tâche disparue"
    cmd, args = action
    if not cmd or not Path(cmd).is_file():
        return f"programme introuvable ({cmd or 'vide'}) : Python déplacé ou mis à jour"
    script = re.match(r'\s*"([^"]+)"', args)
    if not script or not Path(script.group(1)).is_file():
        return f"lanceur introuvable ({script.group(1) if script else args or 'vide'})"
    return ""


def heal() -> list:
    """Garde la veille en vie sans rien demander : tâche disparue (mise à jour de Windows, nettoyage) ou qui pointe vers
    un Python ou un lanceur qui n'existent plus → reposée. Seulement si elle a été posée un jour, jamais après `--retirer`."""
    if not wanted():
        return []
    why = broken(task_action())
    if not why:
        return []
    log(f"auto : {why} → tâche reposée")
    return [f"· veille : {why} → reposée"] + install()


def state_lines() -> list:
    out = []
    if os.name == "nt":
        code, text = _schtasks("/Query", "/TN", TASK, "/FO", "LIST")
        if code == 0:
            out.append(f"✓ tâche planifiée « {TASK} » posée (toutes les {EVERY} min)")
            out += [f"  {ln.strip()}" for ln in text.splitlines()
                    if re.match(r"\s*(Prochaine|Next Run|Statut|Status)", ln)]
        else:
            out.append("· pas de tâche planifiée : `brain auto --installer` la pose")
    last = read_json(LAST, {}) or {}
    if not last.get("le"):
        return out + ["· aucune passe encore"]
    out.append(f"Dernière passe : {last['le'][:16].replace('T', ' ')}")
    rows = last.get("etapes") or []
    return out + ([f"  {'✓' if r.get('code') == 0 else '✗'} {r.get('etape')}" + (f" : {r['texte']}" if r.get("texte")
                                                                               else "") for r in rows]
                  or ["  rien n'était dû"])


def planned() -> bool:
    """La tâche a-t-elle été posée par `brain auto --installer` (pour les textes d'Obsidian) ?"""
    return bool((load_config().get("auto") or {}).get("tache"))
