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
HOOK = None  # événement du hook en cours (posé par hooks._run) : le travail lourd n'y attend jamais, il part en arrière-plan
# Commande de lecture rapide (`brain q`, serveur MCP) : comme dans un hook, l'analyse du graphe en cache sert même
# périmée et la tâche de fond des vues la refait (1 à 4 s de calcul évitées juste après une écriture).
LAZY = False

# Mesuré le 16/10/2026 sur 427 paires de requêtes réelles (contexte n+1 − contexte n autour d'un seul gros résultat
# d'outil) : 2,06 car./token en médiane ; Markdown FR 2,23, Python 2,27, sorties Bash 2,01. L'ancien 3,7 sous-estimait ×1,7.
CHARS_PER_TOKEN = 2.2

DEFAULT_CONFIG = {
    # Budgets de ce qui est injecté, en tokens (relus à chaque requête jusqu'à la compaction) : total au démarrage,
    # index hors projet / dans un projet, fiche du projet, résumé de carte, ajout après compaction, nouveautés à la reprise.
    # Les anciennes clés en caractères (max_chars, index_chars…) restent prioritaires si elles sont dans config.json.
    "inject": {"max_tokens": 2600, "index_tokens": 1650, "index_tokens_project": 1150, "project_tokens": 1100,
               "digest_tokens": 330, "compact_recall_tokens": 450, "resume_items": 5},
    # Rappel automatique à chaque message : souvenirs + fichiers pertinents, seulement si vraiment liés.
    # min_score 5 : sur 27 vrais messages (72 h), les faux rappels notaient 2,4–4,8 et le plus faible vrai 9,3.
    # Plafond glissant : au plus session_cap_items souvenirs sur les session_cap_window derniers messages, puis une ligne
    # le dit et le rappel reprend quand les plus anciens sortent de la fenêtre (« tu te souviens… » passe toujours).
    "recall": {"enabled": True, "max_items": 3, "min_cov": 0.5, "min_score": 5.0, "files": True, "max_files": 4,
               "min_cov_files": 0.4, "max_chars": 1200, "session_cap_items": 12, "session_cap_window": 20,
               "session_cap_files": 20,
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
    # `plugins` : lire aussi les skills des plugins actifs (True, liste de noms de plugins, ou False) ; `triggers` :
    # déclencheurs ajoutés, {« plugin:skill » ou nom : [phrases]} (`brain skill trig`) ; `exclude` : jamais soufflées.
    # `auto` : skills chargées d'office (contenu injecté par le hook dès qu'un déclencheur est reconnu, sans outil Skill).
    "skills": {"enabled": True, "max_items": 1, "min_score": 4.0, "session_cap": 6, "exclude": ["brain"],
               "paste": "propose", "paste_min_chars": 500, "plugins": True, "triggers": {}, "auto": []},
    # Réflexe des connecteurs (Gmail, Agenda, Shopify…) : ligne 🔌 avec le ToolSearch exact, une fois par session et par
    # connecteur ; `triggers` : {« id » ou clé de serveur : [phrases]} (`brain outils trig`) ; `fresh_days` : au-delà,
    # un serveur pas revu n'est plus proposé ; `veille` : nouveaux serveurs et skills sans déclencheur signalés au démarrage.
    "outils": {"enabled": True, "max_items": 2, "session_cap": 6, "fresh_days": 21, "veille": True, "triggers": {}},
    # Rappel en fin de tâche : « mémorise ce qui est durable », seulement si l'utilisateur a dit une phrase durable pas encore enregistrée.
    "stop_reminder": {"enabled": True},
    # Mode éco (`brain eco`) : réglages officiels de Claude Code posés une fois dans ~/.claude/settings.json (sorties de
    # commandes longues mises en fichier, conversation résumée plus tôt, liste des skills réduite, mémoire auto de Claude
    # Code coupée une fois importée dans le cerveau) ; alerte à l'utilisateur quand la conversation passe ces tailles
    # (tokens), ou quand il reprend après une pause qui a vidé le cache (`alerte_pause`) : chaque message la relit en
    # entier. `eco.auto` false = ne rien poser tout seul. `cache` : durée du cache de prompt — "auto" (simulée une fois par
    # jour sur les pauses réelles, posée seulement au-delà de 5 % de gain), "5m", "1h" ou "off" (ne jamais y toucher).
    # `plugins_auto` (à activer : `brain eco --plugins-auto`) : veille quotidienne, en arrière-plan, qui PROPOSE (une
    # annonce, une fois) de désactiver les plugins sans usage depuis 30 jours et les skills claude.ai si aucune n'a servi ;
    # rien n'est désactivé sans `brain eco --plugins`.
    "eco": {"auto": True, "bash_output_max_chars": 10000, "auto_compact_window": 200000,
            "alerte_contexte": [150000, 300000], "alerte_pause": True, "cache": "auto", "plugins_auto": False},
    # Style de réponse par défaut (outputStyle de Claude Code, terminal et app de bureau), posé une fois avec le mode éco
    # quand le plugin le livre, jamais à la place d'un style choisi par l'utilisateur. "off" : ne rien poser (et retirer
    # celui que le cerveau avait posé : `brain config style off`).
    "style": "cerveau:concis",
    # Sorties compactes (`brainkit/compact.py`) : après une commande bavarde (installation, tests, build, git log…), Claude
    # ne lit que l'essentiel ; la sortie brute reste keep_days jours dans state/sorties/. Rien n'est touché sous min_chars
    # caractères ni si le gain est sous min_gain (part) ou min_saved (caractères). `echantillons` : les sorties des
    # commandes non reconnues sont gardées aussi (sans secret) ; l'entretien du jour y repère le bruit qui revient et en
    # fait un filtre (`apprendre_auto`), annoncé une fois ; `brain compact --oublier "<commande>"` le retire pour de bon.
    "compact": {"enabled": True, "min_chars": 1500, "min_gain": 0.3, "min_saved": 600, "keep_days": 3, "max_files": 40,
                "echantillons": True, "apprendre_auto": True},
    # Serveur MCP (`brain mcp` : Claude Code par le plugin, l'app Claude, Cowork…) : chaque client relit la liste des
    # outils à chaque requête. Par défaut, les 6 outils de la mémoire seulement (décision du 21/11) ; `groupes` en ajoute
    # d'autres : "wiki" (wiki_status, wiki_add_source, wiki_lint, wiki_log), "boutique" (boutique_etat, _ajouter, _plan,
    # _kpi, _audit), ou "tout" — `brain config mcp.groupes '["wiki", "boutique"]'`. `max_car` : un résultat plus long est
    # coupé en pages (la fin dit comment demander la suite, `page: 2`).
    "mcp": {"groupes": [], "max_car": 8000},
    # Cartographie automatique (en arrière-plan) des dossiers de projet.
    "auto_map": {"enabled": True, "refresh_minutes": 10},
    "map": {"max_files": 15000, "max_file_kb": 768},
    # Journal des sessions. `rattrapage_le` : dernier contrôle quotidien (au démarrage) des sessions de Claude Code des 7
    # derniers jours absentes du journal (hooks muets) ; elles sont alors importées en arrière-plan.
    "journal": {"enabled": True, "keep": 500, "rattrapage_le": None},
    # Sauvegarde quotidienne hors de ~/.claude. Dossier auto (dir vide) : sous Windows le premier autre disque
    # (D:\\Sauvegardes-cerveau-Claude, sinon E:…), sinon ~/Sauvegardes-cerveau-Claude, annoncé une fois (décision E7).
    "backup": {"enabled": True, "dir": None, "keep": 14},
    # Échéances : les à-faire datés apparaissent au démarrage quand ils approchent (ou sont en retard).
    "due": {"days_ahead": 7},
    # Coffre Obsidian (`export --vault <dossier>`) : dossier retenu après le premier export.
    "vault": {"path": None},
    # Le cerveau en wiki (`brain wiki init <dossier>`) : les pages Markdown du dossier font foi. Synchronisation git
    # automatique sur le PC (pull au démarrage au plus toutes les sync_minutes, commit + push en fin de session).
    "wiki": {"path": None, "auto_sync": True, "sync_minutes": 30},
    # Rêve : entretien quotidien hors conversation ; ligne au démarrage s'il y a au moins min_items points à trancher ou
    # une source du wiki à ingérer. `auto` : Claude le traite lui-même (sources ingérées, partie sûre appliquée, doutes
    # laissés et cités) ; false : la ligne le propose seulement.
    "dream": {"notice": True, "min_items": 3, "auto": True},
    # PC (`brain pc`) : veille légère pendant les hooks (au plus toutes les check_minutes). Elle ne ferme jamais rien :
    # `auto_clean` = lister seul les serveurs MCP orphelins (parent mort depuis orphan_min_minutes) et les proposer en une
    # ligne ; les fermer exige `brain pc --clean --oui`. Une ligne pour Claude aussi si la RAM est critique ou si une
    # session tourne à vide (au plus toutes les alert_repeat_minutes).
    "pc": {"enabled": True, "check_minutes": 10, "auto_clean": True, "orphan_min_minutes": 10,
           "orphan_patterns": ["\\claude\\", "\\.claude\\plugins", "claude_pzs8sxrjxfjjc", "npm-cache\\_npx"],
           "idle_hours": 3, "spin_cores": 0.5, "ram_alert_gb": 2.5, "ram_alert_pct": 92, "alert_repeat_minutes": 60,
           "history_days": 14},
    # Délégation (`brain delegation`, brainkit/delegation.py) : chaque tâche au modèle le moins cher qui suffit, dans un
    # contexte à part. `mode` : "auto" (un sous-agent lancé sans modèle part sur Haiku pour chercher, lire, résumer, sur
    # Sonnet pour une modification mécanique ; conception, débogage et décisions jamais touchés), "max" (tout
    # sous-agent générique au moins sur Sonnet), "conseil" (consigne et conseils seulement), "off". `modeles` :
    # {agent du cerveau: alias} ou {"Explore" | "general-purpose": alias | "off"}. `reflexe` : la ligne ↪ par message
    # (au plus `session_cap` par session). `reve` : le rêve est confié à l'agent archiviste.
    "delegation": {"mode": "auto", "modeles": {}, "reflexe": True, "session_cap": 2, "reve": True},
    # Apprentissage (`brain apprendre`, brainkit/apprendre.py) : erreurs résolues, déclencheurs manqués, méthodes
    # répétées, retours techniques — détectés sans token. `declencheurs_auto` : une tournure commune à deux messages qui
    # ont chargé la même skill devient un déclencheur (annoncé, retirable). `notice` : la ligne 🎓 du démarrage, à
    # partir de `min_items` points au dossier (au plus une fois par jour).
    "apprendre": {"enabled": True, "declencheurs_auto": True, "notice": True, "min_items": 3},
    # Échange de skills entre membres du cerveau commun (`brain echange`, brainkit/echange.py). `envoi` : None tant que
    # l'utilisateur n'a pas répondu, puis "oui" ou "non" (rien ne part sans son oui). `reception` : le texte des skills
    # des amis est proposé quand un message colle ("non" : jamais) ; un script attend toujours un accord (`scripts` :
    # empreintes approuvées). `partager` / `garder` : skills écrites à la main à envoyer / skills à ne jamais envoyer.
    "echange": {"envoi": None, "reception": "oui", "declencheurs": "oui", "partager": [], "garder": [], "proposees": [],
                "scripts": {}, "acceptees": {}},
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


def write_bytes(path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# Messages pour l'utilisateur, dits une fois au démarrage suivant (0 token) : réparation du graphe, dossier choisi
# pour les sauvegardes… Un fichier par sujet dans state/a-dire/ ; le hook du démarrage les lit puis les retire.
NOTICES_DIR = STATE_DIR / "a-dire"


def tell_user(key: str, line: str) -> None:
    try:
        write_text(NOTICES_DIR / f"{slugify(key, 40) or 'message'}.txt", line)
    except OSError as exc:
        log(f"message pour l'utilisateur ({key}) : {exc!r}")


def take_notices() -> list:
    """Messages en attente (les plus anciens d'abord), retirés une fois lus. Rien à lire : quelques µs."""
    try:
        items = sorted(os.scandir(NOTICES_DIR), key=lambda e: e.stat().st_mtime_ns)
    except OSError:
        return []
    out = []
    for e in items:
        if not e.name.endswith(".txt"):
            continue
        try:
            text = Path(e.path).read_text(encoding="utf-8", errors="replace").strip()
            os.remove(e.path)
        except OSError:
            continue
        if text:
            out.append(text)
    return out


def remove_tree(path, wait=0.0) -> bool:
    """Efface un dossier pour de bon, sous Windows aussi : fichiers en lecture seule (objets git) rendus inscriptibles,
    sortie du dossier s'il contient le dossier courant du processus, et nouveaux essais pendant `wait` secondes tant
    qu'un autre processus le tient (tâche de fond qui y travaille encore, antivirus). → True si le dossier n'existe plus."""
    import shutil
    import stat

    def force(func, p, _exc):
        """Droits ajoutés, jamais retirés : chmod(S_IWRITE) seul rendait un dossier illisible hors Windows (0o200), et
        Python 3.10 rappelait alors os.open sans ses arguments. Seule une suppression est refaite ici ; une lecture du
        dossier (os.open, os.scandir, os.lstat) l'est au tour suivant."""
        def allow(q):
            mode = os.lstat(q).st_mode
            extra = stat.S_IWRITE | (stat.S_IREAD | stat.S_IEXEC if stat.S_ISDIR(mode) else 0)
            os.chmod(q, stat.S_IMODE(mode) | extra)

        try:
            allow(p)
            if func in (os.unlink, os.remove, os.rmdir):
                allow(os.path.dirname(p))  # hors Windows, effacer une entrée demande d'écrire dans son dossier
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


class LockBusy(TimeoutError):
    """Verrou tenu par une autre session (FileLock) : un TimeoutError, comme avant, mais qu'on distingue d'un délai
    réseau dépassé (urllib, socket : TimeoutError eux aussi)."""


# errno → français (messages d'erreur des commandes : « No such file or directory » ne dit rien à l'utilisateur)
_ERRNO_FR = {2: "introuvable", 13: "accès refusé", 1: "opération refusée", 28: "disque plein", 30: "disque en lecture seule",
             17: "existe déjà", 20: "n'est pas un dossier", 21: "est un dossier", 16: "fichier occupé",
             39: "dossier non vide", 36: "nom trop long", 122: "quota du disque atteint", 5: "erreur de lecture du disque"}


def oserror_fr(exc) -> str:
    """OSError → « <chemin> : <raison en français> » (Windows : winerror 32, fichier ouvert ailleurs)."""
    why = _ERRNO_FR.get(getattr(exc, "errno", None) or 0)
    if getattr(exc, "winerror", None) == 32:
        why = "fichier ouvert par un autre programme"
    why = why or (exc.strerror if getattr(exc, "strerror", None) else str(exc))
    where = getattr(exc, "filename", None)
    return f"{where} : {why}" if where else why


def network_reason(exc) -> str:
    """Erreur réseau (urllib, socket) → la raison en français ; "" pour une autre erreur d'entrée-sortie. Avant, une
    connexion refusée se lisait « accès impossible à un fichier du cerveau » ou « <urlopen error [Errno 111]> »."""
    import socket
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        return f"le site répond {exc.code}" + (" (accès refusé)" if exc.code in (401, 403) else " (introuvable)"
                                               if exc.code == 404 else " (trop de demandes, attends un peu)"
                                               if exc.code == 429 else "")
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)):
        return "connexion refusée ou coupée"
    if isinstance(reason, socket.gaierror):
        return "adresse introuvable (pas de réseau, ou DNS)"
    if isinstance(reason, (socket.timeout, TimeoutError)) and not isinstance(reason, LockBusy):
        return "délai dépassé"
    if isinstance(exc, (urllib.error.URLError, ConnectionError)):
        return short(str(reason), 120)
    return ""


class FileLock:
    """Verrou inter-processus minimal (création exclusive d'un fichier), reprise des verrous périmés.

    Tant qu'il tient le verrou, le détenteur en rafraîchit la date (un fil en arrière-plan, toutes les `stale`/3 s) :
    seul le verrou d'un processus mort devient périmé. Avant, un travail plus long que `stale` (consolidation, import,
    carte d'un gros projet) se faisait reprendre le verrou par un autre processus, et l'un des deux écrasait l'écriture
    de l'autre : un souvenir annoncé « mémorisé » disparaissait."""

    def __init__(self, path, timeout=5.0, stale=30.0, strict=True):
        self.path = str(path)
        self.timeout = timeout
        self.stale = stale
        self.strict = strict  # False : passé le délai, on continue sans le verrou au lieu d'échouer
        self.held = False
        self._stop = None

    def _keep_fresh(self):
        import threading
        stop = threading.Event()
        period = max(0.1, self.stale / 3)

        def beat():
            while not stop.wait(period):
                try:
                    os.utime(self.path)
                except OSError:
                    return

        threading.Thread(target=beat, name="brain-lock", daemon=True).start()
        self._stop = stop

    def __enter__(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                self._keep_fresh()
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
                    raise LockBusy(f"verrou occupé : {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self._stop is not None:
            self._stop.set()
            self._stop = None
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


# Bornes des réglages numériques [min, max] (None : pas de borne) ; les autres nombres vont de 0 à l'infini. Une valeur
# hors bornes dans config.json est remplacée par le défaut, comme une valeur du mauvais type (CONFIG_ISSUES).
CONFIG_RANGES = {"recall.min_cov": (0, 1), "recall.min_cov_files": (0, 1), "recall.neurone_haut": (0, 1),
                 "recall.neurone_bas": (0, 1), "compact.min_gain": (0, 1), "pc.ram_alert_pct": (0, 100),
                 "promptlib.timeout": (0.1, 60), "eco.bash_output_max_chars": (4000, 128000),
                 "eco.auto_compact_window": (100000, 1000000), "mcp.max_car": (1000, None), "map.max_files": (1, None),
                 "map.max_file_kb": (1, None), "backup.keep": (1, None), "journal.keep": (1, None),
                 "auto_map.refresh_minutes": (1, None)}
# Réglages qui prennent plusieurs formes : skills.plugins (oui/non, ou la liste des plugins lus), style (texte, ou
# false pour aucun), mcp.groupes (liste, ou texte « wiki,boutique » que mcp_server découpe).
CONFIG_FORMS = {"skills.plugins": (bool, list), "style": (str, bool, type(None)), "mcp.groupes": (list, str)}
CONFIG_ISSUES = []  # réglages faux de config.json remplacés par leur défaut à la dernière lecture : [(clé, valeur, attendu)]
_BOOL_WORDS = {"true": True, "false": False, "oui": True, "non": False, "on": True, "off": False, "1": True, "0": False,
               "vrai": True, "faux": False, "yes": True, "no": False}


def config_kind(key, default) -> str:
    """Type attendu d'un réglage, en clair (messages) : d'après sa valeur par défaut."""
    if key in CONFIG_FORMS:
        return {"skills.plugins": "oui/non (true, false) ou liste de plugins", "style": "texte (nom du style) ou off",
                "mcp.groupes": "liste de groupes"}[key]
    if isinstance(default, bool):
        return "oui/non (true ou false)"
    if isinstance(default, int) and not key.endswith(("_minutes", "_hours", "_days")) and key != "due.days_ahead":
        return "nombre entier"
    if isinstance(default, (int, float)):
        return "nombre"
    if isinstance(default, str):
        return "texte"
    if isinstance(default, list):
        return "liste"
    if isinstance(default, dict):
        return "objet JSON"
    return "texte ou null"


def config_value(key, default, val):
    """(valeur ramenée au type du défaut, None) si `val` convient au réglage `key`, sinon (None, type attendu). Rien
    de lourd : chaque lecture de la configuration (chaque hook) passe les valeurs écrites par là."""
    if key in CONFIG_FORMS:
        return (val, None) if isinstance(val, CONFIG_FORMS[key]) else (None, config_kind(key, default))
    if default is None:  # chemin, date ou choix encore vide : texte ou null
        return (val, None) if val is None or isinstance(val, str) else (None, "texte ou null")
    if isinstance(default, bool):
        if isinstance(val, bool):
            return val, None
        if isinstance(val, int) and val in (0, 1):
            return bool(val), None
        if isinstance(val, str) and val.strip().lower() in _BOOL_WORDS:
            return _BOOL_WORDS[val.strip().lower()], None
        return None, config_kind(key, default)
    if isinstance(default, (int, float)):
        if isinstance(val, str):
            try:
                val = float(val.strip().replace(",", "."))
            except ValueError:
                return None, config_kind(key, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val != val or val in (float("inf"), float("-inf")):
            return None, config_kind(key, default)
        lo, hi = CONFIG_RANGES.get(key, (0, None))
        if (lo is not None and val < lo) or (hi is not None and val > hi):
            return None, f"{config_kind(key, default)} de {lo} à {hi}" if hi is not None else \
                f"{config_kind(key, default)} d'au moins {lo}"
        if config_kind(key, default) == "nombre entier":
            if val != int(val):
                return None, "nombre entier"
            val = int(val)
        return val, None
    if isinstance(default, str):
        return (val, None) if isinstance(val, str) else (None, "texte")
    if isinstance(default, list):
        if isinstance(val, str):
            val = [val]
        if not isinstance(val, list):
            return None, "liste"
        if default and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in default) \
                and not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in val):
            return None, "liste de nombres"
        return val, None
    if isinstance(default, dict):
        return (val, None) if isinstance(val, dict) else (None, "objet JSON")
    return val, None


def _sane(defaults, over, prefix, issues):
    """Valeurs écrites dans config.json qui ne conviennent pas à leur réglage (« abc » pour un nombre, texte pour une
    section…) : retirées de `over` (lu à l'instant, donc à nous), le défaut les remplace. Les clés hors des défauts
    (état tenu par le cerveau, sections libres comme skills.triggers) ne sont pas regardées."""
    for key in list(over):
        if key not in defaults:
            continue
        dflt, val, path = defaults[key], over[key], prefix + key
        if isinstance(dflt, dict) and dflt and path not in CONFIG_FORMS:
            if isinstance(val, dict):
                _sane(dflt, val, path + ".", issues)
            else:
                issues.append((path, val, "objet JSON"))
                del over[key]
            continue
        good, want = config_value(path, dflt, val)
        if want:
            issues.append((path, val, want))
            del over[key]
        elif good is not val:
            over[key] = good


def load_config() -> dict:
    over = read_json(CONFIG_FILE, {}) or {}
    issues = []
    if not isinstance(over, dict):  # liste, texte… : rien d'utilisable, les défauts partout
        issues.append(("(fichier)", over, "objet JSON"))
        over = {}
    _sane(DEFAULT_CONFIG, over, "", issues)
    CONFIG_ISSUES[:] = issues
    return _merge(DEFAULT_CONFIG, over)


def config_issues_line() -> str:
    """Réglages faux remplacés par leur défaut, en une ligne pour l'utilisateur ("" s'il n'y en a pas)."""
    if not CONFIG_ISSUES:
        return ""
    bits = []
    for key, val, want in CONFIG_ISSUES[:4]:
        shown = json.dumps(val, ensure_ascii=False)
        bits.append(f"{key} = {shown[:40] + '…' if len(shown) > 40 else shown} ({want} attendu)")
    more = f" (+{len(CONFIG_ISSUES) - 4})" if len(CONFIG_ISSUES) > 4 else ""
    first = CONFIG_ISSUES[0][0]
    fix = "`brain config` pour voir" if first == "(fichier)" else f"corriger : `brain config {first} <valeur>`"
    return (f"⚠ Cerveau : réglage ignoré dans {CONFIG_FILE.name}, valeur par défaut utilisée — " + " · ".join(bits)
            + f"{more} ; {fix}")


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
            if not isinstance(cur.get(key), dict):  # section abîmée (texte, liste…), déjà ignorée à la lecture : refaite
                cur[key] = {}
            cur = cur[key]
        cur[keys[-1]] = value
    return update_config(change)

def commun_member(cfg=None) -> bool:
    """Membre du cerveau commun, d'après la configuration seule : faux, rien à charger à chaque hook (ni commun.py, ni
    git, ni hashlib) ; vrai, commun.member() fait le contrôle complet (dossier du dépôt, session cloud)."""
    c = (load_config() if cfg is None else cfg).get("commun")
    return isinstance(c, dict) and c.get("etat") == "membre" and bool(c.get("nom"))


def owner_name() -> str:
    """Prénom de l'utilisateur, réglage local (publish.owner) jamais publié : le wiki s'adresse à lui ; le graphe et
    l'index des skills ne le prennent pas pour un sujet. Vide s'il n'est pas réglé."""
    return str((load_config().get("publish") or {}).get("owner") or "").strip()


def sujets() -> list:
    """Mots du domaine de l'utilisateur, réglage local (« sujets ») jamais publié : ils s'ajoutent aux sujets connus du
    graphe et aux termes de la bibliothèque de prompts. Le code publié n'en contient aucun."""
    vals = load_config().get("sujets") or []
    vals = vals if isinstance(vals, (list, tuple)) else [vals]
    return [str(w).strip() for w in vals if str(w).strip()]


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
parfait parfaite super genial top nickel cool excellent impeccable continue continuer go bravo réessayer réessaie
combien fois font quel quels lequel laquelle lesquels lesquelles autre autres beaucoup trop tant
entre contre selon parmi malgré durant"""
_STOP_EN = """about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing done down during each few for from further had has have
having he her here hers him his how i if in into is it its itself just me more most my no nor not now of
off on once only or other our ours out over own same she should so some such than that the their theirs
them then there these they this those through to too under until up very was we were what when where
which while who whom why will with would you your yours please make get let retry"""
STOPWORDS = {fold(w) for w in (_STOP_FR + " " + _STOP_EN).split()}

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN = re.compile(r"[a-z0-9]+")


def stem(tok: str) -> str:
    """Pluriel neutralisé : un « s » final retiré (« commandes » → « commande »), sauf après u, i, a, où il fait
    souvent partie du mot (« refus », « préavis », « Paris », « frais », « colis ») : « refu » ne retrouvait plus
    « refusé ». Le pluriel de ces mots-là (« envois », « bleus ») retrouve son singulier par le préfixe."""
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith(("ss", "us", "is", "as")):
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
    inter = len(a & b)  # |a ∪ b| = |a| + |b| - |a ∩ b| : même valeur, sans construire l'union
    return inter / (len(a) + len(b) - inter)


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
