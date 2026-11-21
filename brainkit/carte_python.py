"""Carte de projets : parseur Python (symboles, imports, routes, variables d'environnement) et graphe d'appels
(références de chaque fonction vers les noms importés ou définis). Partie de mapper.py, découpé le 21/11/2026."""
from __future__ import annotations

import ast
import re
import warnings
from collections import Counter, defaultdict, deque
from pathlib import Path

from .carte_langages import leading_doc, parse_generic, STDLIB
from .common import first_line

# =============================================================================================== parseurs
PY_ENV = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]([A-Za-z_]\w*)['"]|os\.environ\[\s*['"]([A-Za-z_]\w*)['"]\s*\]""")
DJANGO_PATH = re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]\s*,\s*([\w.]+)""")
ROUTE_METHODS = {"route", "get", "post", "put", "patch", "delete", "websocket", "api_route", "head", "options"}


def _decorator_routes(fn):
    out = []
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
            continue
        meth = d.func.attr.lower()
        if meth not in ROUTE_METHODS or not d.args:
            continue
        a0 = d.args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
            continue
        verb = meth.upper()
        if meth in ("route", "api_route"):
            verb = "ANY"
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    vals = [e.value for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    if vals:
                        verb = "/".join(v.upper() for v in vals)
        out.append(f"{verb} {a0.value} → {fn.name}")
    return out


def _is_main_guard(test) -> bool:
    return isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__"


def parse_python(text, rel):
    out = {"symbols": [], "imports": [], "routes": []}
    try:
        with warnings.catch_warnings():  # échappements invalides dans le code analysé : pas notre affaire
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return parse_generic(text, rel, "python_fallback")
    doc = ast.get_docstring(tree)
    out["doc"] = first_line(doc) if doc else leading_doc(text)
    consts = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["symbols"].append({"n": node.name, "k": "fn", "l": node.lineno})
            out["routes"] += _decorator_routes(node)
        elif isinstance(node, ast.ClassDef):
            out["symbols"].append({"n": node.name, "k": "class", "l": node.lineno})
            for sub in node.body[:80]:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("__") and sub.name != "__init__":
                        continue
                    out["symbols"].append({"n": f"{node.name}.{sub.name}", "k": "method", "l": sub.lineno})
                    out["routes"] += _decorator_routes(sub)
        elif isinstance(node, ast.If) and _is_main_guard(node.test):
            out["main"] = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and consts < 12:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 2:
                    out["symbols"].append({"n": t.id, "k": "const", "l": node.lineno})
                    consts += 1
    binds, stars = {}, []  # noms importés (hors bibliothèque standard) → base du graphe d'appels
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out["imports"] += [a.name for a in node.names]
            for a in node.names:
                top = a.name.split(".")[0]
                if top not in STDLIB:
                    binds[a.asname or top] = ("m", a.name if a.asname else top)
        elif isinstance(node, ast.ImportFrom):
            dots = "." * (node.level or 0)
            mod = node.module or ""
            if mod:
                out["imports"].append(dots + mod)
            for a in node.names[:12]:
                if a.name != "*":
                    out["imports"].append(dots + (mod + "." if mod else "") + a.name)
            if dots or mod.split(".")[0] not in STDLIB:
                for a in node.names:
                    if a.name == "*":
                        stars.append(dots + mod)
                    else:
                        binds[a.asname or a.name] = ("f", dots + mod, a.name)
    out["env"] = sorted({a or b for a, b in PY_ENV.findall(text)})
    if rel.endswith("urls.py"):
        out["routes"] += [f"PATH /{p} → {v}" for p, v in DJANGO_PATH.findall(text)[:40]]
    out["imports"] = list(dict.fromkeys(out["imports"]))
    try:
        out["pyrefs"] = _py_refs(tree, out["symbols"], binds, stars)
    except Exception:  # graphe d'appels facultatif : jamais au prix des symboles
        pass
    out["pystar"] = list(dict.fromkeys(stars))
    return out


# =============================================================================================== graphe d'appels (Python)
# Façon graphify (« affected ») : qui appelle quoi, pour savoir ce qui casse avant de modifier. Les références sont
# notées brutes à l'analyse (par fichier : la carte reste incrémentale), puis résolues à la demande sur la carte entière.
# Règle reprise de graphify : un nom ambigu ne donne aucun lien plutôt qu'un faux.
MAX_REFS = 1500  # références gardées par fichier
CALL_NOISE_WORDS = frozenset((
    "add get set put pop run call start stop open close read write send load dump save join wait poll info debug "
    "warning error exception log update apply submit result cancel execute commit rollback connect fetch process "
    "handle check validate parse build create delete remove reset setup render show draw name value data exists "
    "mkdir glob rglob touch unlink rename acquire release notify emit dispatch trigger refresh reload flush seek tell "
    "readline readlines writelines headers json text content status raise_for_status iter_content add_argument "
    "add_parser parse_args set_defaults add_subparsers").split())
_CALL_NOISE = None


def _call_noise():
    """Noms trop courants pour deviner un appel : builtins, méthodes des types natifs, API usuelles."""
    global _CALL_NOISE
    if _CALL_NOISE is None:
        import builtins
        import datetime
        import io
        kinds = (str, bytes, bytearray, list, dict, set, frozenset, tuple, int, float, complex, object, Path,
                 io.TextIOWrapper, io.BufferedReader, io.BytesIO, io.StringIO, type(re.compile("")),
                 type(re.match("", "")), datetime.datetime, datetime.timedelta, deque, Counter, defaultdict)
        _CALL_NOISE = CALL_NOISE_WORDS.union(dir(builtins), *(dir(k) for k in kinds))
    return _CALL_NOISE


def _locals(fn):
    """Noms locaux d'une fonction (paramètres, affectations, boucles, with, except, définitions internes) : ils masquent
    les noms du module. Les imports faits dans la fonction n'en sont pas : ils restent des liens."""
    names, glob = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            names.update(x.arg for x in a.posonlyargs + a.args + a.kwonlyargs)
            names.update(x.arg for x in (a.vararg, a.kwarg) if x)
            if n is not fn and not isinstance(n, ast.Lambda):
                names.add(n.name)
        elif isinstance(n, ast.ClassDef):
            names.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            glob.update(n.names)
    return names - glob


def _py_refs(tree, symbols, binds, stars) -> dict:
    """Références d'un module Python, notées brutes : {appelant: ["ligne relation genre a [b [c]]", …]}.
    Appelant : « fonction », « Classe.méthode », « Classe » (bases, décorateurs, corps), CONSTANTE, « » (module).
    Relation : c appel · h héritage · r usage (fonction passée en valeur, table de rappels, constante).
    Genre : l nom du fichier · i nom importé (module, nom) · m module importé (chemin, attribut) · f nom importé suivi
    d'attributs (module, chemin, attribut) · s self.attr · p super().attr · * import étoile · a méthode devinée par
    son seul nom (gardée seulement si un seul candidat)."""
    noise = _call_noise()
    local = {s["n"] for s in symbols if "." not in s["n"]}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name) and t.id.isupper():
                    local.add(t.id)
    classes = {s["n"] for s in symbols if s["k"] == "class"}
    out, seen = {}, set()

    def note(caller, line, rel, r):
        if not r or len(seen) >= MAX_REFS:
            return
        k = (caller, rel) + r
        if k not in seen:
            seen.add(k)
            out.setdefault(caller, []).append(" ".join((str(line), rel) + r))

    def ref(e, cls, shadow):
        if isinstance(e, ast.Name):
            n = e.id
            if n in shadow:
                return None
            b = binds.get(n)
            if b:
                return ("i", b[1], b[2]) if b[0] == "f" else None
            if n in local:
                return ("l", n)
            return ("*", n) if stars and n not in noise else None
        if not isinstance(e, ast.Attribute):
            return None
        attr, chain, v = e.attr, [], e.value
        while isinstance(v, ast.Attribute):
            chain.append(v.attr)
            v = v.value
        chain.reverse()
        if isinstance(v, ast.Name):
            n = v.id
            if n in ("self", "cls") and cls and not chain:
                return ("s", cls, attr)
            if n not in shadow:
                b = binds.get(n)
                if b and b[0] == "m":
                    return ("m", ".".join([b[1]] + chain), attr)
                if b:
                    return ("f", b[1], ".".join([b[2]] + chain), attr)
                if n in classes and not chain:
                    return ("l", f"{n}.{attr}")
                return None  # module de la bibliothèque standard, variable globale… : rien à deviner
        elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "super":
            return ("p", cls, attr) if cls and not chain else None
        if attr.startswith("__") or len(attr) < 4 or attr in noise:
            return None
        return ("a", attr)

    def scan(nodes, caller, cls, shadow):
        stack = [(x, cls) for x in reversed(nodes)]
        while stack:
            e, c = stack.pop()
            if isinstance(e, ast.Call):
                note(caller, e.lineno, "c", ref(e.func, c, shadow))
                root = e.func
                while isinstance(root, ast.Attribute):
                    root = root.value
                if not isinstance(root, ast.Name):
                    stack.append((root, c))  # Panier().ajouter(), TABLE[k](x) : l'objet appelé se lit aussi
                args = list(e.args) + [k.value for k in e.keywords]
                for a in args:
                    if isinstance(a, ast.Attribute):
                        r = ref(a, c, shadow)
                        if r and r[0] in ("s", "p"):
                            note(caller, a.lineno, "r", r)  # Thread(target=self.boucle)
                stack.extend((a, c) for a in reversed(args))
            elif isinstance(e, ast.Name):
                if isinstance(e.ctx, ast.Load):
                    note(caller, e.lineno, "r", ref(e, c, shadow))
            elif isinstance(e, ast.Attribute):
                r = ref(e, c, shadow) if isinstance(e.ctx, ast.Load) else None
                if r and r[0] in ("m", "f", "l"):
                    note(caller, e.lineno, "r", r)
                else:
                    stack.append((e.value, c))
            else:
                if isinstance(e, ast.ClassDef):
                    c = None
                stack.extend((x, c) for x in reversed(list(ast.iter_child_nodes(e))))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan([node], node.name, None, _locals(node))
        elif isinstance(node, ast.ClassDef):
            C = node.name
            for b in node.bases:
                r = ref(b, None, ())
                if r and r[0] != "a":
                    note(C, node.lineno, "h", r)
            scan(node.decorator_list + [k.value for k in node.keywords], C, None, set())
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    who = C if sub.name.startswith("__") and sub.name != "__init__" else f"{C}.{sub.name}"
                    scan([sub], who, C, _locals(sub))
                else:
                    scan([sub], C, C, set())
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            who = next((t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper()), "")
            scan([x for x in (node.value, getattr(node, "annotation", None)) if x is not None], who, None, set())
        else:
            scan([node], "", None, set())
    return out
