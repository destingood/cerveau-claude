"""Socle commun : chemins, configuration, E/S robustes (Windows/UTF-8), texte, dates, verrous."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
# Plugin Claude Code (installation d'un ami) : le code vit dans le cache des plugins et change de dossier à chaque mise
# à jour ; les souvenirs restent dans ~/.claude/brain. Installation classique : code et souvenirs dans le même dossier.
PLUGIN = (CODE_DIR / ".claude-plugin" / "plugin.json").exists()
BRAIN_DIR = Path(os.environ.get("BRAIN_HOME") or (CLAUDE_HOME / "brain" if PLUGIN else CODE_DIR))
BRAIN_PY = CODE_DIR / "brain.py"
GRAPH_FILE = BRAIN_DIR / "graph.json"
INDEX_FILE = BRAIN_DIR / "BRAIN.md"
CONFIG_FILE = BRAIN_DIR / "config.json"
EXPORT_FILE = BRAIN_DIR / "MEMOIRES.md"
VIZ_FILE = BRAIN_DIR / "cerveau.html"
VIZ2D_FILE = BRAIN_DIR / "cerveau-2d.html"
REPORT_FILE = BRAIN_DIR / "RAPPORT.md"
PROJECTS_DIR = BRAIN_DIR / "projects"
JOURNAL_FILE = BRAIN_DIR / "journal" / "sessions.json"
STATE_DIR = BRAIN_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
LOG_FILE = STATE_DIR / "brain.log"
CMD = 'python "$HOME/.claude/brain/brain.py"'
if PLUGIN and BRAIN_DIR != Path.home() / ".claude" / "brain":  # plugin avec un autre dossier Claude (CLAUDE_CONFIG_DIR)
    CMD = f'python "{BRAIN_DIR.as_posix()}/brain.py"'

DEFAULT_CONFIG = {
    # Taille max de ce qui est injecté au démarrage d'une session (caractères ≈ tokens × 3,7).
    "inject": {"max_chars": 8800, "index_chars": 4200, "index_chars_project": 3000, "project_chars": 4400},
    # Rappel automatique à chaque message : souvenirs + fichiers pertinents, seulement si vraiment liés.
    "recall": {"enabled": True, "max_items": 3, "min_cov": 0.5, "min_score": 1.0, "files": True, "max_files": 4,
               "min_cov_files": 0.4, "max_chars": 1200, "session_cap_items": 12, "session_cap_files": 20},
    # Rappel en fin de tâche : « mémorise ce qui est durable » (une fois, seulement si la session a travaillé).
    "stop_reminder": {"enabled": True, "min_tool_calls": 15, "min_edits": 3, "repeat_after": 60},
    # Cartographie automatique (en arrière-plan) des dossiers de projet.
    "auto_map": {"enabled": True, "refresh_minutes": 10},
    "map": {"max_files": 15000, "max_file_kb": 768},
    "journal": {"enabled": True, "keep": 500},
    # Sauvegarde quotidienne hors du disque système (dossier auto : D:\\Sauvegardes-cerveau-Claude, sinon E:…).
    "backup": {"enabled": True, "dir": None, "keep": 14},
    # Échéances : les à-faire datés apparaissent au démarrage quand ils approchent (ou sont en retard).
    "due": {"days_ahead": 7},
    # Coffre Obsidian (`export --vault <dossier>`) : dossier retenu après le premier export.
    "vault": {"path": None},
    # Rêve : entretien quotidien hors conversation ; ligne au démarrage s'il y a au moins min_items points à trancher.
    "dream": {"notice": True, "min_items": 3},
}


# ------------------------------------------------------------------------------------------ E/S
def setup_io() -> None:
    """Force l'UTF-8 sur stdout/stderr (la console Windows est souvent en cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except Exception as exc:  # fichier corrompu : ne jamais casser une session
        log(f"read_json {path}: {exc!r}")
        return default


def _atomic_write(path: Path, payload: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows : fichier momentanément ouvert ailleurs
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def write_json(path, data, indent=1) -> None:
    _atomic_write(Path(path), json.dumps(data, ensure_ascii=False, indent=indent))


def write_text(path, text: str) -> None:
    _atomic_write(Path(path), text)


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def log(msg: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512_000:
            os.replace(LOG_FILE, LOG_FILE.with_suffix(".old.log"))
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {msg}\n")
    except Exception:
        pass


class FileLock:
    """Verrou inter-processus minimal (création exclusive d'un fichier), reprise des verrous périmés."""

    def __init__(self, path, timeout=5.0, stale=30.0):
        self.path = str(path)
        self.timeout = timeout
        self.stale = stale
        self.held = False

    def __enter__(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return self
            except (FileExistsError, PermissionError):
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError(f"verrou occupé : {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.held = False
        return False


# ------------------------------------------------------------------------------------------ config
def _merge(base, over):
    out = dict(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config() -> dict:
    return _merge(DEFAULT_CONFIG, read_json(CONFIG_FILE, {}) or {})


def set_config(dotted: str, value) -> dict:
    cfg = read_json(CONFIG_FILE, {}) or {}
    cur = cfg
    keys = dotted.split(".")
    for key in keys[:-1]:
        cur = cur.setdefault(key, {})
    cur[keys[-1]] = value
    write_json(CONFIG_FILE, cfg)
    return load_config()


# ------------------------------------------------------------------------------------------ dates
def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def days_since(value) -> float:
    d = parse_iso(value)
    if d is None:
        return 9999.0
    return max(0.0, (_dt.datetime.now() - d).total_seconds() / 86400)


def fmt_date(value) -> str:
    d = parse_iso(value)
    return d.strftime("%d/%m/%Y") if d else "?"


# ------------------------------------------------------------------------------------------ texte
_FOLD_SRC = (("àáâãäåāăą", "a"), ("çćĉċč", "c"), ("ďđ", "d"), ("èéêëēĕėęě", "e"), ("ĝğġģ", "g"), ("ĥħ", "h"),
             ("ìíîïĩīĭįı", "i"), ("ĵ", "j"), ("ķ", "k"), ("ĺļľŀł", "l"), ("ñńņňŉ", "n"), ("òóôõöøōŏő", "o"),
             ("ŕŗř", "r"), ("śŝşšș", "s"), ("ţťŧț", "t"), ("ùúûüũūŭůűų", "u"), ("ŵ", "w"), ("ýÿŷ", "y"), ("źżž", "z"))
_FOLD = {}
for _src, _dst in _FOLD_SRC:
    for _c in _src:
        _FOLD[ord(_c)] = _dst
        if len(_c.upper()) == 1:  # « ŉ ».upper() fait 2 caractères
            _FOLD[ord(_c.upper())] = _dst
_FOLD.update({ord("œ"): "oe", ord("Œ"): "oe", ord("æ"): "ae", ord("Æ"): "ae", ord("ß"): "ss", ord("ﬁ"): "fi",
              ord("ﬂ"): "fl", ord("’"): "'", ord("‘"): "'", ord("«"): '"', ord("»"): '"', ord("“"): '"', ord("”"): '"',
              ord("–"): "-", ord("—"): "-", ord("−"): "-", ord("…"): "...", ord("\u00a0"): " ", ord("\u202f"): " "})


def fold(text) -> str:
    """minuscules + sans accents (« Été » → « ete ») — table de traduction, unicodedata seulement en dernier recours."""
    s = str(text).translate(_FOLD).lower()
    if s.isascii() or not any(c.isalpha() and ord(c) > 127 for c in s):
        return s
    import unicodedata  # lettres accentuées rares (hors table) : décomposition complète
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


_STOP_FR = """a à ai aie ait as au aux avais avait avec avez avoir ayant c ça ca car ce ceci cela celle
celles celui ces cet cette ceux chaque chez comme comment d dans de des du donc dont elle elles en encore
es est et été etre être eu eux fait faire fais faites faut ici il ils j je jusqu l la le les leur leurs lui
m ma mais me même meme mes moi mon n ne ni nos notre nous on ont ou où par pas peu peut peux plus pour
pourquoi qu quand que quel quelle quelles quels qui quoi s sa sans se ses si son sont sous stp svp sur t ta
te tes toi ton tous tout toute toutes très tres tu un une vers via voici voila voilà vos votre vous y oui
non alors aussi bien bon juste veux veut vouloir merci dis donne donner mets mettre pouvoir dois doit
maintenant aujourd hui demain hier toujours jamais rien chose choses truc trucs ok okay vsy bonjour salut
parfait parfaite super genial top nickel cool excellent impeccable continue continuer go bravo
combien fois font quel quels lequel laquelle lesquels lesquelles autre autres beaucoup trop tant"""
_STOP_EN = """about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing done down during each few for from further had has have
having he her here hers him his how i if in into is it its itself just me more most my no nor not now of
off on once only or other our ours out over own same she should so some such than that the their theirs
them then there these they this those through to too under until up very was we were what when where
which while who whom why will with would you your yours please make get let"""
STOPWORDS = {fold(w) for w in (_STOP_FR + " " + _STOP_EN).split()}

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN = re.compile(r"[a-z0-9]+")


def stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokenize(text, keep_stop=False) -> list:
    """Découpe pour la recherche : camelCase/snake_case séparés, accents et pluriels neutralisés."""
    if not text:
        return []
    text = fold(_CAMEL.sub(" ", str(text)))
    out = []
    for tok in _TOKEN.findall(text):
        if len(tok) < 2 or (not keep_stop and tok in STOPWORDS):
            continue
        out.append(stem(tok))
    return out


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def slugify(text, maxlen=48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return slug[:maxlen].rstrip("-") or "n"


def short(text, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: max(1, n - 1)].rstrip() + "…"


def first_line(text, n=140) -> str:
    for line in str(text or "").splitlines():
        line = line.strip(" \t#*-/>`=")
        if line:
            return short(line, n)
    return ""


def est_tokens(text) -> int:
    return int(len(text or "") / 3.7)


# ------------------------------------------------------------------------------------------ chemins
_MSYS = re.compile(r"^/([a-zA-Z])(/.*)?$")


def norm_path(p) -> str:
    """Chemin comparable (absolu, normalisé, casse Windows). Accepte /c/... (Git Bash)."""
    s = str(p or "")
    if os.name == "nt":
        m = _MSYS.match(s)
        if m:
            s = f"{m.group(1)}:{m.group(2) or '/'}"
    return os.path.normcase(os.path.normpath(os.path.abspath(s)))


def path_within(child, parent) -> bool:
    c, p = norm_path(child), norm_path(parent)
    if c == p:
        return True
    return c.startswith(p if p.endswith(os.sep) else p + os.sep)


def is_scratch(path) -> bool:
    """Dossiers jetables de l'app (sessions « sans dossier ») : jamais traités comme des projets."""
    s = norm_path(path).replace("\\", "/").lower()
    return "scratch-workspaces" in s or "/temp/claude/" in s
