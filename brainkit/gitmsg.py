"""Échecs de git en français : ce qui s'est passé et quoi faire, à la place de la sortie brute de git (en anglais).

Utilisé par la synchronisation du wiki et `brain publish` (le cerveau commun a la sienne : commun._unreachable). Les
motifs reconnus viennent des messages de git (2.3x à 2.5x), de GitHub et du gestionnaire d'identifiants ; un échec
qu'on ne reconnaît pas garde la première ligne d'erreur de git, citée après l'explication."""
from __future__ import annotations

import re

# (motif dans la sortie de git, ce qui s'est passé, quoi faire) — le premier qui correspond l'emporte.
CASES = (
    (r"could not resolve host|could not resolve hostname|name or service not known|temporary failure in name resolution"
     r"|failed to connect|connection refused|connection timed out|operation timed out|network is unreachable"
     r"|unable to access .*(?:proxy|timed out|connect)|proxy|ssl_connect|tls|couldn't connect|no route to host"
     r"|early eof|the remote end hung up unexpectedly|rpc failed",
     "GitHub injoignable (pas de réseau, proxy ou pare-feu)",
     "vérifie la connexion, puis relance"),
    (r"authentication failed|could not read username|could not read password|terminal prompts disabled"
     r"|permission denied|access denied|403|401|invalid username or password|support for password authentication",
     "accès refusé par GitHub (identifiants absents ou sans droit d'écriture sur ce dépôt)",
     "connecte-toi (`gh auth login`, ou le gestionnaire d'identifiants de Git), puis relance"),
    (r"repository not found|not found|does not appear to be a git repository|no such remote",
     "dépôt introuvable à cette adresse (adresse fausse, dépôt supprimé, ou privé sans accès)",
     "vérifie l'adresse : `git remote -v` dans le dossier"),
    (r"\[rejected\]|non-fast-forward|fetch first|updates were rejected",
     "GitHub a des nouveautés que ce dossier n'a pas encore",
     "elles seront récupérées à la prochaine synchronisation (pull), puis l'envoi repartira"),
    (r"conflict|could not apply|merge conflict|unmerged",
     "conflit : la même page a été modifiée des deux côtés",
     "rien n'est perdu ; règle-le à la main dans le dossier (`git status`)"),
    (r"please tell me who you are|unable to auto-detect email|empty ident name",
     "git ne connaît pas encore ton nom",
     "`git config --global user.name \"Ton nom\"` et `git config --global user.email <ton adresse>`, puis relance"),
    (r"index\.lock|another git process seems to be running",
     "un autre git travaille dans ce dossier (ou s'est arrêté net)",
     "attends qu'il finisse ; s'il n'y en a plus, retire le fichier .git/index.lock, puis relance"),
    (r"not a git repository",
     "ce dossier n'est pas un dépôt git",
     "`git init` (ou clone ton dépôt GitHub) dans le dossier"),
    (r"no space left on device|disk quota exceeded",
     "disque plein",
     "libère de la place, puis relance"),
)


def first_error(out) -> str:
    """La ligne qui dit l'erreur dans la sortie de git (fatal:, error:, ! [rejected]…), sinon la première."""
    lines = [x.strip() for x in str(out or "").splitlines() if x.strip()]
    pick = next((x for x in lines if x.lower().startswith(("fatal:", "error:", "! ", "remote: error"))), None)
    return pick or (lines[0] if lines else "")


def explain(out, code=None, what="git") -> str:
    """Sortie de git (stdout + stderr) d'un échec → « <quoi> : ce qui s'est passé — quoi faire (git : « … ») »."""
    text = str(out or "")
    low = text.lower()
    if code == 127 or re.search(r"no such file or directory: '?git'?|\[winerror 2\]|git: (command )?not found", low):
        return f"{what} : git introuvable sur ce PC — installe Git (git-scm.com), puis relance"
    if "timed out after" in low or "timeoutexpired" in low:
        return f"{what} : git ne répond pas (délai dépassé) — réseau lent ou GitHub injoignable ; relance plus tard"
    for pattern, why, todo in CASES:
        if re.search(pattern, low):
            line = first_error(text)
            return f"{what} : {why} — {todo}" + (f" (git : « {line[:160]} »)" if line else "")
    line = first_error(text)
    return f"{what} : git a échoué" + (f" (« {line[:200]} »)" if line else "") + " — `git status` dans le dossier"


def is_conflict(out) -> bool:
    return bool(re.search(r"conflict|could not apply|unmerged", str(out or "").lower()))


def is_unreachable(out) -> bool:
    """Échec sans rien à régler dans le dossier (réseau, accès, adresse) : rien n'a été récupéré ni envoyé."""
    low = str(out or "").lower()
    return not is_conflict(low) and any(re.search(p, low) for p, _, _ in CASES[:3])
