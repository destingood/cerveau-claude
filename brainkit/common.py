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

# Mesuré le 16/10/2026 sur 427 paires de requêtes réelles (contexte n+1 − contexte n autour d'un seul gros résultat
# d'outil) : 2,06 car./token en médiane ; Markdown FR 2,23, Python 2,27, sorties Bash 2,01. L'ancien 3,7 sous-estimait ×1,7.
CHARS_PER_TOKEN = 2.2

DEFAULT_CONFIG = {
    # Budgets de ce qui est injecté, en tokens (relus à chaque requête jusqu'à la compaction) : total au démarrage,
    # index hors projet / dans un projet, fiche du projet, résumé de carte, ajout après compaction, nouveautés à la reprise.
    # Les anciennes clés en caractères (max_chars, index_chars…) restent prioritaires si elles sont dans config.json.
    "inject": {"max_tokens": 2600, "index_tokens": 1650, "index_tokens_project": 1150, "project_tokens": 1250,
               "digest_tokens": 330, "compact_recall_tokens": 450, "resume_items": 5},
    # Rappel automatique à chaque message : souvenirs + fichiers pertinents, seulement si vraiment liés.
    # min_score 5 : sur 27 vrais messages (72 h), les faux rappels notaient 2,4–4,8 et le plus faible vrai 9,3.
    "recall": {"enabled": True, "max_items": 3, "min_cov": 0.5, "min_score": 5.0, "files": True, "max_files": 4,
               "min_cov_files": 0.4, "max_chars": 1200, "session_cap_items": 12, "session_cap_files": 20,
               # Neurone du rappel (neurone.py), appris sur les échanges de cet utilisateur : « auto » (il prend la
               # main une fois assez d'exemples et s'il fait mieux que la règle), « off » (la règle seule). Ligne
               # complète si sa probabilité d'être utile atteint neurone_haut ; sinon titre seul pour ce que la règle
               # accepte (à partir de neurone_bas ; 0 : il ne cache jamais ce que la règle aurait montré).
               "neurone": "auto", "neurone_haut": 0.6, "neurone_bas": 0.0},
    # prompts.chat (bibliothèque ouverte de prompts/skills) : sur une demande de prompt, de skill, de rôle ou de contenu
    # à créer, 0 à max_items modèles proches injectés, filtrés sur le titre ; au plus max_calls recherches (≈ 0,3 s,
    # cache 7 jours), coupé net au-delà de timeout s ou si le site limite le débit. `brain prompts` à la main.
    "promptlib": {"auto": True, "max_items": 2, "max_calls": 3, "timeout": 2.5, "session_cap": 6},
    # Réflexes de skills : souffler la skill perso qui colle au message (une fois par session et par skill) ; une
    # méthode ou un prompt collé → proposer (« propose ») ou faire tout de suite (« auto ») une skill ; « off » : rien.
    "skills": {"enabled": True, "max_items": 1, "min_score": 4.0, "session_cap": 6, "exclude": ["brain"],
               "paste": "propose", "paste_min_chars": 500},
    # Rappel en fin de tâche : « mémorise ce qui est durable » (une fois, seulement si la session a travaillé).
    "stop_reminder": {"enabled": True, "min_tool_calls": 15, "min_edits": 3, "repeat_after": 150},
    # Mode éco (`brain eco`) : réglages officiels de Claude Code posés une fois dans ~/.claude/settings.json (sorties de
    # commandes longues mises en fichier, conversation résumée plus tôt, liste des skills réduite, mémoire auto de Claude
    # Code coupée une fois importée dans le cerveau) ; alerte à l'utilisateur quand la conversation passe ces tailles
    # (tokens), ou quand il reprend après une pause qui a vidé le cache (`alerte_pause`) : chaque message la relit en
    # entier. `eco.auto` false = ne rien poser tout seul. `cache` : durée du cache de prompt — "auto" (simulée une fois par
    # jour sur les pauses réelles, posée seulement au-delà de 5 % de gain), "5m", "1h" ou "off" (ne jamais y toucher).
    # `plugins_auto` (à activer : `brain eco --plugins-auto`) : veille quotidienne, en arrière-plan, qui désactive les plugins
    # sans usage depuis 30 jours et coupe les skills claude.ai si aucune n'a servi.
    "eco": {"auto": True, "bash_output_max_chars": 10000, "auto_compact_window": 200000,
            "alerte_contexte": [150000, 300000], "alerte_pause": True, "cache": "auto", "plugins_auto": False},
    # Cartographie automatique (en arrière-plan) des dossiers de projet.
    "auto_map": {"enabled": True, "refresh_minutes": 10},
    "map": {"max_files": 15000, "max_file_kb": 768},
    # Journal des sessions. `rattrapage_le` : dernier contrôle quotidien (au démarrage) des sessions de Claude Code des 7
    # derniers jours absentes du journal (hooks muets) ; elles sont alors importées en arrière-plan.
    "journal": {"enabled": True, "keep": 500, "rattrapage_le": None},
    # Sauvegarde quotidienne hors du disque système (dossier auto : D:\\Sauvegardes-cerveau-Claude, sinon E:…).
    "backup": {"enabled": True, "dir": None, "keep": 14},
    # Échéances : les à-faire datés apparaissent au démarrage quand ils approchent (ou sont en retard).
    "due": {"days_ahead": 7},
    # Coffre Obsidian (`export --vault <dossier>`) : dossier retenu après le premier export.
    "vault": {"path": None},
    # Le cerveau en wiki (`brain wiki init <dossier>`) : les pages Markdown du dossier font foi. Synchronisation git
    # automatique sur le PC (pull au démarrage au plus toutes les sync_minutes, commit + push en fin de session).
    "wiki": {"path": None, "auto_sync": True, "sync_minutes": 30},
    # Rêve : entretien quotidien hors conversation ; ligne au démarrage s'il y a au moins min_items points à trancher.
    "dream": {"notice": True, "min_items": 3},
    # PC (`brain pc`) : veille légère pendant les hooks (au plus toutes les check_minutes), fermeture seule des orphelins
    # sûrs (serveurs MCP et sessions Claude dont le parent est mort depuis orphan_min_minutes), une ligne pour Claude
    # seulement si la RAM est critique ou si une session tourne à vide (au plus toutes les alert_repeat_minutes).
    "pc": {"enabled": True, "check_minutes": 10, "auto_clean": True, "orphan_min_minutes": 10,
           "orphan_patterns": ["mcp", "\\claude\\", "\\.claude\\plugins", "claude_pzs8sxrjxfjjc", "npm-cache\\_npx"],
           "idle_hours": 3, "spin_cores": 0.5, "ram_alert_gb": 2.5, "ram_alert_pct": 92, "alert_repeat_minutes": 60,
           "history_days": 14},
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
    for attempt in range(8):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return default
        except PermissionError as exc:  # Windows : fichier en cours de remplacement par une tâche de fond
            if attempt == 7:
                log(f"read_json {path}: {exc!r}")
                return default
            time.sleep(0.05 * (attempt + 1))
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


def remove_tree(path, wait=0.0) -> bool:
    """Efface un dossier pour de bon, sous Windows aussi : fichiers en lecture seule (objets git) rendus inscriptibles,
    sortie du dossier s'il contient le dossier courant du processus, et nouveaux essais pendant `wait` secondes tant
    qu'un autre processus le tient (tâche de fond qui y travaille encore, antivirus). → True si le dossier n'existe plus."""
    import shutil
    import stat

    def force(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass  # encore ouvert ailleurs : repris au tour suivant

    path = Path(os.path.abspath(path))  # absolu (sinon « . » viserait le parent après os.chdir) ; un lien n'est pas suivi
    try:  # Windows : le dossier courant d'un processus ne s'efface pas
        if Path.cwd().resolve().is_relative_to(path.resolve()):
            os.chdir(path.parent)
    except OSError:
        pass
    end = time.time() + wait
    kw = {"onexc": force} if sys.version_info >= (3, 12) else {"onerror": force}
    while path.exists():
        shutil.rmtree(path, **kw)
        if not path.exists() or time.time() >= end:
            break
        time.sleep(0.5)
    return not path.exists()


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

    def __init__(self, path, timeout=5.0, stale=30.0, strict=True):
        self.path = str(path)
        self.timeout = timeout
        self.stale = stale
        self.strict = strict  # False : passé le délai, on continue sans le verrou au lieu d'échouer
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
                    if not self.strict:
                        log(f"verrou occupé, on continue sans : {self.path}")
                        return self
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


def update_config(change) -> dict:
    """Relit la configuration écrite (sans les défauts), la passe à `change` qui la modifie sur place, et la réécrit — le
    tout sous verrou : deux tâches de fond (plugins, cache…) qui l'écrivent en même temps ne s'écrasent plus. Jamais
    bloquant : passé 3 s, l'écriture se fait sans le verrou."""
    with FileLock(str(CONFIG_FILE) + ".lock", timeout=3.0, stale=10.0, strict=False):
        cfg = read_json(CONFIG_FILE, {}) or {}
        change(cfg)
        write_json(CONFIG_FILE, cfg)
    return load_config()


def set_config(dotted: str, value) -> dict:
    def change(cfg):
        cur = cfg
        keys = dotted.split(".")
        for key in keys[:-1]:
            cur = cur.setdefault(key, {})
        cur[keys[-1]] = value
    return update_config(change)


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


_LABEL_SPACE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_LABEL_DROP = re.compile("[\u00ad\u061c\u180e\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]")


def clean_label(text) -> str:
    """Titre sûr (façon graphify sanitize_label) : caractères de contrôle → espace ; invisibles et caractères de
    direction (qui retournent l'affichage) retirés ; espaces resserrés. Garde les liants d'emoji (ZWJ/ZWNJ)."""
    s = _LABEL_DROP.sub("", _LABEL_SPACE.sub(" ", str(text or "")))
    return " ".join(s.split())


def est_tokens(text) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN)


def budget_chars(section: dict, key: str) -> int:
    """Budget en caractères d'une clé `<nom>_tokens` ; l'ancienne clé `<nom>_chars` gagne si l'utilisateur l'a fixée."""
    legacy = key.replace("_tokens", "_chars")
    if isinstance(section.get(legacy), (int, float)):
        return int(section[legacy])
    return int(section.get(key, 0) * CHARS_PER_TOKEN)


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
