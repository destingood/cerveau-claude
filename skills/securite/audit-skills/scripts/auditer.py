"""Auditer une skill tierce avant de l'installer : verdict « sûre », « à vérifier » ou « refusée », avec les raisons.

Analyse statique seulement : rien n'est lancé, aucun lien n'est suivi, rien ne part sur le réseau. Le moteur est
celui du cerveau (brainkit/skills_audit.py, le même contrôle que l'échange de skills entre amis) ; ce script le
trouve à côté de la skill (plugin) ou dans ~/.claude/brain (installation classique).

Usage :
  python auditer.py <dossier de la skill> [<autre dossier> …] [--json] [--infos]

  --json    résultat en JSON (une liste, un objet par dossier)
  --infos   montrer aussi les constats sans gravité (programme lancé sans shell…)

Code de sortie : 0 sûre, 1 à vérifier, 2 refusée (le pire des dossiers donnés), 3 erreur d'utilisation.
Une skill sur GitHub : la cloner d'abord dans un dossier temporaire (`git clone --depth 1 <url> <dossier>`), sans
rien y lancer, puis auditer le dossier de la skill."""
import json
import os
import sys
from pathlib import Path


def _engine():
    """brainkit, cherché en remontant depuis ce script (plugin : <plugin>/brainkit ; classique : ~/.claude/brain)."""
    here = Path(__file__).resolve()
    homes = [Path(os.environ["CLAUDE_CONFIG_DIR"]) / "brain"] if os.environ.get("CLAUDE_CONFIG_DIR") else []
    for root in [*here.parents, *homes, Path.home() / ".claude" / "brain"]:
        for cand in (root, root / "brain"):
            if (cand / "brainkit" / "skills_audit.py").is_file():
                sys.path.insert(0, str(cand))
                from brainkit import skills_audit
                return skills_audit
    return None


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--json", "--infos", "--help"}
    if not args or "--help" in flags or unknown:
        print(__doc__.strip())
        if unknown:
            print(f"\n✗ option inconnue : {', '.join(sorted(unknown))}")
        return 3 if (unknown or not args) and "--help" not in flags else 0
    engine = _engine()
    if engine is None:
        print("✗ moteur du cerveau introuvable (brainkit/skills_audit.py) : le cerveau est-il installé ?")
        return 3
    results = [engine.audit(a) for a in args]
    if "--json" in flags:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print("\n\n".join(engine.report(r, infos="--infos" in flags) for r in results))
    return max(engine.VERDICTS.index(r["verdict"]) for r in results)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
