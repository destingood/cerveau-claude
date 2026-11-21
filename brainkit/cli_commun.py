"""Aides communes de la ligne de commande : argparse en français, die, refresh_views, lecture des arguments (projet,
types, texte, champs du wiki), ligne d'un souvenir.

Découpé de cli.py (étape 8 du plan) sans rien changer : le parseur et main() restent dans cli.py, qui ne charge ce
module qu'au moment d'en lancer une commande."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import fold, log, short, slugify
from .store import GLOBAL_REFS, TYPES, Brain, normalize_type


def die(msg, code=1):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


# Messages d'argparse traduits (il les passe tous par gettext, nommé « _ » dans son module) : plus de « error: the
# following arguments are required » ni d'aide en anglais.
_FR = {"usage: ": "utilisation : ", "positional arguments": "arguments", "options": "options",
       "optional arguments": "options", "show this help message and exit": "afficher cette aide",
       "subcommands": "sous-commandes", " (default: %(default)s)": " (défaut : %(default)s)",
       "the following arguments are required: %s": "argument manquant : %s",
       "unrecognized arguments: %s": "argument inattendu : %s",
       "argument %(argument_name)s: %(message)s": "%(argument_name)s : %(message)s",
       "expected one argument": "une valeur attendue après l'option",
       "expected at least one argument": "au moins une valeur attendue",
       "expected at most one argument": "au plus une valeur attendue",
       "invalid choice: %(value)r (choose from %(choices)s)": "choix inconnu : %(value)r (au choix : %(choices)s)",
       "invalid %(type)s value: %(value)r": "valeur illisible : %(value)r",
       "ambiguous option: %(option)s could match %(matches)s": "option ambiguë : %(option)s peut être %(matches)s",
       "not allowed with argument %s": "incompatible avec %s",
       "one of the arguments %s is required": "un de ces arguments est obligatoire : %s",
       "ignored explicit argument %r": "valeur %r ignorée",
       "%(prog)s: error: %(message)s\n": "✗ %(prog)s : %(message)s\n"}


# Noms des arguments sans option, tels qu'argparse les cite quand ils manquent.
_ARG_FR = {"text": "texte", "target": "fichier ou symbole", "name": "nom", "file": "fichier", "new": "nouveau",
           "old": "ancien", "event": "événement", "ref": "n° ou date", "a": "premier", "b": "second", "id": "id",
           "key": "clé", "value": "valeur", "path": "dossier", "action": "action"}


_FR_ON = False


def _french_argparse():
    global _FR_ON
    if not _FR_ON:
        _FR_ON = True
        en = argparse._
        argparse._ = lambda msg: _FR.get(msg, en(msg))


class Parser(argparse.ArgumentParser):
    """argparse en français ; une valeur qui commence par « - » (prise pour une option) : dire comment la donner."""

    def error(self, message):
        import re
        # Python 3.10 et 3.11 ne passent pas « argument X: … » par la traduction (ArgumentError.__str__), les suivants si
        message = re.sub(r"^argument (\S+): ", r"\1 : ", message)
        if message.startswith("argument manquant : "):
            names = [_ARG_FR.get(x.strip(), x.strip()) for x in message.split(" : ", 1)[1].split(",")]
            message = f"argument manquant : {', '.join(names)}"
        m = re.match(r"<commande> : choix inconnu : '([^']*)' \(au choix : (.*)\)$", message)
        if m:  # commande mal tapée : la plus proche, pas la liste entière des 150 noms
            import difflib
            near = difflib.get_close_matches(m.group(1), re.findall(r"'([^']*)'", m.group(2)), n=3, cutoff=0.6)
            message = f"commande inconnue : « {m.group(1)} »" + (f" — voulais-tu : {', '.join(near)} ?" if near else "")
        args = sys.argv[1:]
        opts = set(self._option_string_actions)
        dash = [i for i, x in enumerate(args) if x.startswith("-") and len(x) > 1 and x != "--"
                and x.split("=")[0] not in opts and not re.match(r"^-\d", x) and i > 0]
        hint = ""
        if dash and re.match(r"(argument manquant|argument inattendu|.* : une valeur attendue)", message):
            i = dash[0]
            if args[i - 1] in opts and args[i - 1].startswith("-"):  # valeur d'une option : collée avec « = »
                fix = " ".join(args[:i - 1] + [f"{args[i - 1]}={args[i]}"] + args[i + 1:])
            else:  # texte sans option : après « -- », tout est du texte
                fix = " ".join(args[:i] + ["--"] + args[i:])
            hint = f"\n  une valeur qui commence par « - » est prise pour une option ; écris : `brain {fix}`"
        self.print_usage(sys.stderr)
        self.exit(2, f"✗ {self.prog} : {message}{hint}\n  aide : `{self.prog} -h`\n")


def _number(kind, lo=None, hi=None, example=None):
    """Type d'argument : nombre (entier si kind is int) entre lo et hi, message en français sinon."""
    span = (f"de {lo} à {hi}" if hi is not None else f"d'au moins {lo}") if lo is not None else ""

    def parse(text):
        try:
            v = kind(str(text).replace(",", ".")) if kind is float else int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{'nombre entier' if kind is int else 'nombre'} attendu, pas « {text} »"
                                             + (f" (ex. {example})" if example is not None else "")) from None
        if v != v or (lo is not None and v < lo) or (hi is not None and v > hi):
            raise argparse.ArgumentTypeError(f"« {text} » refusé : {'nombre entier' if kind is int else 'nombre'} {span} "
                                             "attendu" + (f" (ex. {example})" if example is not None else ""))
        return v
    return parse


def _positive(kind=int, example=5):
    return _number(kind, 1 if kind is int else 0.01, None, example)


def refresh_views(brain=None, wait=False):
    """Après une modification. Mode wiki : index.md du wiki tout de suite (une page du wiki, lue par Claude et envoyée
    par git). Le reste — index injecté BRAIN.md, export MEMOIRES.md, vues 3D et 2D — est refait en arrière-plan une fois
    les écritures calmées (vues.py) : la commande n'écrit que le graphe. wait=True : tout de suite (réparation).
    `brain` : le cerveau tout juste enregistré par l'appelant (évite de le relire)."""
    try:
        from . import wikistore
        if wikistore.resolve()[0] == "wiki":
            b = brain or Brain.load()
            if b.data.get("wiki") and not b.data["wiki"].get("missing"):
                from . import wiki
                wiki.write_index(b)
    except Exception as exc:
        log(f"refresh_views (wiki) : {exc!r}")
    try:
        from . import vues
        if wait:  # réparation : toutes, tout de suite
            vues.run_now(force=True)
        elif not vues.request():  # lancement en arrière-plan impossible : comme avant, tout de suite
            vues.run_now()
    except Exception as exc:
        log(f"refresh_views : {exc!r}")


def body_of(a):
    if getattr(a, "body_file", None):
        return Path(a.body_file).read_text(encoding="utf-8")
    body = getattr(a, "body", None)
    if body == "-":
        return sys.stdin.read()
    return body


def types_of(spec):
    if not spec:
        return None
    try:
        return [normalize_type(t) for t in spec.split(",") if t.strip()]
    except ValueError as exc:
        die(str(exc))


def project_arg(b, ref, cwd=None):
    """-p : id/nom/chemin, « . » = projet courant, « none » = global."""
    if ref is None:
        return None, False
    if str(ref).lower() in GLOBAL_REFS:
        return None, True
    proj = b.resolve_project(ref, cwd)
    if not proj:
        die(f"projet introuvable : {ref} (voir `brain proj`)")
    return proj, True


def wiki_meta(a, meta):
    """--resume, --sources, --domaine (pages du wiki), --commun (cerveau commun) → champs de meta ; « none » les retire."""
    share = fold(getattr(a, "commun", None) or "")
    if share in ("oui", "yes", "partage", "partager", "public"):
        meta["partage"] = True
        meta.pop("prive", None)
    elif share in ("non", "no", "prive", "privee"):
        meta["prive"] = True
        meta.pop("partage", None)
    elif share == "auto":
        meta.pop("partage", None)
        meta.pop("prive", None)
    if getattr(a, "resume", None) is not None:
        if fold(a.resume) in ("none", "aucun", "-", ""):
            meta.pop("resume", None)
        else:
            meta["resume"] = " ".join(a.resume.split())
    if getattr(a, "sources", None) is not None:
        import re
        from .wikistore import links_in
        raw = a.sources.strip()
        if fold(raw) in ("none", "aucune", "-", ""):
            meta.pop("sources", None)
        else:  # « [[A]], [[B]] » ou « A, B »
            refs = [f"[[{t}]]" for t in (links_in(raw) or [x.strip() for x in re.split(r"[,;\n]", raw) if x.strip()])]
            meta["sources"] = list(dict.fromkeys(list(meta.get("sources") or []) + refs))
    if getattr(a, "domaine", None) is not None:
        doms = [slugify(x, 30) for x in a.domaine.split(",") if x.strip() and fold(x.strip()) not in ("none", "-")]
        if doms:
            meta["domaine"] = doms
        else:
            meta.pop("domaine", None)
    return meta


def node_line(n, chars=110):
    body = short((n.get("meta") or {}).get("resume") or n.get("body", ""), chars)  # page du wiki : son résumé d'abord
    arch = " (archivé)" if n.get("status", "active") != "active" else ""
    who = (n.get("meta") or {}).get("commun_par")
    return (f"[{TYPES.get(n['type'], n['type'])}{f' 🤝 {who}' if who else ''}] {n['title']}" + (f" — {body}" if body else "")
            + f"  `{n['id']}`{arch}")
