"""Synchronisation git du wiki : commit, pull --rebase et push, sur plusieurs PC sans jamais bloquer. Un conflit se
règle seul (la version de GitHub reste en place, celle de ce PC en copie à côté), index.md et les pages régénérées
restent hors de git, log.md et .gitignore sont fusionnés, un git interrompu est nettoyé.

Découpé de wiki.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis wiki (`wiki.sync`, `wiki.commit`, `wiki.push_pending`…)."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from . import obsidian, wikistore as ws
from .common import FileLock, log, now_iso, read_json, short, write_json, write_text
from .wiki import GIT_LOCK, INDEX, JOURNAL_DIR, LOG, SYNC_STATE, _changes, git, is_repo, pc_name, remote, write_index
from .wiki_journal import MONTH_RX, _merge_month, _migrate_journal
from .wiki_textes import UNION


def _upstream(root, why=None):
    """→ arguments de `git pull` adaptés : la branche suivie, sinon la branche du même nom sur origin si elle existe,
    sinon None (dépôt distant encore vide : rien à récupérer). Dépôt injoignable (réseau, accès) : None aussi, et
    `why` (liste) reçoit la sortie de git — avant, c'était pris pour un dépôt vide, sans un mot."""
    if git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", timeout=10)[0] == 0:
        return ["pull", "--rebase", "--autostash"]
    code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    if code or not branch or branch == "HEAD":
        return None
    code, heads = git(root, "ls-remote", "--heads", "origin", branch, timeout=60)
    if code and why is not None:
        why.append(heads or f"code {code}")
    return ["pull", "--rebase", "--autostash", "origin", branch] if code == 0 and heads.strip() else None


# Fichiers régénérés sur chaque PC à partir de ses propres données : hors de git (sinon un conflit à chaque fois que
# deux PC changent quelque chose). Un wiki d'avant la 8.30.0 les suivait : ils sortent de l'index à la synchro suivante,
# sans être effacés du dossier.
UNTRACKED = (INDEX, obsidian.STATUS, obsidian.CARD)


GENERATED = (JOURNAL_DIR + "/", ".obsidian/")  # régénérés aussi, mais suivis : en conflit, la version de GitHub reste


LINES_UNION = (".gitignore", ".gitattributes", ".ignore")


def _ensure_lines(path, lines) -> bool:
    """Ajoute à un petit fichier texte les lignes qui lui manquent (sans toucher au reste). → True s'il a changé."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError:
        return False
    miss = [ln for ln in lines if ln not in text.splitlines()]
    if not miss:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, (text.rstrip("\n") + "\n" if text.strip() else "") + "\n".join(miss) + "\n")
    return True


def _prepare_repo(root) -> None:
    """Réglages git du wiki pour travailler sur plusieurs PC (idempotent, quelques ms) : index.md et les pages
    régénérées hors de git, log.md et .gitignore fusionnés des deux côtés. `.git/info/attributes` (propre à ce PC) fait
    effet tout de suite, avant même que le .gitattributes du dépôt soit arrivé sur l'autre PC."""
    root = Path(root)
    _ensure_lines(root / ".gitignore", [f"/{x}" for x in UNTRACKED])  # sinon `git add -A` les remettrait dans git
    _ensure_lines(root / ".gitattributes", UNION)
    if (root / ".git").is_dir():
        _ensure_lines(root / ".git" / "info" / "attributes", UNION)
    code, out = git(root, "ls-files", "-z", "--", *UNTRACKED, timeout=20)
    names = [x for x in out.split("\0") if x.strip()] if code == 0 else []
    if names:
        git(root, "rm", "--cached", "-q", "--ignore-unmatch", "--", *names, timeout=30)
    _migrate_journal(root)  # journal/AAAA-MM.md d'avant la 8.31.0 → journal/ancien/ (un dossier par PC désormais)


def conflict_copy_name(rel, pc=None, when=None, n=1) -> str:
    """« wiki/Faits/Prix.md » → « wiki/Faits/Prix (conflit PC-2 2026-11-21 14h05).md » (wikistore ne le lit pas) ;
    `n` > 1 : « … 14h05 2) » quand le premier nom est déjà pris."""
    head, _, name = rel.rpartition("/")
    stem, dot, ext = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
    tag = f"conflit {pc or pc_name()} {when or time.strftime('%Y-%m-%d %Hh%M')}" + (f" {n}" if n > 1 else "")
    return (head + "/" if head else "") + f"{stem} ({tag}){dot}{ext}"


def _blob(root, stage, rel):
    """Contenu d'un fichier en conflit, côté `stage` (1 ancêtre, 2 GitHub, 3 ce PC pendant un rebase). → octets ou None."""
    try:
        r = subprocess.run(["git", "-C", str(root), "show", f":{stage}:{rel}"], capture_output=True, timeout=30,
                           stdin=subprocess.DEVNULL, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _unmerged(root) -> dict:
    """Fichiers en conflit → {chemin: {étapes présentes}} (2 : version de GitHub, 3 : version de ce PC)."""
    code, out = git(root, "ls-files", "-u", "-z", timeout=20)
    rows = {}
    for item in out.split("\0") if code == 0 else []:
        meta, tab, path = item.partition("\t")
        bits = meta.split()
        if tab and len(bits) == 3 and bits[2].isdigit():
            rows.setdefault(path, set()).add(int(bits[2]))
    return rows


def _union_log(ours, theirs) -> str:
    """log.md des deux côtés : celui de GitHub, puis les entrées de ce PC qu'il n'a pas (jamais rien d'effacé)."""
    def blocks(text):
        parts = re.split(r"(?m)^(?=## \[)", text)
        return parts[0], [b.rstrip("\n") for b in parts[1:]]
    head, mine = blocks(ours)
    have = set(mine)
    extra = [b for b in blocks(theirs)[1] if b not in have]
    out = [head.rstrip("\n")] + mine + extra
    return "\n\n".join(x for x in out if x.strip()) + "\n"


def _union_lines(ours, theirs) -> str:
    seen, out = set(), []
    for ln in ours.splitlines() + theirs.splitlines():
        if ln not in seen or not ln.strip():
            seen.add(ln)
            out.append(ln)
    return "\n".join(out).rstrip("\n") + "\n"


def _resolve(root, copies) -> bool:
    """Règle seul les fichiers en conflit d'un rebase (rien ne se perd) :
    - index.md et les pages régénérées : sortis de git (chaque PC a le sien) ;
    - log.md, .gitignore : les lignes des deux côtés gardées ;
    - un mois du journal (journal/…/AAAA-MM.md) : les lignes des deux côtés, jour par jour ;
    - .obsidian/ (régénéré) : la version de GitHub ;
    - une page (ou tout autre fichier) modifiée des deux côtés : la version de GitHub reste en place, celle de ce PC
      est posée à côté, en copie de conflit (`copies` reçoit son chemin) ; supprimée d'un côté et modifiée de l'autre :
      la version modifiée est gardée.
    → False s'il reste un fichier qu'on ne sait pas régler (l'appelant annule alors le rebase)."""
    root = Path(root)
    rows = _unmerged(root)
    for rel, stages in sorted(rows.items()):
        name = rel.rsplit("/", 1)[-1]
        if rel in UNTRACKED:
            ok = git(root, "rm", "--cached", "-q", "--", rel, timeout=30)[0] == 0
        elif rel == LOG or name in LINES_UNION or (rel.startswith(JOURNAL_DIR + "/") and MONTH_RX.match(name)
                                                   and 2 in stages and 3 in stages):
            ours, theirs = (_blob(root, s, rel) or b"" for s in (2, 3))
            merge = _union_log if rel == LOG else _merge_month if rel.startswith(JOURNAL_DIR + "/") else _union_lines
            write_text(root / rel, merge(ours.decode("utf-8", "replace"), theirs.decode("utf-8", "replace")))
            ok = git(root, "add", "--", rel, timeout=30)[0] == 0
        elif 2 in stages and (3 not in stages or rel.startswith(GENERATED)):
            ok = git(root, "checkout", "--ours", "--", rel, timeout=30)[0] == 0 and git(root, "add", "--", rel)[0] == 0
        elif 3 in stages and 2 not in stages:  # supprimée sur GitHub, modifiée ici : la version modifiée reste
            ok = git(root, "checkout", "--theirs", "--", rel, timeout=30)[0] == 0 and git(root, "add", "--", rel)[0] == 0
        elif 2 in stages and 3 in stages:  # modifiée des deux côtés : GitHub en place, ce PC à côté
            mine = _blob(root, 3, rel)
            ok = mine is not None and git(root, "checkout", "--ours", "--", rel, timeout=30)[0] == 0 \
                and git(root, "add", "--", rel)[0] == 0
            if ok:
                when, n = time.strftime("%Y-%m-%d %Hh%M"), 1
                copy = conflict_copy_name(rel, when=when)
                while (root / copy).exists():
                    n += 1
                    copy = conflict_copy_name(rel, when=when, n=n)
                (root / copy).parent.mkdir(parents=True, exist_ok=True)
                (root / copy).write_bytes(mine)
                ok = git(root, "add", "--", copy, timeout=30)[0] == 0
                if ok:
                    copies.append(copy)
        else:  # supprimée des deux côtés (ou rien d'exploitable) : rien à garder
            ok = git(root, "rm", "--cached", "-q", "--ignore-unmatch", "--", rel, timeout=30)[0] == 0
        if not ok:
            return False
    return True


def _rebasing(root) -> bool:
    g = Path(root) / ".git"
    return (g / "rebase-merge").exists() or (g / "rebase-apply").exists()


def _pull(root, how, copies) -> tuple:
    """pull --rebase ; un conflit se règle seul (_resolve), commit après commit. → (code, sortie de git)."""
    code, txt = git(root, *how, timeout=120)
    for _ in range(50):  # un tour par commit de ce PC rejoué sur ceux de GitHub
        if code == 0 or not _rebasing(root):
            break
        if _unmerged(root):
            if not _resolve(root, copies):
                break
            code, txt = git(root, "-c", "core.editor=true", "rebase", "--continue", timeout=60)
        elif re.search(r"no changes|nothing to commit|skip this patch|now empty|allow-empty", txt, re.I):
            # commit devenu vide une fois le conflit réglé (le même changement déjà sur GitHub) : rien à rejouer
            code, txt = git(root, "-c", "core.editor=true", "rebase", "--skip", timeout=60)
        else:  # autre échec (identité git, hook…) : jamais de --skip, il jetterait le commit ; l'appelant annule tout
            break
    return code, txt


def _unstick(root) -> list:
    """Un git interrompu ne bloque plus la synchronisation : verrous de plus de 2 min retirés, rebase abandonné en plan
    (plus de 2 min aussi) annulé. Appelé sous GIT_LOCK. → ce qui a été nettoyé."""
    from . import gitmsg
    done = gitmsg.clear_stale_locks(root, 120)
    g = Path(root) / ".git"
    for d in (g / "rebase-merge", g / "rebase-apply"):
        try:
            if d.exists() and time.time() - d.stat().st_mtime > 120:
                git(root, "rebase", "--abort", timeout=30)
                done.append(d.name)
        except OSError:
            continue
    return done


def commit(root, message=None) -> str:
    """Commit de tout ce qui a changé. → résumé (vide s'il n'y avait rien)."""
    _prepare_repo(root)
    rows = _changes(root)
    if not rows:
        return ""
    pages = [p for _, p in rows if p.startswith((ws.PAGES + "/", ws.ARCHIVE + "/")) and p.endswith(".md")]
    raws = [p for _, p in rows if p.startswith(ws.RAW + "/")]
    if not message:
        bits = []
        if pages:
            bits.append(f"{len(pages)} page(s)")
        if raws:
            bits.append(f"{len(raws)} source(s)")
        others = len(rows) - len(pages) - len(raws)
        if others:
            bits.append(f"{others} autre(s)")
        names = ", ".join(ws.stem(p) for p in pages[:6]) + (" …" if len(pages) > 6 else "")
        message = "cerveau : " + ", ".join(bits) + (f" — {names}" if names else "")
    git(root, "add", "-A", timeout=60)
    code, out = git(root, "commit", "-q", "-m", message, timeout=60)
    if code:
        from . import gitmsg
        return "✗ " + gitmsg.explain(out, code, "commit") + " ; les pages restent telles quelles dans le dossier"
    return message


def sync(root=None, push=True, pull=True, auto=False) -> list:
    """Commit, puis pull --rebase et push si le dépôt a une adresse GitHub. Un conflit se règle seul (_resolve : la
    version de GitHub en place, celle de ce PC en copie à côté, signalée au démarrage suivant) ; s'il ne peut pas l'être,
    le rebase est annulé (rien ne reste à moitié fait). Jamais « ✓ » pour une étape ratée : ses lignes commencent par
    « ✗ » (code de sortie 1 pour `brain wiki sync`), et `brain wiki status` dit la dernière synchro ratée.
    → lignes de compte rendu."""
    root = Path(root or ws.root() or "")
    if not str(root) or not (root / ws.MARKER).is_file():
        return ["✗ pas de wiki ici : `brain wiki init <dossier>`"]
    if not is_repo(root):
        return ["· pas de dépôt git dans le wiki : `git init` (ou clone ton dépôt GitHub) pour l'historique et la "
                "synchronisation"]
    if auto and os.environ.get("CLAUDE_CODE_REMOTE"):
        return ["· session cloud : pas de synchronisation automatique (commit et push sur la branche de la session)"]
    out = []
    try:
        with FileLock(GIT_LOCK, timeout=2 if auto else 20, stale=600):
            from . import gitmsg
            cleaned = _unstick(root)
            if cleaned:
                out.append(f"· git interrompu nettoyé ({', '.join(cleaned)}) : la synchronisation repart")
            st = read_json(SYNC_STATE, {}) or {}
            fails, net = [], False
            msg = commit(root)
            if msg.startswith("✗"):
                out.append(msg)
                fails.append(msg)
                out.append("· pull et envoi remis à la prochaine synchronisation : rien n'est perdu, les pages restent "
                           "dans le dossier")
                pull = push = False
            elif msg:
                out.append("✓ commit : " + msg)
            url = remote(root)
            why = []
            how = _upstream(root, why) if url and pull else None
            if why:  # GitHub injoignable : rien n'est récupéré, et un envoi échouerait de même
                line = ("✗ " + gitmsg.explain(why[0], what="pull") + " ; rien n'est perdu, les pages restent dans "
                        "le dossier et partiront à la prochaine synchronisation")
                out.append(line)
                fails.append(line)
                net = gitmsg.is_unreachable(why[0])
                st["pull_failed"] = now_iso()
                push = False
            if how:
                copies = []
                code, txt = _pull(root, how, copies)
                if code and (gitmsg.is_conflict(txt) or _rebasing(root)):
                    git(root, "rebase", "--abort", timeout=30)
                    st["conflict"] = now_iso()
                    line = (f"✗ pull : conflit que le cerveau n'a pas pu régler seul — rien n'est perdu (rebase "
                            f"annulé) ; à régler à la main dans {root} (`git status`, puis `brain wiki sync`)"
                            f" (git : « {short(gitmsg.first_error(txt), 160)} »)")
                    out.append(line)
                    fails.append(line)
                    push = False
                elif code:  # réseau, accès… : pas un conflit (avant, il était noté comme tel au démarrage suivant)
                    if _rebasing(root):
                        git(root, "rebase", "--abort", timeout=30)
                    st["pull_failed"] = now_iso()
                    line = "✗ " + gitmsg.explain(txt, code, "pull") + " ; rien n'est perdu (pages gardées dans le dossier)"
                    out.append(line)
                    fails.append(line)
                    net = gitmsg.is_unreachable(txt)
                    push = False
                else:
                    st.pop("conflict", None)
                    st.pop("pull_failed", None)
                    out.append("✓ pull" + ("" if "up to date" in txt.lower() or "à jour" in txt.lower() else
                                          f" : {short(txt.splitlines()[-1] if txt else '', 120)}"))
                    if copies:
                        names = ", ".join(f"« {c.rsplit('/', 1)[-1]} »" for c in copies[:5])
                        out.append(f"✓ conflit réglé : {len(copies)} fichier(s) modifié(s) ici et sur un autre PC — la "
                                   f"version de GitHub reste en place, celle de ce PC est gardée en copie à côté : "
                                   f"{names}" + (" …" if len(copies) > 5 else "")
                                   + " (relis-la, garde ce qui compte dans la page, puis supprime la copie)")
                        st["copies"] = sorted(set(st.get("copies") or []) | set(copies))
                    try:  # catalogue de ce PC à jour avec les pages reçues (index.md n'est plus dans git)
                        here = ws.root()
                        if here and Path(here).resolve() == root.resolve():
                            write_index(root=root)
                    except Exception as exc:
                        log(f"wiki sync : index.md : {exc!r}")
                    if _migrate_journal(root):  # un PC pas à jour a réécrit un journal/AAAA-MM.md : rangé, envoyé
                        commit(root, "cerveau : journal d'avant la 8.31.0 rangé dans journal/ancien/")
            if url and push:
                code, txt = git(root, "push", "-u", "origin", "HEAD", timeout=120)
                if code == 0:
                    out.append("✓ push")
                else:
                    line = ("✗ " + gitmsg.explain(txt, code, "push") + " ; les commits restent ici et partiront à la "
                            "prochaine synchronisation")
                    out.append(line)
                    fails.append(line)
                    net = net or gitmsg.is_unreachable(txt)
            elif not url:
                out.append("· pas d'adresse GitHub (origin) : historique local seulement — `git remote add origin <url>`")
            if fails:  # jamais « dernière synchro » pour une synchro ratée : `brain wiki status` la dit
                st["failed"] = {"le": now_iso(), "quoi": short(fails[0][2:], 220), "reseau": net}
            else:
                st.pop("failed", None)
                st["synced"] = now_iso()
            write_json(SYNC_STATE, st)
    except TimeoutError:
        out.append("· synchronisation déjà en cours ailleurs")
    if auto:
        log("wiki sync : " + " | ".join(out))
    return out


def push_pending(root) -> str:
    """Envoie sur GitHub les commits déjà faits, sans commit ni pull : les fichiers ne sont pas touchés, donc sans
    risque pendant qu'une session écrit dans le wiki (veille). → compte rendu, "" s'il n'y a rien à envoyer."""
    root = Path(root)
    if not is_repo(root) or not remote(root):
        return ""
    try:
        with FileLock(GIT_LOCK, timeout=2, stale=600):
            code, txt = git(root, "rev-list", "--count", "@{u}..HEAD", timeout=20)
            ahead = int(txt) if code == 0 and txt.isdigit() else 0
            if not ahead:
                return ""
            code, txt = git(root, "push", "origin", "HEAD", timeout=120)
    except TimeoutError:
        return ""  # une synchro est en cours : elle envoie elle-même
    if code == 0:
        return f"{ahead} commit(s) envoyé(s) sur GitHub (session ouverte : ni commit ni pull)"
    if re.search(r"rejected|fetch first|non-fast-forward", txt):
        return "en attente : GitHub a des nouveautés, récupérées à la prochaine synchro complète"
    from . import gitmsg
    raise RuntimeError(gitmsg.explain(txt, code, "envoi du wiki"))
