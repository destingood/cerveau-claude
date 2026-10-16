"""Auto-déploiement : `brain self-update` installe le code (brain.py, brainkit/, tests/) depuis l'arbre de
développement vers le cerveau installé (~/.claude/brain), SANS jamais toucher aux données (souvenirs, config,
journal, historique, pages HTML). Il sauvegarde d'abord l'ancien code, copie, vérifie (la suite de tests) et
revient en arrière tout seul si la vérification échoue. « Une fois le changement fait, le cerveau se met en place
tout seul, quel que soit le changement. »

Ne s'applique PAS à l'installation plugin d'un ami : là, c'est Claude Code qui met le plugin à jour lui-même."""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .common import CLAUDE_HOME, PLUGIN, load_config, read_json, write_json

# CODE (remplacé par une mise à jour) vs DONNÉES (jamais touchées : graph.json, config.json, BRAIN.md, history/…).
CODE_ROOT_FILES = ("brain.py",)
CODE_DIRS = ("brainkit", "tests")


def _code_files(root: Path) -> dict:
    """{chemin relatif POSIX -> Path absolu} de tout le CODE sous root : brain.py + brainkit/**.py + tests/**.py
    (jamais __pycache__ ni aucun fichier de données)."""
    out = {}
    for name in CODE_ROOT_FILES:
        p = root / name
        if p.is_file():
            out[name] = p
    for d in CODE_DIRS:
        base = root / d
        if base.is_dir():
            for p in base.rglob("*.py"):
                if "__pycache__" not in p.parts:
                    out[p.relative_to(root).as_posix()] = p
    return out


def _version_of(root: Path) -> str:
    init = root / "brainkit" / "__init__.py"
    if init.is_file():
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    return "?"


def _vkey(v: str) -> tuple:
    """Clé de comparaison de version : « 7.10.0 » > « 7.4.0 » (et pas l'inverse, comme le ferait un tri de texte)."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums) if nums else (0,)


def _same(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def target_dir() -> Path:
    """Le cerveau installé (installation classique) : ~/.claude/brain (ou CLAUDE_CONFIG_DIR/brain)."""
    return CLAUDE_HOME / "brain"


def _check_source(root: Path) -> str | None:
    """Message d'erreur si root n'est pas un arbre de développement valide, sinon None."""
    if not root.exists():
        return f"source introuvable : {root}"
    if not (root / "brain.py").is_file() or not (root / "brainkit" / "__init__.py").is_file():
        return f"{root} n'a pas l'air d'un arbre du cerveau (brain.py + brainkit/ attendus)"
    if (root / ".claude-plugin" / "plugin.json").exists():
        return f"{root} est un plugin construit (.claude-plugin) : donne l'arbre de développement, pas le dépôt publié"
    # Un arbre de développement peut très bien contenir des données (graph.json…) : ce n'est pas grave, on ne copie
    # JAMAIS que le code (brain.py, brainkit/, tests/). Le seul vrai garde-fou est « source ≠ cible » (plus bas).
    return None


def _backup_dir(version: str) -> Path:
    base = CLAUDE_HOME / "backups"
    day = _dt.date.today().isoformat()
    cand = base / f"brain-code-v{version}-{day}"
    n = 2
    while cand.exists():
        cand = base / f"brain-code-v{version}-{day}-{n}"
        n += 1
    return cand


def _make_backup(target: Path, backup: Path) -> None:
    """Copie le CODE actuel de la cible (+ config.json comme simple repère) dans backup."""
    backup.mkdir(parents=True, exist_ok=True)
    for rel, src in _code_files(target).items():
        dst = backup / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    cfg = target / "config.json"
    if cfg.is_file():
        shutil.copy2(cfg, backup / "config.json")  # repère seulement, jamais réappliqué sur les données


def _restore(backup: Path, target: Path, added: list) -> None:
    """Remet le code de la sauvegarde et retire les fichiers qui venaient d'être ajoutés."""
    saved = _code_files(backup)
    for rel, src in saved.items():
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for rel in added:
        if rel not in saved:
            (target / rel).unlink(missing_ok=True)


def _default_verify(target: Path) -> tuple:
    """Lance la suite de tests de la cible (sous-processus isolé). → (ok, résumé lisible)."""
    suite = target / "tests" / "test_all.py"
    if not suite.is_file():
        return True, "pas de suite de tests à vérifier (sautée)"
    try:
        r = subprocess.run([sys.executable, "-I", "-S", str(suite)], cwd=str(target),
                           capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "suite de tests : délai dépassé (600 s)"
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    m = re.search(r"(\d+)\s+vérifications OK,\s+(\d+)\s+échec", out)
    if not m:
        return False, "suite de tests : résumé introuvable (le lanceur a planté ?)\n" + out[-800:]
    okn, failn = int(m.group(1)), int(m.group(2))
    tail = "" if failn == 0 else "\n" + out[-1200:]
    return failn == 0, f"suite de tests : {okn} OK, {failn} échec(s){tail}"


def _remember(target: Path, source: Path, version: str) -> None:
    """Note dans la config DE LA CIBLE d'où vient le code, pour qu'un simple « brain self-update » (sans argument)
    reprenne la même source. Fusion : les autres réglages sont conservés, aucune donnée n'est touchée."""
    cfg = read_json(target / "config.json", {}) or {}
    cfg.setdefault("selfupdate", {}).update({
        "source": str(source),
        "last": _dt.datetime.now().isoformat(timespec="seconds"),
        "version": version,
    })
    write_json(target / "config.json", cfg)


def deploy(source, *, force=False, verify=True, dry_run=False, verifier=None, log=print) -> int:
    """Déploie le code de `source` vers le cerveau installé. 0 = succès, autre = rien de cassé n'est resté."""
    target = target_dir()
    if PLUGIN:
        log("✗ installation plugin (ami) : les mises à jour arrivent par Claude Code, self-update ne s'applique pas ici")
        return 2
    source = Path(source).resolve()
    err = _check_source(source)
    if err:
        log("✗ " + err)
        return 1
    if not (target / "brainkit" / "__init__.py").is_file():
        log(f"✗ cerveau installé introuvable dans {target} (rien à mettre à jour)")
        return 1
    if source == target.resolve():
        log("✗ la source et la cible sont le même dossier — indique l'arbre de développement")
        return 1

    src_files, tgt_files = _code_files(source), _code_files(target)
    added = sorted(r for r in src_files if r not in tgt_files)
    removed = sorted(r for r in tgt_files if r not in src_files)
    changed = sorted(r for r in src_files if r in tgt_files and not _same(src_files[r], tgt_files[r]))
    sv, tv = _version_of(source), _version_of(target)

    if not (added or changed or removed):
        log(f"✓ déjà à jour : le code installé ({tv}) est identique à {source}")
        return 0
    if sv != "?" and tv != "?" and _vkey(sv) < _vkey(tv) and not force:
        log(f"✗ la source est en {sv}, plus ancienne que l'installé {tv} — ajoute --force pour revenir en arrière exprès")
        return 1
    if len(removed) > 2 and not force:
        log(f"✗ la source retirerait {len(removed)} fichiers de code (arbre incomplet ?) : "
            + ", ".join(removed[:6]) + (" …" if len(removed) > 6 else "")
            + "\n  vérifie la source, ou ajoute --force si c'est bien voulu")
        return 1

    transition = f"{tv} → {sv}" if sv != tv else f"{sv} (code modifié)"
    log(f"• mise à jour {transition} : {len(changed)} modifié(s), {len(added)} ajouté(s), {len(removed)} retiré(s)")
    for sign, items in (("~", changed), ("+", added), ("-", removed)):
        for rel in items:
            log(f"    {sign} {rel}")
    backup = _backup_dir(tv)
    if dry_run:
        log(f"(simulation) sauvegarde prévue : {backup} — rien n'a été touché")
        return 0

    _make_backup(target, backup)
    log(f"✓ sauvegarde du code {tv} : {backup}")
    try:
        for rel in changed + added:
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_files[rel], dst)
        for rel in removed:
            (target / rel).unlink(missing_ok=True)
    except OSError as exc:
        log(f"✗ copie interrompue ({exc!r}) — restauration de la version précédente…")
        _restore(backup, target, added)
        return 1

    if verify:
        vok, summary = (verifier or _default_verify)(target)
        log(("✓ " if vok else "✗ ") + summary)
        if not vok:
            log("  → la vérification a échoué : restauration de la version précédente…")
            _restore(backup, target, added)
            log(f"✓ revenu au code {tv} — rien de cassé n'est resté en place (sauvegarde : {backup})")
            return 1

    _remember(target, source, sv)
    log(f"✓ cerveau mis à jour en {sv} dans {target} — données intactes, sauvegarde : {backup}")
    return 0


def run(source=None, *, force=False, verify=True, dry_run=False) -> int:
    cfg = load_config().get("selfupdate", {})
    source = source or cfg.get("source")
    if not source:
        print("✗ aucune source indiquée : brain self-update <dossier de l'arbre de développement>\n"
              "  le code (brain.py, brainkit/, tests/) y est copié vers ~/.claude/brain ; tes souvenirs n'y touchent pas.\n"
              "  le dossier est retenu ensuite (un simple « brain self-update » le réutilisera).")
        return 1
    return deploy(source, force=force, verify=verify, dry_run=dry_run)
