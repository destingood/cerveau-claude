"""Lanceur des hooks (décision E1 du plan) : trouver un Python 3.10 ou plus récent là où la commande `python` n'existe
pas (macOS, beaucoup de Linux : seulement `python3` ; Windows : souvent seulement `py`). À ne pas confondre avec le
« lanceur stable » ~/.claude/brain/brain.py (plugin.py), qui relaie les commandes vers le code du plugin.

Il essaie, dans l'ordre : $CERVEAU_PYTHON (si l'utilisateur l'a réglé), l'interpréteur qu'a vu `brain install`
(installation classique), puis python3, python et py. Il saute les alias du Microsoft Store qui ouvrent le Store au lieu
de lancer Python, et sur macOS le /usr/bin/python3 qui ouvrirait la fenêtre d'installation des outils de développement.
Un Python trop ancien (brain.py sort alors avec TROP_ANCIEN, avant de lire l'entrée) cède la place au suivant ; un
Python 2 (il refuse l'option -I : code 2) aussi. Entrée, sortie et code de sortie passent tels quels. Aucun Python
utilisable : une ligne en français dit quoi installer (Claude Code l'affiche dans sa notice « hook error ») au démarrage
et à chaque message, les autres hooks se taisent (code 0 : un code non nul bloquerait l'outil Agent sous Windows sans
Git Bash, et ferait trois notices par message).

Comment Claude Code lance un hook « command » (https://code.claude.com/docs/en/hooks, Exec form and shell form ;
https://code.claude.com/docs/en/plugins-reference, Environment variables) :
- avec "args" (forme exec), `command` est un exécutable cherché dans le PATH, sans shell : `python` absent → échec ;
- sans "args" (forme shell), la chaîne passe à `sh -c` sur macOS et Linux, à Git Bash sous Windows, ou à PowerShell
  quand Git Bash n'est pas installé (pwsh, sinon powershell.exe, avec -NoProfile -NonInteractive -ExecutionPolicy
  Bypass -Command). Dans ce dernier cas, ${CLAUDE_PLUGIN_ROOT} est réécrit en ${env:CLAUDE_PLUGIN_ROOT} ;
- aucun réglage ne choisit un hook selon le système.

D'où une seule chaîne pour les trois shells (polyglotte) : `sh` et Git Bash lisent la partie POSIX (SH) et sortent ;
PowerShell voit cette partie dans une chaîne entre apostrophes, puis lit la sienne (ps), qui pour sh est entre
apostrophes. Aucune des deux ne contient donc d'apostrophe droite (les messages prennent l'apostrophe typographique).
La partie POSIX ne lance aucun sous-shell (que des commandes internes, puis Python) : quelques millisecondes."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

PYTHON_MIN = (3, 10)  # README : « Python 3.10 ou plus récent » ; brain.py le vérifie avant tout import
TROP_ANCIEN = 97  # code de sortie de brain.py lancé par ce lanceur sous un Python trop ancien (voir brain.py)
CANDIDATS = ("python3", "python", "py")  # décision E1 : python3, python, puis py (le lanceur de python.org, Windows)
PARLANTS = ("session-start", "prompt")  # hooks qui affichent la ligne « cerveau en pause » (une fois par message)
MCP_COMMAND = "${CERVEAU_PYTHON:-python}"  # serveur MCP : forme exec seulement (pas de shell), d'où une variable

_INSTALLE = ("python.org (Windows : coche « Add python.exe to PATH ») ou, sur macOS, brew install python, puis "
             "redémarre Claude Code (README du cerveau, section « Prérequis »).")
MESSAGE_ABSENT = ("🧠 cerveau en pause : aucun Python trouvé (essayés : python3, python, py). Installe Python 3.10 ou "
                  "plus récent depuis " + _INSTALLE)
MESSAGE_ANCIEN = ("🧠 cerveau en pause : Python trop ancien (il faut 3.10 ou plus récent ; essayés : python3, python, "
                  "py). Installe une version récente depuis " + _INSTALLE)

# Partie POSIX (sh, dash, bash 3.2 de macOS, Git Bash). $1 : dossier de brain.py, $2 : interpréteur préféré (ou vide),
# la suite : les arguments de brain.py. Le PATH est parcouru à la main ([ -x ] est interne) : `command -v` dans un
# $(…) coûterait un sous-shell par candidat. Git Bash trouve aussi python.exe sous le nom `python`.
SH = "; ".join((
    "r=$1; q=$2; shift 2; v=; o=$IFS",
    'for n in ${CERVEAU_PYTHON:+"$CERVEAU_PYTHON"} ${q:+"$q"} ' + " ".join(CANDIDATS) + "; do x=",
    'case $n in */*) [ -f "$n" ] && [ -x "$n" ] && x=$n ;; *) IFS=:; for d in $PATH; do'
    ' [ -f "${d:-.}/$n" ] && [ -x "${d:-.}/$n" ] && { x=${d:-.}/$n; break; }; done; IFS=$o ;; esac',
    '[ -n "$x" ] || continue; w=1',
    # Alias du Microsoft Store : sans paquet Python du Store installé, il ouvre le Store (code 9009) au lieu de Python.
    'case $x in */[Ww]indows[Aa]pps/*) w=; for d in "${x%/*}"/PythonSoftwareFoundation.*; do [ -e "$d" ] && w=1; done ;;'
    # macOS sans outils de développement : /usr/bin/python3 ouvrirait leur fenêtre d'installation à chaque hook.
    ' /usr/bin/python3) if [ -e /usr/bin/xcode-select ]; then w=; for d in "${DEVELOPER_DIR:-/-}"'
    " /var/db/xcode_select_link /Library/Developer/CommandLineTools /Applications/Xcode.app/Contents/Developer; do"
    ' [ -e "$d/usr/bin/python3" ] && w=1; done; fi ;; esac',
    '[ -n "$w" ] || continue',
    # `python` sans python3 utilisable avant lui (vieux macOS, vieux Linux) peut être Python 2 : essayé à vide d'abord,
    # sinon son « Unknown option: -I » passerait avant la ligne du cerveau. Sous Windows, `python` est le bon.
    'case $n in python) [ "$OS" = Windows_NT ] || "$x" -I -S -c pass </dev/null >/dev/null 2>&1 || { v=1; continue; } ;;'
    " esac",
    'CERVEAU_LANCEUR=1 "$x" -I -S "$r/brain.py" "$@"; c=$?',
    # 126/127 : pas exécutable ; 49 : 9009 (alias du Store) tronqué par Git Bash ; 2 : Python 2 refuse -I (vérifié),
    # sinon le vrai code de brain.py.
    f"case $c in {TROP_ANCIEN}) v=1 ;; 126|127) ;; 49) [ \"$OS\" = Windows_NT ] || exit 49 ;;"
    ' 2) "$x" -I -S -c pass </dev/null >/dev/null 2>&1 && exit 2; v=1 ;; *) exit $c ;; esac',
    "done",
    '[ "$1" = hook ] && case $2 in ' + "|".join(PARLANTS) + ") ;; *) exit 0 ;; esac",
    f'if [ -n "$v" ]; then echo "{MESSAGE_ANCIEN}" >&2; else echo "{MESSAGE_ABSENT}" >&2; fi',
    "exit 1",
))


def ps(event: str) -> str:
    """Partie PowerShell (Windows sans Git Bash ; Windows PowerShell 5.1 ou PowerShell 7). L'entrée du hook est lue
    une fois puis donnée à chaque essai ; la sortie et l'erreur de Python vont droit au tube de Claude Code (non
    redirigées : aucun réencodage par PowerShell), son code de sortie aussi. Le message est écrit en octets UTF-8."""
    old, absent = (m.replace('"', "`\"") for m in (MESSAGE_ANCIEN, MESSAGE_ABSENT))
    names = ",".join(f'"{n}"' for n in CANDIDATS)
    quiet = "" if event in PARLANTS else "exit 0; "
    return "; ".join((
        f'$r=$env:CLAUDE_PLUGIN_ROOT; $a="hook {event}"; $v=0; $m=New-Object IO.MemoryStream',
        "try{[Console]::OpenStandardInput().CopyTo($m)}catch{}; $d=$m.ToArray()",
        f"foreach($n in @($env:CERVEAU_PYTHON,{names})){{ if(!$n){{continue}}",
        "$c=@(Get-Command $n -CommandType Application -ErrorAction Ignore)[0]; if(!$c){continue}; $x=$c.Path",
        'if($x -like "*\\WindowsApps\\*" -and !(Test-Path ((Split-Path $x)+"\\PythonSoftwareFoundation.*"))){continue}',
        '$i=New-Object Diagnostics.ProcessStartInfo $x,("-I -S `"$r\\brain.py`" "+$a)',
        '$i.UseShellExecute=$false; $i.RedirectStandardInput=$true; $i.EnvironmentVariables["CERVEAU_LANCEUR"]="1"',
        "try{$p=[Diagnostics.Process]::Start($i)}catch{continue}",
        "try{$p.StandardInput.BaseStream.Write($d,0,$d.Length); $p.StandardInput.Close()}catch{}",
        f"$p.WaitForExit(); $e=$p.ExitCode; if($e -eq {TROP_ANCIEN}){{$v=1; continue}}; if($e -eq 9009){{continue}}",
        'if($e -eq 2){$i.Arguments="-I -S -c pass"; $i.RedirectStandardOutput=$true; $i.RedirectStandardError=$true;'
        " $k=[Diagnostics.Process]::Start($i); $k.StandardInput.Close(); $k.WaitForExit(); if($k.ExitCode){$v=1; continue}}",
        "exit $e }",
        quiet + f'$t="{absent}"; if($v){{$t="{old}"}}; $b=[Text.Encoding]::UTF8.GetBytes($t+"`n")',
        "$s=[Console]::OpenStandardError(); $s.Write($b,0,$b.Length); $s.Flush(); exit 1",
    ))


def commande_plugin(event: str) -> str:
    """La commande (forme shell) d'un hook du plugin, la même sous sh, Git Bash et PowerShell. Pour sh :
    `echo \\'` écrit une apostrophe dans /dev/null, la partie POSIX tourne et sort, `: '…'` n'est jamais exécuté.
    Pour PowerShell : `echo \\'…'` est une chaîne envoyée dans $null, puis vient sa partie, et `#'` est un commentaire."""
    for part in (SH, ps(event)):
        if "'" in part:
            raise ValueError("apostrophe droite dans une partie du lanceur : la commande ne serait plus polyglotte")
    return (f'echo \\\' >/dev/null; set -- "${{CLAUDE_PLUGIN_ROOT}}" "" hook {event}; {SH}; '
            f": ' >$null; {ps(event)} #'")


def hook_plugin(event: str, timeout: int, status=None, background=False) -> dict:
    """Un hook de hooks/hooks.json (publish._hook)."""
    h = {"type": "command", "command": commande_plugin(event), "timeout": timeout}
    if status:
        h["statusMessage"] = status
    if background:
        h["async"] = True
    return h


def _interpreteur_installe():
    """L'interpréteur qui lance `brain install` (installation classique) : celui-là marche, c'est lui qu'on préfère.
    Un alias du Microsoft Store change de chemin à chaque mise à jour de Python : sous Windows, `py -3` à la place."""
    exe = sys.executable or ""
    if exe and os.path.exists(exe) and "windowsapps" not in exe.lower() and not exe.lower().endswith("pythonw.exe"):
        return exe, []
    if os.name == "nt" and shutil.which("py"):
        return "py", ["-3"]
    return exe or "python", []


def hook_classique(root, event: str, timeout: int, status=None, background=False) -> dict:
    """Un hook de ~/.claude/settings.json (installation classique, install.merged_settings), en forme exec : aucun
    chemin à mettre entre guillemets, aucun shell à analyser la commande. macOS et Linux : /bin/sh lance la partie
    POSIX du lanceur, avec en premier l'interpréteur de `brain install`. Windows : cet interpréteur directement (il
    marche, et ainsi ni Git Bash ni PowerShell ne démarrent à chaque hook) ; `brain doctor` signale s'il disparaît."""
    script = os.path.join(str(root), "brain.py")
    exe, pre = _interpreteur_installe()
    if os.name == "nt":
        h = {"type": "command", "command": exe, "args": [*pre, "-I", "-S", script, "hook", event]}
    else:
        h = {"type": "command", "command": "/bin/sh", "args": ["-c", SH, "cerveau", str(root), exe, "hook", event]}
    h["timeout"] = timeout
    if status:
        h["statusMessage"] = status
    if background:
        h["async"] = True
    return h


def est_du_cerveau(h) -> bool:
    """Ce hook lance-t-il brain.py hook … (toutes les formes : chaîne d'avant la 8.29, exec, polyglotte) ?"""
    if not isinstance(h, dict):
        return False
    text = " ".join([str(h.get("command", ""))] + [str(a) for a in (h.get("args") or [])])
    return "brain.py" in text and " hook " in text


# --------------------------------------------------------------------------------------- ce que dit `brain doctor`
def _version(exe, timeout=5):
    """(majeur, mineur, correctif) de cet interpréteur, ou None s'il ne se lance pas (alias du Store, cassé…)."""
    try:
        r = subprocess.run([exe, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], capture_output=True,
                           text=True, errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        found = re.search(r"(\d+)\.(\d+)\.(\d+)", r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        found = None
    return tuple(int(x) for x in found.groups()) if found else None


def _saute(exe) -> str:
    """Pourquoi le lanceur ne lance même pas cet interpréteur ("" : il l'essaie). Mêmes règles que SH et ps()."""
    low = exe.replace("\\", "/").lower()
    if "/windowsapps/" in low:
        folder = os.path.dirname(exe)
        try:
            if not any(n.startswith("PythonSoftwareFoundation.") for n in os.listdir(folder)):
                return "alias du Microsoft Store sans Python installé (il ouvrirait le Store)"
        except OSError:
            return "alias du Microsoft Store illisible"
    if low == "/usr/bin/python3" and os.path.exists("/usr/bin/xcode-select"):
        dev = [os.environ.get("DEVELOPER_DIR") or "/-", "/var/db/xcode_select_link",
               "/Library/Developer/CommandLineTools", "/Applications/Xcode.app/Contents/Developer"]
        if not any(os.path.exists(os.path.join(d, "usr", "bin", "python3")) for d in dev):
            return "outils de développement d'Apple absents (il ouvrirait leur fenêtre d'installation)"
    return ""


def essai(name, saute=True) -> dict:
    """Un candidat, tel que ce PATH le résout : {nom, exe, version, raison} ; raison vide = utilisable, sinon
    "introuvable", "trop ancien", "ne se lance pas" ou celle de _saute (saute=False : le serveur MCP, lancé tel quel)."""
    exe = (name if os.path.isfile(name) else None) if os.path.dirname(name) else shutil.which(name)
    row = {"nom": name, "exe": exe, "version": None, "raison": ""}
    if not exe:
        row["raison"] = "introuvable"
        return row
    row["raison"] = _saute(exe) if saute else ""
    if not row["raison"]:
        row["version"] = _version(exe)
        if not row["version"]:
            row["raison"] = "ne se lance pas"
        elif row["version"][:2] < PYTHON_MIN:
            row["raison"] = "trop ancien"
    return row


def essais(prefere=None) -> list:
    """Ce que fera le lanceur sur ce PC, dans l'ordre, jusqu'au premier utilisable (celui que les hooks lanceront) :
    [essai(…)]. prefere : l'interpréteur de `brain install` (installation classique)."""
    out = []
    for name in [n for n in (os.environ.get("CERVEAU_PYTHON"), prefere) if n] + list(CANDIDATS):
        out.append(essai(name))
        if not out[-1]["raison"]:
            break
    return out


def choisi(rows):
    """Le premier essai retenu, ou None."""
    return next((r for r in rows if not r["raison"]), None)


def prefere(h):
    """L'interpréteur qu'un hook classique de settings.json lance en premier → (chemin ou nom, lanceur?) : lanceur=True
    quand il passe par la partie POSIX du lanceur (il en trouvera un autre si celui-ci disparaît)."""
    args = [str(a) for a in (h.get("args") or [])]
    cmd = str(h.get("command", ""))
    if args:
        if cmd == "/bin/sh" and len(args) >= 5 and args[0] == "-c":
            return args[4], True
        return cmd, False
    m = re.match(r'^"([^"]+)"|^(\S+)', cmd.strip())  # chaîne d'avant la 8.29 : "C:/…/python.exe" -I -S "…" hook …
    return (m.group(1) or m.group(2)) if m else "", False
