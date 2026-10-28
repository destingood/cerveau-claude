"""Sorties de commandes compactes — idées de RTK, quiet-shell-mcp et token-saver (crédits d'OmniRoute, 28/10/2026).

Après une commande bavarde (installation, tests, build, `git log`, clone…), le hook PostToolUse du cerveau remplace la
sortie que Claude lit par l'essentiel : erreurs et avertissements (les répétitions regroupées), résumé de fin. La
commande a tourné telle quelle (rien n'est réécrit : permissions, `cd` et code de sortie intacts) et la sortie brute
reste dans un fichier (`state/sorties/`, gardé `keep_days` jours) dont le chemin termine la sortie compactée. Rien
n'est touché si la sortie est courte ou si le gain est faible ; une commande en échec (PostToolUseFailure) garde sa
sortie entière. `brain compact` pour l'essayer à la main ; `config compact.enabled false` pour le couper.

v8.14 (idées de rtk_discover / rtk_learn, des règles JSON de RTK et de Headroom, crédits d'OmniRoute) : filtres perso
(`compact.filtres` : `{"cmd": motif, "drop": [motifs]}`, proposés par `brain compact --decouvrir` / `--apprendre`),
liste JSON d'objets → tableau en-tête + lignes sans perte, et une sortie identique à une précédente de la session
devient un renvoi vers sa sortie brute (oublié à la compaction).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from .common import STATE_DIR, load_config, log, read_json, read_stdin_json, write_json

OUT_DIR = STATE_DIR / "sorties"
STATS_FILE = STATE_DIR / "compact.json"
SEEN_FILE = STATE_DIR / "compact-vus.json"  # empreintes des longues sorties déjà lues, par session

# Familles de commandes bavardes, reconnues sur le début de chaque commande simple d'une ligne (`cd x && npm i`).
_FAMILIES = [
    ("git-log", r"git\s+(?:-C\s+\S+\s+)?log\b"),
    ("git-net", r"git\s+(?:-C\s+\S+\s+)?(?:clone|fetch|pull|push)\b"),
    ("install", r"(?:npm|pnpm)\s+(?:install|i|ci|add|update|up)\b|yarn\s*$|yarn\s+(?:install|add)\b"
                r"|bun\s+(?:install|i|add)\b|(?:pip3?|(?:python3?|py)\s+-m\s+pip|uv\s+pip)\s+install\b|uv\s+(?:sync|add)\b"
                r"|poetry\s+(?:install|add|update)\b|composer\s+(?:install|require|update)\b|bundle\s+install\b"
                r"|go\s+(?:mod\s+download|get)\b|cargo\s+fetch\b|dotnet\s+restore\b|(?:brew|gem|conda)\s+install\b"),
    ("test", r"(?:(?:python3?|py)\s+-m\s+)?(?:pytest|unittest)\b|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|npm\s+t\b"
             r"|(?:(?:npx|pnpx|bunx)\s+)?(?:jest|vitest|mocha)\b|(?:cargo|go|dotnet)\s+test\b|mvn\s+(?:\S+\s+)*test\b"
             r"|(?:\./)?gradlew?\s+test\b|rspec\b|phpunit\b"),
    ("build", r"(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?build\b|cargo\s+(?:build|check|clippy)\b|(?:go|dotnet)\s+build\b"
              r"|mvn\s+\S|(?:\./)?gradlew?\s+\S|make\b|(?:(?:npx|pnpx|bunx)\s+)?(?:tsc|next\s+build|vite\s+build)\b"
              r"|docker\s+(?:build|pull|compose\s+(?:build|pull|up))\b"),
]
_FAMILY_RX = [(name, re.compile(rx)) for name, rx in _FAMILIES]
_SPLIT = re.compile(r"&&|\|\||[;|\n]")
_PREFIX = re.compile(r"^\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|sudo|time|command|env)\s+)*")
# git log déjà choisi précis (patchs, fichiers, format perso) : le contenu compte, on n'y touche pas
_GIT_LOG_KEEP = re.compile(r"\s(?:-p|-u|--patch|--stat|--numstat|--name-only|--name-status|--format|--pretty)\b")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]")
_BAR = re.compile(r"^[\s\[\]()#=>\-.|/\\:*_~⠀-⣿█▉▊▋▌▍▎▏░▒▓━─╸╺·•%0-9KMGkmgBbs]*$")  # barres de progression, compteurs
_IMPORTANT = re.compile(
    r"(?i)\b(?:error|errors|erreur|err!|fail|failed|failure|failures|fatal|panic|exception|traceback|denied|refused"
    r"|cannot|can't|could not|couldn't|unable|not found|no such|missing|conflict|vulnerabilit|warn|warning"
    r"|deprecat|abort|timed? ?out)\b|^\s*E\s{2,}|^\s*>\s{3}|✗|✘|×|❌")
_HARD = re.compile(r"(?i)\b(?:error|erreur|err!|fail\w*|fatal|panic|exception|traceback)\b|✗|✘|❌")
_FAIL_START = re.compile(r"^(?:_{3,} .+ _{3,}|=+ (?:FAILURES|ERRORS) =+|FAIL(?:ED)?\b|ERROR\b|--- FAIL\b"
                         r"|Traceback \(most recent call last\)|\s*●\s|thread '.+' panicked)")
_SUMMARY = re.compile(
    r"(?i)\b\d+\s+(?:passed|failed|skipped|errors?|tests?|suites?|pending|todo|xfailed|xpassed|warnings?|packages?"
    r"|vulnerabilit\w*|modules?|files?|deselected)\b|^\s*Ran \d+ tests?|^\s*(?:OK|FAILED)\b|^\s*Tests?:|^\s*Test Suites:"
    r"|^\s*Snapshots:|^\s*Time:|^\s*Duration\b|test result:|^\s*(?:ok|FAIL|PASS)\s+\S|Successfully (?:installed|built)"
    r"|^\s*added \d|^\s*up to date|^\s*audited|^\s*Finished\b|^\s*Done in|^\s*Built\b|^\s*Compiled\b|BUILD (?:SUCCESS|FAILED)"
    r"|webpack compiled|^\s*✓ built in|^\s*Resolved \d|^\s*Installed \d|^\s*Prepared \d|^\s*Audited \d")
# Lignes de remplissage sûres par famille : jamais une erreur (les lignes importantes passent avant ce filtre).
_NOISE = {
    "install": re.compile(r"(?i)^\s*(?:Collecting|Downloading|Using cached|Requirement already satisfied|Obtaining"
                          r"|Preparing metadata|Getting requirements|Building wheels? for|Created wheel|Stored in"
                          r"|Looking in indexes|Processing|Installing build dependencies|Attempting uninstall"
                          r"|Found existing installation|Uninstalling|Successfully uninstalled|Fetching|Resolving"
                          r"|Downloaded|Compiling|Updating|Locking|Checking|Linking|Progress|reify|idealTree"
                          r"|timing|http fetch|npm (?:http|sill|verb|timing)|[+-] \S+==?\S*$|\s*~ \S)"),
    "test": re.compile(r"(?i)(?:\bPASSED\b|\s(?:ok|passed)\s*(?:\(\d.*\))?$|^\s*[✓✔√]\s|^\s*PASS\s|^=== RUN\s|^--- PASS\b"
                       r"|^\s*test \S+ \.\.\. ok$|^\S+\.py[ .]*\[\s*\d+%\]$|^\S+\.py \.+\s*(?:\[\s*\d+%\])?$)"),
    "build": re.compile(r"(?i)^\s*(?:Compiling|Checking|Downloaded|Downloading|Fresh|Building|Running|Step \d+/\d+"
                        r"|#\d+ |--->|Removing intermediate|transforming|rendering chunks|computing gzip|\[\d+/\d+\])"),
    "git-net": re.compile(r"(?i)^\s*(?:remote:\s*)?(?:Enumerating|Counting|Compressing|Receiving|Resolving|Writing"
                          r"|Total \d|Delta compression|Unpacking|Updating files|Checking out|Filtering content)"),
}
_TAIL = {"install": 6, "test": 12, "build": 10, "git-net": 8, "git-log": 0, "mixte": 12}
_DATE = re.compile(r"^Date:\s+(.+?)(?:\s+[+-]\d{4})?$")
_SIG = re.compile(r"[0-9a-f]{7,}|\d+(?:[.,:]\d+)*")


def family(command) -> str | None:
    """Famille de la commande (« install », « test », « build », « git-log », « git-net », « mixte » si plusieurs) ou
    None : seules ces commandes bavardes sont compactées."""
    found = []
    for part in _SPLIT.split(str(command or "")):
        part = _PREFIX.sub("", part)
        for name, rx in _FAMILY_RX:
            if rx.match(part):
                if name == "git-log" and _GIT_LOG_KEEP.search(" " + part):
                    return None
                found.append(name)
                break
    kinds = set(found)
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else "mixte"


def clean_lines(text) -> list:
    """Lignes lisibles : couleurs (ANSI) retirées, seule la dernière étape d'une ligne réécrite par « \\r » (barres de
    progression), espaces de fin coupés, lignes de barres seules et lignes vides en série retirées."""
    out = []
    for line in _ANSI.sub("", str(text or "")).replace("\r\n", "\n").split("\n"):
        line = line.rsplit("\r", 1)[-1].rstrip()
        if line and _BAR.match(line) and not re.search(r"[A-Za-z]{3}", line):
            continue
        if not line and out and not out[-1]:
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return out


def _signature(line) -> str:
    """Forme d'une ligne sans ses nombres ni empreintes, réduite à ses 3 premiers mots : regroupe « npm WARN deprecated
    a@1 », « … b@2 ». Une erreur reste entière : seules ses répétitions exactes sont regroupées."""
    return line.strip() if _HARD.search(line) else " ".join(_SIG.sub("#", line).split()[:3])


def _collapse(lines, idx) -> list:
    """(première, dernière ligne couverte, texte) des lignes gardées, dans l'ordre ; plus de 3 lignes de même forme à
    la suite → les 2 premières + leur nombre."""
    out, i = [], 0
    while i < len(idx):
        j = i
        sig = _signature(lines[idx[i]])
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1 and _signature(lines[idx[j + 1]]) == sig:
            j += 1
        run = idx[i:j + 1]
        if len(run) > 3:
            out += [(k, k, lines[k]) for k in run[:2]] + [(run[2], run[-1], f"… +{len(run) - 2} lignes du même genre")]
        else:
            out += [(k, k, lines[k]) for k in run]
        i = j + 1
    return out


def _gap(n) -> str:
    return f"… ({n} ligne{'s' if n > 1 else ''})"


def _num(n) -> str:
    return f"{n:,}".replace(",", " ")


def _git_log(lines) -> list:
    """`git log` complet → une ligne par commit (empreinte courte, date, sujet, +N lignes de message) ; au-delà de 60
    commits, les 50 premiers."""
    commits, cur = [], None
    for line in lines:
        m = re.match(r"commit ([0-9a-f]{7,40})(.*)", line)
        if m:
            cur = {"sha": m.group(1)[:8], "ref": m.group(2).strip(), "date": "", "subj": None, "more": 0}
            commits.append(cur)
        elif cur is None:
            continue
        elif line.startswith("Date:"):
            raw = _DATE.match(line).group(1) if _DATE.match(line) else line[5:].strip()
            try:
                cur["date"] = time.strftime("%d/%m/%Y", time.strptime(raw, "%a %b %d %H:%M:%S %Y"))
            except ValueError:
                cur["date"] = raw
        elif line.startswith("    ") and line.strip():
            if cur["subj"] is None:
                cur["subj"] = line.strip()
            else:
                cur["more"] += 1
    if not commits:
        return lines
    out = [" ".join(x for x in (c["sha"], c["date"], c["subj"] or "", c["ref"],
                                f"(+{c['more']} l. de message)" if c["more"] else "") if x) for c in commits[:50]]
    if len(commits) > 60:
        return out + [f"… +{len(commits) - 50} commits (sortie brute)"]
    return out + [" ".join(x for x in (c["sha"], c["date"], c["subj"] or "") if x) for c in commits[50:]]


def _json_table(text) -> str | None:
    """Liste JSON d'au moins 3 objets → en-tête + une ligne par objet, colonnes séparées par « | » (façon TOON) ;
    None si la conversion perdrait quelque chose (une valeur contient « | » ou un saut de ligne)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) < 3 or not all(isinstance(d, dict) and d for d in data):
        return None
    cols = list(dict.fromkeys(k for d in data for k in d))
    cell = lambda v: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)  # noqa: E731
    rows = [cols] + [[cell(d[k]) if k in d else "" for k in cols] for d in data]
    if any("|" in str(v) or "\n" in str(v) or "\r" in str(v) for r in rows for v in r):
        return None
    return "\n".join(" | ".join(r) for r in rows)


def compact_text(text, kind, drop=()) -> str:
    """Texte compacté d'une sortie de la famille `kind` (sans en-tête ni pied) ; `drop` : motifs des filtres perso,
    lignes retirées (jamais une erreur)."""
    if kind == "json":
        return _json_table(text) or text
    lines = clean_lines(text)
    if kind == "git-log":
        return "\n".join(_git_log(lines))
    dropped, guard = set(), 0
    for i, line in enumerate(lines if drop else ()):
        guard = 20 if _HARD.search(line) else max(0, guard - 1)  # une erreur et sa trace restent entières
        if not guard and any(r.search(line) for r in drop):
            dropped.add(i)
    noise = _NOISE.get(kind)
    keep = set(range(len(lines))) if kind == "perso" else set(range(max(0, len(lines) - _TAIL.get(kind, 10)), len(lines)))
    block = 0
    for i, line in enumerate(lines):
        if kind == "perso":
            break  # filtre perso : tout sauf ses motifs
        if kind in ("test", "mixte") and _FAIL_START.match(line):
            block = 30  # un échec se lit avec ses lignes suivantes (trace, attendu/obtenu)
        if block:
            keep.add(i)
            block -= 1
        elif _IMPORTANT.search(line) or _SUMMARY.search(line):
            keep.add(i)
        elif i < 2 and line and not (noise and noise.search(line)):
            keep.add(i)  # bannière de l'outil (nom, version)
    keep -= dropped
    idx = [i for i in sorted(keep) if lines[i] or i - 1 in keep]
    out, last = [], -1
    for first, end, line in _collapse(lines, idx):
        if first > last + 1:
            blank = not any(lines[last + 1:first])
            if not blank:
                out.append(_gap(first - last - 1))
            elif out and out[-1]:
                out.append("")
        out.append(line)
        last = end
    if last < len(lines) - 1:
        out.append(_gap(len(lines) - 1 - last))
    return "\n".join(out)


def _saved_path(stdout) -> Path | None:
    """Sortie déjà mise en fichier par Claude Code (bashOutputMaxChars) : « Full output saved to: <chemin> »."""
    m = re.search(r"Full output saved to:\s*(\S.*?\.txt)\b", stdout or "")
    if m:
        p = Path(m.group(1).strip())
        if p.is_file():
            return p
    return None


def _prune(keep_days, max_files):
    try:
        files = sorted(OUT_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    limit = time.time() - keep_days * 86400
    for i, p in enumerate(files):
        try:
            if i >= max_files or p.stat().st_mtime < limit:
                p.unlink()
        except OSError:
            pass


def save_raw(command, stdout, stderr, cfg) -> Path:
    """Sortie brute complète dans state/sorties/<date>-<empreinte>.txt (même sortie → même fichier)."""
    body = f"$ {command}\n\n{stdout}" + (f"\n\n--- stderr ---\n{stderr}" if stderr else "")
    digest = _digest(body)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    found = list(OUT_DIR.glob(f"*-{digest}.txt"))
    if found:
        return found[0]
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{digest}.txt"
    path.write_text(body, encoding="utf-8", errors="replace")
    _prune(cfg.get("keep_days", 3), cfg.get("max_files", 40))
    return path


def _stats(kind, n_in, n_out):
    st = read_json(STATS_FILE, {}) or {}
    st["n"], st["in"], st["out"] = st.get("n", 0) + 1, st.get("in", 0) + n_in, st.get("out", 0) + n_out
    fam = st.setdefault("par", {}).setdefault(kind, [0, 0, 0])
    fam[0], fam[1], fam[2] = fam[0] + 1, fam[1] + n_in, fam[2] + n_out
    st["depuis"] = st.get("depuis") or time.strftime("%Y-%m-%d")
    write_json(STATS_FILE, st)


def _rules(command, cfg) -> list:
    """Motifs « drop » des filtres perso (`compact.filtres`) dont le motif `cmd` prend le début d'une commande simple."""
    out = []
    for f in (cfg or {}).get("filtres") or []:
        try:
            if any(re.match(f["cmd"], _PREFIX.sub("", part)) for part in _SPLIT.split(str(command or ""))):
                out += [re.compile(p) for p in f.get("drop") or []]
        except (re.error, KeyError, TypeError):
            continue  # filtre mal écrit : ignoré, jamais bloquant
    return out


def kind_of(command, stdout, cfg) -> str | None:
    """Famille de la commande, « perso » (filtre perso), « json » (liste JSON) ou None : sortie laissée telle quelle."""
    return family(command) or ("perso" if _rules(command, cfg) else None) or \
        ("json" if (stdout or "").lstrip()[:1] == "[" else None)


def _digest(*parts) -> str:
    import hashlib  # ici : 4 ms d'import épargnés aux commandes qui ne sont pas compactées
    return hashlib.sha1("\0".join(parts).encode("utf-8", "replace")).hexdigest()[:10]


def _repeat(session, command, stdout, stderr, cfg) -> str | None:
    """Sortie identique à une précédente de la session (idée de Session-Dedup, Headroom) → renvoi vers la sortie brute
    plutôt que la relire ; sinon None, et son empreinte est notée (sessions de plus de 2 jours oubliées)."""
    if not session:
        return None
    key, now = _digest(stdout, stderr), time.time()
    seen = {s: v for s, v in (read_json(SEEN_FILE, {}) or {}).items() if now - v.get("t", 0) < 2 * 86400}
    mine = seen.setdefault(session, {"t": now, "k": {}})
    prev = mine["k"].get(key)
    mine["t"] = now
    if prev is None:
        mine["k"] = dict(list(mine["k"].items())[-199:] + [(key, str(command or "")[:120])])
    write_json(SEEN_FILE, seen)
    if prev is None:
        return None
    raw = save_raw(command, stdout, stderr, cfg)
    return (f"[🧠 sortie identique à celle de `{prev}` plus tôt dans cette session ({_num(len(stdout) + len(stderr))} car.,"
            f" rien n'a changé) ; brute complète : {raw.as_posix()}]")


def forget(session):
    """Compaction ou /clear : les sorties déjà lues ont quitté le contexte, plus de renvoi vers elles."""
    seen = read_json(SEEN_FILE, {}) or {}
    if seen.pop(session, None) is not None:
        write_json(SEEN_FILE, seen)


def compact_output(command, stdout, stderr="", cfg=None) -> tuple | None:
    """(stdout, stderr, avant, après) compactés, ou None : commande non bavarde, sortie courte, gain trop faible."""
    cfg = cfg if cfg is not None else load_config().get("compact", {})
    drop = _rules(command, cfg)
    saved = _saved_path(stdout)
    if saved:
        try:
            stdout = saved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    kind = kind_of(command, stdout, cfg)
    if not kind:
        return None
    n_in = len(stdout) + len(stderr or "")
    if n_in < cfg.get("min_chars", 1500):
        return None
    new_out = compact_text(stdout, kind, drop) if stdout else ""
    new_err = compact_text(stderr, kind, drop) if stderr else ""
    if n_in - (len(new_out) + len(new_err) + 150) < max(cfg.get("min_saved", 600), cfg.get("min_gain", 0.3) * n_in):
        return None  # abandon : le gain ne vaut pas une sortie retouchée (150 car. : le pied de page)
    raw = saved or save_raw(command, stdout, stderr, cfg)
    foot = "[🧠 sortie compactée par le cerveau ({}) : {} → {} car. ; brute complète : " + raw.as_posix() + "]"
    body = new_out + "\n" if new_out else ""
    n_out = len(body) + len(new_err) + len(foot)
    for _ in range(2):  # le pied de page compte ses propres caractères
        n_out = len(body) + len(new_err) + len(foot.format(kind, _num(n_in), _num(n_out)))
    new_out = body + foot.format(kind, _num(n_in), _num(n_out))
    return new_out, new_err, n_in, len(new_out) + len(new_err)


def on_post_bash(data, cfg=None) -> dict | None:
    """Hook PostToolUse (Bash) → sortie de hook avec `updatedToolOutput`, ou None (sortie laissée telle quelle)."""
    if data.get("tool_name") != "Bash":
        return None
    tin, resp = data.get("tool_input") or {}, data.get("tool_response")
    if not isinstance(resp, dict) or tin.get("run_in_background") or resp.get("interrupted") or resp.get("isImage"):
        return None
    stdout, stderr, command = resp.get("stdout"), resp.get("stderr") or "", tin.get("command")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None
    cfg = cfg if cfg is not None else load_config()
    cc = cfg.get("compact") or {}
    if not cc.get("enabled", True):
        return None
    ref = None
    if len(stdout) + len(stderr) >= cc.get("min_chars", 1500):
        ref = _repeat(data.get("session_id"), command, stdout, stderr, cc)
    if ref:
        done, kind = (ref, "", len(stdout) + len(stderr), len(ref)), "doublon"
    else:
        done, kind = compact_output(command, stdout, stderr, cc), kind_of(command, stdout, cc) or "json"
    if not done:
        if cc.get("echantillons") and len(stdout) + len(stderr) >= cc.get("min_chars", 1500):
            save_raw(command, stdout, stderr, cc)  # opt-in : matière de `brain compact --decouvrir`
        return None
    new_out, new_err, n_in, n_out = done
    try:
        _stats(kind, n_in, n_out)
    except Exception as exc:
        log(f"compact : statistiques non écrites ({exc!r})")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "updatedToolOutput": {**resp, "stdout": new_out, "stderr": new_err}}}


def hook() -> int:
    """Point d'entrée rapide (`brain.py hook post-bash`) : n'importe que ce module et le socle."""
    data = read_stdin_json()
    try:
        out = on_post_bash(data)
        if out:
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.flush()
    except Exception as exc:
        log(f"hook post-bash ERREUR {exc!r}")
    return 0


def stats_text() -> str:
    st = read_json(STATS_FILE, {}) or {}
    if not st.get("n"):
        return "Sorties compactées : aucune pour l'instant (commandes bavardes : installations, tests, builds, git log…)."
    from .common import CHARS_PER_TOKEN
    lines = [f"Sorties compactées depuis le {st.get('depuis', '?')} : {st['n']} — {_num(st['in'])} → {_num(st['out'])} "
             f"car. (≈ {_num(int((st['in'] - st['out']) / CHARS_PER_TOKEN))} tokens de moins à la lecture, puis à chaque "
             f"relecture du contexte)"]
    for kind, (n, a, b) in sorted(st.get("par", {}).items(), key=lambda kv: -(kv[1][1] - kv[1][2])):
        lines.append(f"- {kind} : {n} fois, {_num(a)} → {_num(b)} car. (−{100 - 100 * b // max(1, a)} %)")
    return "\n".join(lines)


# --- Filtres appris (idée de rtk_discover / rtk_learn) : suggestions seulement, appliquées après --enregistrer ---
_PLAIN = re.compile(r"^(?:[^\W\d_]+(?:[-'’][^\W\d_]+)*:?|[^\w\s]{1,3})$")


def _key(line) -> str:
    """Étiquette d'une ligne : ses premiers mots sans chiffre ni nom propre au cas (3 au plus) — « Collecting
    requests==2.31 » → « Collecting », « remote: Counting objects: 5 » → « remote: Counting objects: »."""
    words = []
    for w in line.split()[:3]:
        if not _PLAIN.match(w):
            break
        words.append(w)
    key = " ".join(words)
    return key if len(re.findall(r"[^\W\d_]", key)) >= 4 else ""  # « at », « - » : trop vague


def _label(command) -> str:
    part = _PREFIX.sub("", (_SPLIT.split(str(command or "")) or [""])[-1])
    return " ".join(part.split()[:2])


def _samples(command=None, files=()) -> list:
    """(commande, sortie) : les fichiers donnés, sinon les sorties brutes gardées (state/sorties/, en-tête « $ cmd »)
    dont une commande simple commence par `command`."""
    out = []
    for p in files or sorted(OUT_DIR.glob("*.txt")):
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head, sep, body = text.partition("\n\n")
        cmd = head[2:] if sep and head.startswith("$ ") else ""
        if files:
            out.append((command or cmd, body if cmd else text))
        elif not command or any(_PREFIX.sub("", part).startswith(command.strip()) for part in _SPLIT.split(cmd)):
            out.append((cmd, body))
    return out


def recurrent(samples, min_n=5) -> list:
    """Lignes de bruit qui reviennent : même étiquette au moins `min_n` fois (dans 2 sorties au moins s'il y en a
    plusieurs), et jamais sur une erreur, un avertissement ni un résumé → [(étiquette, lignes, sorties, car., exemple,
    motif, commandes)], les plus coûteuses d'abord."""
    stat, bad = {}, set()
    for i, (cmd, text) in enumerate(samples):
        for line in clean_lines(text):
            k = _key(line)
            if not k:
                continue
            if _IMPORTANT.search(line) or _SUMMARY.search(line):
                bad.add(k)
            s = stat.setdefault(k, [0, set(), 0, line, set()])
            s[0], s[2] = s[0] + 1, s[2] + len(line) + 1
            s[1].add(i)
            s[4].add(_label(cmd))
    need = 2 if len(samples) > 1 else 1
    rows = [(k, n, len(f), c, ex, r"^\s*" + r"\s+".join(map(re.escape, k.split())) + (r"\b" if k[-1].isalnum() else ""),
             sorted(x for x in cmds if x)) for k, (n, f, c, ex, cmds) in stat.items()
            if k not in bad and n >= min_n and len(f) >= need]
    return sorted(rows, key=lambda r: -r[3])


def discover_text() -> str:
    """`brain compact --decouvrir` : le bruit qui revient dans les sorties gardées, classé par caractères."""
    samples = _samples()
    hint = "sorties des commandes non reconnues aussi : brain config compact.echantillons true (gardées keep_days jours)"
    if not samples:
        return f"Aucune sortie gardée dans state/sorties/ pour l'instant ({hint})."
    rows = recurrent(samples)
    out = [f"Bruit qui revient dans {len(samples)} sortie(s) gardée(s) — suggestions, rien n'est appliqué :"]
    for k, n, f, c, ex, _, cmds in rows[:15]:
        out.append(f"- « {k} » : {n} lignes dans {f} sortie(s), {_num(c)} car. — ex. « {ex.strip()[:80]} »"
                   + (f" — {', '.join(cmds[:3])}" if cmds else ""))
    if len(out) == 1:
        out.append("- rien qui revienne assez souvent")
    else:
        out.append("Filtre pour une commande : brain compact --apprendre \"<commande>\" (puis --enregistrer)")
    if not load_config().get("compact", {}).get("echantillons"):
        out.append(f"({hint})")
    return "\n".join(out)


def learn_text(command, files=(), save=False) -> str:
    """`brain compact [sortie.txt] --apprendre <commande> [--enregistrer]` : filtre proposé pour cette commande,
    appris de ses sorties (gardées ou données), avec le gain mesuré dessus ; enregistré dans compact.filtres sur demande."""
    samples = _samples(command, files)
    if not samples:
        return (f"Aucune sortie de « {command} » gardée : donne-en une (brain compact sortie.txt --apprendre "
                f"\"{command}\") ou garde les sorties des commandes non reconnues (brain config compact.echantillons true).")
    rows = recurrent(samples, 3)
    if not rows:
        return f"« {command} » ({len(samples)} sortie(s)) : aucune ligne de bruit qui revienne — pas de filtre à proposer."
    filt = {"cmd": re.escape(command.strip()) + r"(?=\s|$)", "drop": [r[5] for r in rows[:12]]}
    drop = [re.compile(p) for p in filt["drop"]]
    kind = family(command) or "perso"
    before = sum(len(t if kind == "perso" else compact_text(t, kind)) for _, t in samples)
    after = sum(len(compact_text(t, kind, drop)) for _, t in samples)
    out = [f"Filtre proposé pour « {command} » ({len(samples)} sortie(s)) : {_num(before)} → {_num(after)} car.",
           json.dumps(filt, ensure_ascii=False)] + [f"- « {r[0]} » : {r[1]} lignes, ex. « {r[4].strip()[:80]} »"
                                                    for r in rows[:12]]
    if not save:
        return "\n".join(out + ["Relis la liste : une ligne utile qui revient souvent y figure aussi (motif à retirer du JSON).",
                                f"Pour l'appliquer à chaque sortie : brain compact --apprendre \"{command}\" --enregistrer"
                                " (ou brain config compact.filtres '[<JSON retouché>]')"])
    from .common import update_config

    def change(c):
        cc = c.setdefault("compact", {})
        cc["filtres"] = [f for f in cc.get("filtres") or [] if f.get("cmd") != filt["cmd"]] + [filt]
    update_config(change)
    return "\n".join(out + ["✓ Enregistré dans compact.filtres : appliqué tout seul (les erreurs et leurs traces restent)."])
