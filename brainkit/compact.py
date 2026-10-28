"""Sorties de commandes compactes — idées de RTK, quiet-shell-mcp et token-saver (crédits d'OmniRoute, 28/10/2026).

Après une commande bavarde (installation, tests, build, `git log`, clone…), le hook PostToolUse du cerveau remplace la
sortie que Claude lit par l'essentiel : erreurs et avertissements (les répétitions regroupées), résumé de fin. La
commande a tourné telle quelle (rien n'est réécrit : permissions, `cd` et code de sortie intacts) et la sortie brute
reste dans un fichier (`state/sorties/`, gardé `keep_days` jours) dont le chemin termine la sortie compactée. Rien
n'est touché si la sortie est courte ou si le gain est faible ; une commande en échec (PostToolUseFailure) garde sa
sortie entière. `brain compact` pour l'essayer à la main ; `config compact.enabled false` pour le couper.
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


def compact_text(text, kind) -> str:
    """Texte compacté d'une sortie de la famille `kind` (sans en-tête ni pied)."""
    lines = clean_lines(text)
    if kind == "git-log":
        return "\n".join(_git_log(lines))
    noise = _NOISE.get(kind)
    keep = set(range(max(0, len(lines) - _TAIL.get(kind, 10)), len(lines)))
    block = 0
    for i, line in enumerate(lines):
        if kind in ("test", "mixte") and _FAIL_START.match(line):
            block = 30  # un échec se lit avec ses lignes suivantes (trace, attendu/obtenu)
        if block:
            keep.add(i)
            block -= 1
        elif _IMPORTANT.search(line) or _SUMMARY.search(line):
            keep.add(i)
        elif i < 2 and line and not (noise and noise.search(line)):
            keep.add(i)  # bannière de l'outil (nom, version)
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
    import hashlib  # ici : 4 ms d'import épargnés aux commandes qui ne sont pas compactées
    body =f"$ {command}\n\n{stdout}" + (f"\n\n--- stderr ---\n{stderr}" if stderr else "")
    digest = hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:10]
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


def compact_output(command, stdout, stderr="", cfg=None) -> tuple | None:
    """(stdout, stderr, avant, après) compactés, ou None : commande non bavarde, sortie courte, gain trop faible."""
    cfg = cfg if cfg is not None else load_config().get("compact", {})
    kind = family(command)
    if not kind:
        return None
    saved = _saved_path(stdout)
    if saved:
        try:
            stdout = saved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    n_in = len(stdout) + len(stderr or "")
    if n_in < cfg.get("min_chars", 1500):
        return None
    new_out = compact_text(stdout, kind) if stdout else ""
    new_err = compact_text(stderr, kind) if stderr else ""
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
    stdout, stderr = resp.get("stdout"), resp.get("stderr") or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str) or not family(tin.get("command")):
        return None
    cfg = cfg if cfg is not None else load_config()
    cc = cfg.get("compact") or {}
    if not cc.get("enabled", True):
        return None
    done = compact_output(tin.get("command"), stdout, stderr, cc)
    if not done:
        return None
    new_out, new_err, n_in, n_out = done
    try:
        _stats(family(tin.get("command")), n_in, n_out)
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
