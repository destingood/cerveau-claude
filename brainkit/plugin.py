"""Mode plugin Claude Code (installation d'un ami) : le code arrive par le plugin « cerveau », que Claude Code met à
jour tout seul ; les souvenirs restent dans ~/.claude/brain.

- Lanceur stable ~/.claude/brain/brain.py, réécrit à chaque démarrage : les commandes données à Claude
  (`python "$HOME/.claude/brain/brain.py" …`) visent toujours le code de la version installée.
- Consignes du cerveau injectées au démarrage (un plugin n'écrit pas dans CLAUDE.md).
- Le plugin s'efface devant le cerveau classique (code dans ~/.claude/brain) : jamais deux cerveaux à la fois."""
from __future__ import annotations

import os

from .common import BRAIN_DIR, CODE_DIR, PLUGIN, write_text

LAUNCHER = '''#!/usr/bin/env python3
"""🧠 Lanceur du cerveau (plugin Claude Code), réécrit à chaque démarrage de session : il lance le code du plugin,
que Claude Code met à jour tout seul. Les souvenirs restent dans ce dossier."""
import os
import runpy
import sys

CODE = {code!r}
os.environ.setdefault("BRAIN_HOME", os.path.dirname(os.path.abspath(__file__)))
sys.argv[0] = os.path.join(CODE, "brain.py")
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def classic_install() -> bool:
    """Cerveau classique déjà là (code et souvenirs dans ~/.claude/brain) ? Le plugin le laisse travailler seul."""
    return (BRAIN_DIR / "brainkit").is_dir()


def ensure_launcher() -> bool:
    """Écrit (ou met à jour) le lanceur stable. → True s'il a changé."""
    if not PLUGIN or classic_install():
        return False
    path = BRAIN_DIR / "brain.py"
    text = LAUNCHER.format(code=str(CODE_DIR))
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    write_text(path, text)
    return True


def instructions() -> str:
    """Le bloc CLAUDE.md du cerveau classique, sans ses balises : consignes de chaque session en mode plugin."""
    from .install import CLAUDE_BLOCK, skill_sources
    text = "\n".join(line for line in CLAUDE_BLOCK.strip().splitlines() if not line.startswith("<!--"))
    if os.environ.get("CERVEAU_CLOUD"):  # session cloud lancée par le wiki : code récupéré, pas de skill installée
        text = text.replace("skill `/brain`", f"référence complète : {CODE_DIR / 'skills' / 'brain' / 'SKILL.md'}")
        metier = " · ".join(f"{name} : {src / 'SKILL.md'}" for name, src in skill_sources().items())
        return text + (f"\nSkills métier (à lire dès qu'une demande s'y rapporte) — {metier}" if metier else "")
    return text.replace("skill `/brain`", "skill `/cerveau:brain`")
