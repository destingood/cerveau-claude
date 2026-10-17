"""PreToolUse hook for Bash|PowerShell (mega-prompt 16.5).

Refuses at least: `rm -rf` (and its PowerShell / cmd equivalents), `git push` to main or
forced, `--force`, hook bypasses (R6), any command that writes, moves or changes the
permissions of a protected path (redirection, tee, sed -i, mv, cp, chmod, chown, icacls...)
and any read of `.env` or `secrets/`.

The shell grammar is approximated on purpose: ambiguous constructs are refused rather than
guessed. This is a convenience guard-rail; the effective protection of config/live.yaml
remains the file-system ACL (R3, ADR-003).
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field

import _common as c

MAX_DEPTH = 3
PROTECTED_BRANCHES = frozenset({"main", "master"})

READ_ONLY = frozenset(
    {
        # POSIX inspection tools
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ls", "dir",
        "stat", "file", "wc", "md5sum", "sha1sum", "sha256sum", "sha512sum", "diff", "cmp",
        "tree", "du", "realpath", "readlink", "basename", "dirname", "test", "[", "[[",
        "echo", "printf", "jq", "yq", "nl", "od", "hexdump", "strings", "cut", "column",
        "sed", "find", "pwd", "true", "false", "which", "where", "type",
        # PowerShell inspection cmdlets and aliases
        "get-content", "gc", "get-childitem", "gci", "get-item", "gi", "get-itemproperty",
        "gp", "get-filehash", "test-path", "select-string", "sls", "measure-object",
        "resolve-path", "rvpa", "get-acl", "write-output", "write-host", "get-location",
        "split-path", "join-path", "format-list", "format-table", "select-object",
        "where-object", "sort-object", "out-host", "out-null", "convertfrom-json",
        "convertto-json",
        # Windows tools (write options are checked separately)
        "icacls", "attrib", "findstr", "fc",
        # navigation and shell state
        "cd", "pushd", "popd", "set-location", "sl", "chdir", "export",
        # project tools that only read protected files
        "git", "cerveau",
    }
)  # fmt: skip
# Commands for which naming a directory that contains a protected path is already a risk.
MUTATORS = frozenset(
    {
        "rm", "rmdir", "mv", "cp", "chmod", "chown", "chgrp", "chattr", "ln", "install",
        "rsync", "truncate", "shred", "touch", "tar", "unzip", "7z", "dd", "takeown",
        "remove-item", "ri", "del", "erase", "rd", "move-item", "mi", "move", "copy-item",
        "cpi", "copy", "robocopy", "xcopy", "rename-item", "ren", "rni", "set-acl",
        "clear-content", "clc", "set-content", "sc", "add-content", "ac", "out-file",
        "new-item", "ni", "set-itemproperty", "sp", "clear-item", "cli", "expand-archive",
        "compress-archive",
    }
)  # fmt: skip
WRAPPERS = frozenset(
    {
        "sudo", "doas", "env", "command", "builtin", "exec", "nohup", "time", "nice",
        "ionice", "timeout", "stdbuf", "xargs", "npx", "uvx", "pnpx", "bunx", "call",
    }
)  # fmt: skip
WRAPPER_VALUE_OPTS = frozenset({"-I", "-n", "-P", "-L", "-s", "-u", "-d", "-E", "-C", "-p"})
KEYWORDS = frozenset({"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}"})
UV_VALUE_OPTS = frozenset(
    {"--with", "--project", "--directory", "--python", "-p", "--package", "--group", "--extra"}
)
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
PS_SHELLS = frozenset({"pwsh", "powershell"})
INTERPRETERS = frozenset({"python", "python3", "py", "node", "perl", "ruby", "php"})
EVALUATORS = frozenset({"eval", "iex", "invoke-expression"})
GIT_SAFE = frozenset(
    {
        "status", "diff", "log", "show", "add", "commit", "branch", "tag", "rev-parse",
        "ls-files", "ls-tree", "grep", "blame", "describe", "shortlog", "reflog", "remote",
        "fetch", "init", "config", "cat-file", "check-ignore", "check-attr", "show-ref",
        "for-each-ref", "rev-list", "name-rev", "count-objects", "fsck", "version", "help",
        "hash-object", "merge-base", "notes", "push", "symbolic-ref", "var", "whatchanged",
    }
)  # fmt: skip
GIT_VALUE_OPTS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})
PUSH_VALUE_OPTS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
SECRET_READ_EXEMPT = frozenset(
    {
        "ls", "dir", "gci", "get-childitem", "test-path", "test", "[", "[[", "stat", "echo",
        "printf", "write-output", "write-host", "cd", "set-location", "sl", "pushd",
    }
)  # fmt: skip
GREP_LIKE = frozenset({"grep", "egrep", "fgrep", "rg"})
GREP_VALUE_OPTS = frozenset(
    {
        "-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "-g", "-t", "-T", "-j", "-M",
        "--regexp", "--file", "--max-count", "--glob", "--type", "--type-not", "--context",
        "--after-context", "--before-context", "--threads", "--max-columns",
    }
)  # fmt: skip
PS_CONTENT_READERS = frozenset(
    {"select-string", "sls", "get-content", "gc", "cat", "type", "foreach-object", "%"}
)
FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
FIND_WRITE = FIND_EXEC | {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
ICACLS_WRITE = (
    "/grant", "/deny", "/remove", "/reset", "/setowner", "/setintegritylevel",
    "/inheritance", "/restore", "/substitute",
)  # fmt: skip
NULL_SINKS = frozenset({"/dev/null", "nul", "nul:", "$null"})
WRITE_PROTECTED_NAMES = ("live.yaml", "governance/approvals", "var/audit")
UNKNOWN_CWD_CANDIDATES = (
    "config", "governance", "governance/approvals", "var", "var/audit", "infra", "secrets",
)  # fmt: skip

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_SHORT_CLUSTER = re.compile(r"^-[A-Za-z]+$")
_ENV_FILE = re.compile(r"(?<![\w.-])\.env(?![\w-])(?!\.example(?![\w.-]))", re.IGNORECASE)
_SECRETS_DIR = re.compile(r"(?<![\w.-])secrets(?=$|[/\s'\";|&)])", re.IGNORECASE)
_HOOK_BYPASS_ENV = re.compile(
    r"\$env:(SKIP|PRE_COMMIT\w*|HUSKY|GIT_HOOKS?\w*)\s*=|^(SKIP|PRE_COMMIT\w*|HUSKY)=",
    re.IGNORECASE,
)
_SED_WRITE_COMMAND = re.compile(r"(^|[/;}\s])[wW]\s+\S|(^|[/;}\s])e(\s|$)")


# --- tokenizer ---------------------------------------------------------------------------------


@dataclass
class Segment:
    """One simple command: words after quote removal, redirection targets, heredoc bodies."""

    raw: str
    tokens: list[str]
    redirects: list[str] = field(default_factory=list)
    heredoc: str = ""
    piped: bool = False


def _matching_paren(text: str, start: int) -> int:
    """Index of the `)` closing a `$(` whose content starts at `start` (len(text) if none)."""
    depth, quote, i = 1, None, start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            i += 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


class Scanner:
    """Split a Bash or PowerShell command line into segments of words.

    Separators: newline ; | || & && ( ) and, in PowerShell or for bash groups, { }.
    Command substitutions ($(...), backticks) are collected for recursive analysis.
    """

    def __init__(self, text: str, powershell: bool) -> None:
        self.text = text
        self.ps = powershell
        self.esc = "`" if powershell else "\\"
        self.segments: list[Segment] = []
        self.substitutions: list[str] = []
        self._raw: list[str] = []
        self._tokens: list[str] = []
        self._redirects: list[str] = []
        self._word: list[str] = []
        self._in_word = False
        self._redirect_next = False
        self._heredocs: list[tuple[str, bool, int]] = []
        self._here_words: list[str] = []
        self._here_next = False
        self._piped = False
        self._next_piped = False

    # word / segment bookkeeping
    def _take(self, raw: str, word: str) -> None:
        self._raw.append(raw)
        self._word.append(word)
        self._in_word = True

    def _end_word(self) -> None:
        if not self._in_word:
            return
        word = "".join(self._word)
        if self._redirect_next:
            self._redirects.append(word)
            self._redirect_next = False
        elif self._here_next:
            self._here_words.append(word)
            self._here_next = False
        else:
            self._tokens.append(word)
        self._word, self._in_word = [], False

    def _end_segment(self) -> None:
        self._end_word()
        self._redirect_next = self._here_next = False
        raw = "".join(self._raw).strip()
        if raw or self._tokens:
            here = "".join(f"{w}\n" for w in self._here_words)
            self.segments.append(Segment(raw, self._tokens, self._redirects, here, self._piped))
        self._raw, self._tokens, self._redirects, self._here_words = [], [], [], []
        self._piped, self._next_piped = self._next_piped, False

    def _separator(self, piped: bool = False) -> None:
        self._end_segment()
        self._piped = piped

    # special constructs
    def _redirect(self, i: int) -> int:
        word = "".join(self._word)
        if self._in_word and (word.isdigit() or word == "*"):
            self._word, self._in_word = [], False  # file-descriptor prefix (2>, *>)
        else:
            self._end_word()
        text, n, j = self.text, len(self.text), i
        while j < n and text[j] == ">":
            j += 1
        if j < n and text[j] == "|":
            j += 1
        self._raw.append(text[i:j])
        if j < n and text[j] == "&":
            k = j + 1
            while k < n and (text[k].isdigit() or text[k] == "-"):
                k += 1
            if k > j + 1:  # >&2, 2>&1: duplication, no file
                self._raw.append(text[j:k])
                return k
            j += 1
        self._redirect_next = True
        return j

    def _heredoc(self, i: int) -> int:
        self._end_word()
        text, n, j = self.text, len(self.text), i + 2
        strip_tabs = j < n and text[j] == "-"
        if strip_tabs:
            j += 1
        while j < n and text[j] in " \t":
            j += 1
        start = j
        while j < n and text[j] not in " \t\n\r;|&<>()":
            j += 1
        delimiter = text[start:j].strip("'\"").replace("\\", "")
        self._raw.append(text[i:j])
        if delimiter:
            self._heredocs.append((delimiter, strip_tabs, len(self.segments)))
        return j

    def _consume_heredocs(self, i: int) -> int:
        text, n = self.text, len(self.text)
        for delimiter, strip_tabs, index in self._heredocs:
            body: list[str] = []
            while i < n:
                end = text.find("\n", i)
                end = n if end == -1 else end
                line = text[i:end].rstrip("\r")
                i = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
                body.append(line)
            if index < len(self.segments):
                self.segments[index].heredoc += "\n".join(body) + "\n"
        self._heredocs = []
        return i

    def _here_string(self, i: int) -> int:
        text, quote = self.text, self.text[i + 1]
        close = "\n" + quote + "@"
        end = text.find(close, i + 2)
        end = len(text) if end == -1 else end
        body = text[i + 2 : end]
        if quote == '"':
            for match in re.finditer(r"\$\(", body):
                self.substitutions.append(body[match.end() : _matching_paren(body, match.end())])
        self._take(text[i : end + len(close)], body)
        return end + len(close)

    def scan(self) -> Scanner:
        text, n, i = self.text, len(self.text), 0
        quote: str | None = None
        while i < n:
            ch = text[i]
            nxt = text[i + 1] if i + 1 < n else ""
            if quote == "'":
                self._raw.append(ch)
                if ch == "'":
                    quote = None
                else:
                    self._word.append(ch)
                i += 1
            elif ch == "$" and nxt == "(":
                end = _matching_paren(text, i + 2)
                self.substitutions.append(text[i + 2 : end])
                self._take(text[i : end + 1], "$(…)")
                i = end + 1
            elif ch == "$" and nxt == "{":
                end = text.find("}", i)
                end = n - 1 if end == -1 else end
                self._take(text[i : end + 1], text[i : end + 1])
                i = end + 1
            elif ch == "`" and not self.ps:
                end = text.find("`", i + 1)
                end = n if end == -1 else end
                self.substitutions.append(text[i + 1 : end])
                self._take(text[i : end + 1], "`…`")
                i = end + 1
            elif ch == self.esc and nxt:
                self._raw.append(ch + nxt)
                if nxt != "\n":
                    if quote == '"' and not self.ps and nxt not in '"\\$`':
                        self._word.append(ch)
                    self._word.append(nxt)
                    self._in_word = True
                i += 2
            elif quote == '"':
                self._raw.append(ch)
                if ch == '"':
                    quote = None
                else:
                    self._word.append(ch)
                i += 1
            else:
                i = self._unquoted(i, ch, nxt)
                if i < 0:  # opening quote
                    quote, i = ch, -i
        self._end_segment()
        return self

    def _unquoted(self, i: int, ch: str, nxt: str) -> int:
        """Handle one unquoted character; returns the next index (negated after a quote)."""
        text = self.text
        if self.ps and ch == "@" and nxt in "'\"" and text[i + 2 : i + 3] in ("\n", "\r"):
            return self._here_string(i)
        if ch in "'\"":
            self._raw.append(ch)
            self._in_word = True
            return -(i + 1)
        if ch in " \t":
            self._end_word()
            self._raw.append(ch)
            return i + 1
        if ch in "\r\n":
            self._separator()
            return self._consume_heredocs(i + 1) if self._heredocs else i + 1
        if (ch == "|" and nxt == "|") or (ch == "&" and nxt == "&"):
            self._separator()
            return i + 2
        if ch == "&" and nxt == ">":
            self._end_word()
            self._raw.append("&")
            return self._redirect(i + 1)
        if ch == ">":
            return self._redirect(i)
        if ch == "<" and not self.ps and text.startswith("<<<", i):
            self._end_word()
            self._raw.append("<<<")
            self._here_next = True
            return i + 3
        if ch == "<" and nxt == "<" and not self.ps:
            return self._heredoc(i)
        if ch == "<":
            self._end_word()
            self._raw.append(ch)
            return i + 1
        if ch == "|":
            self._separator(piped=True)
            return i + 1
        if ch in ";&()":
            self._separator()
            return i + 1
        if ch in "{}" and (self.ps or self._brace_is_separator(i, ch)):
            self._separator()
            return i + 1
        self._raw.append(ch)
        self._word.append(ch)
        self._in_word = True
        return i + 1

    def _brace_is_separator(self, i: int, ch: str) -> bool:
        # bash group `{ cmd; }` needs blanks; `file{,.bak}` or `{}` is brace expansion / a word
        text = self.text
        if ch == "{":
            return not self._in_word and (i + 1 >= len(text) or text[i + 1] in " \t\n")
        return not self._in_word


def expand_braces(word: str, limit: int = 64) -> list[str]:
    """Minimal bash brace expansion (`a{b,c}d` -> abd, acd), enough for path checks."""
    match = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not match or limit <= 0:
        return [word]
    results: list[str] = []
    for option in match.group(1).split(","):
        results.extend(
            expand_braces(word[: match.start()] + option + word[match.end() :], limit - 1)
        )
        if len(results) >= limit:
            break
    return results[:limit]


# --- analysis context --------------------------------------------------------------------------


@dataclass
class Context:
    powershell: bool
    depth: int
    cwd: str | None  # normalised; None when a `cd` made it unknowable

    def bases(self) -> list[str]:
        if self.cwd is not None:
            return [self.cwd]
        root = c.root_norm()
        return [root] + [f"{root}/{d}" for d in UNKNOWN_CWD_CANDIDATES]

    def resolve(self, token: str) -> set[str]:
        paths: set[str] = set()
        for candidate in path_candidates(token, self.powershell):
            for expanded in expand_braces(candidate):
                for base in self.bases():
                    paths.add(c.normalise(expanded, base))
        return paths

    def glob_hit(self, token: str, samples: tuple[str, ...], ancestors: bool = False) -> bool:
        dotfiles = self.powershell
        return any(
            c.glob_could_match(candidate, base, samples, dotfiles, ancestors=ancestors)
            for candidate in path_candidates(token, self.powershell)
            for base in self.bases()
        )


def path_candidates(token: str, powershell: bool) -> list[str]:
    """Strings inside a word that may name a file (`--out=x`, `of=x`, `-Path:x`)."""
    if not token or token in ("-", "--"):
        return []
    if token.startswith("-"):
        for sep in ("=", ":") if powershell else ("=",):
            if sep in token:
                return [token.split(sep, 1)[1]]
        return []
    candidates = [token]
    if "=" in token and not token.startswith("="):
        candidates.append(token.split("=", 1)[1])
    return candidates


def basename(token: str) -> str:
    name = re.split(r"[\\/]", token.strip("'\""))[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def command_word(tokens: list[str]) -> tuple[int | None, str, list[str]]:
    """Index and name of the executed command, skipping assignments and wrappers."""
    assignments: list[str] = []
    i = 0
    while i < len(tokens):
        token, name = tokens[i], basename(tokens[i])
        if _ASSIGNMENT.match(token):
            assignments.append(token)
            i += 1
        elif name in KEYWORDS:
            i += 1
        elif name in WRAPPERS:
            i += 1
            while i < len(tokens) and (
                tokens[i].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", tokens[i])
            ):
                i += 2 if tokens[i] in WRAPPER_VALUE_OPTS else 1
        elif name == "uv" and i + 1 < len(tokens) and tokens[i + 1] in ("run", "tool"):
            i += 2
            if i < len(tokens) and tokens[i] == "run":  # uv tool run
                i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in UV_VALUE_OPTS else 1
        elif name in ("npm", "pnpm", "yarn") and i + 1 < len(tokens) and tokens[i + 1] == "exec":
            i += 2
        else:
            return i, name, assignments
    return None, "", assignments


def is_dynamic(name: str) -> bool:
    return any(mark in name for mark in ("$", "…", "`", "%"))


# --- individual rules --------------------------------------------------------------------------


def _unix_recursive_force(args: list[str], short_only: bool = False) -> bool:
    recursive = force = False
    for arg in args:
        if arg == "--":
            break
        if arg in ("--recursive", "--force") and not short_only:
            recursive |= arg == "--recursive"
            force |= arg == "--force"
        elif _SHORT_CLUSTER.match(arg) and (not short_only or len(arg) <= 3):
            recursive |= "r" in arg[1:] or "R" in arg[1:]
            force |= "f" in arg[1:]
    return recursive and force


def _ps_param(arg: str, name: str, min_len: int = 2) -> bool:
    low = arg.lower().split(":", 1)[0]
    return low.startswith("-") and len(low) >= min_len and name.startswith(low)


def _ps_recursive_force(args: list[str]) -> bool:
    recursive = any(_ps_param(a, "-recurse") for a in args)
    force = any(_ps_param(a, "-force") for a in args)
    return recursive and force


def check_recursive_delete(tokens: list[str], cmd: str, ps: bool) -> str | None:
    for index, token in enumerate(tokens):
        name, rest = basename(token), tokens[index + 1 :]
        lowered = {a.lower() for a in rest}
        if name == "rm" and (
            _ps_recursive_force(rest) or _unix_recursive_force(rest, short_only=ps)
            if ps
            else _unix_recursive_force(rest)
        ):
            return "suppression récursive forcée (rm -rf) interdite"
        if name in ("remove-item", "ri", "del", "erase", "rd", "rmdir") and (
            _ps_recursive_force(rest) or {"/s", "/q"} <= lowered
        ):
            return "suppression récursive forcée (Remove-Item -Recurse -Force, rd /s /q) interdite"
    if is_dynamic(cmd) and (_unix_recursive_force(tokens) or _ps_recursive_force(tokens)):
        return "commande dynamique avec suppression récursive forcée : refus par précaution"
    return None


def check_force_and_bypass(tokens: list[str], cmd: str, assignments: list[str]) -> str | None:
    for token in tokens:
        low = token.lower()
        if low == "--force" or low.startswith("--force="):
            return "option --force interdite"
        if low == "--no-verify":
            return "--no-verify contourne les hooks (gitleaks, R6) : interdit"
        if "core.hookspath" in low:
            return "modifier core.hooksPath contourne les hooks (R6) : interdit"
    if cmd == "pre-commit" and len(tokens) > 1 and "uninstall" in (t.lower() for t in tokens):
        return "désinstaller pre-commit contourne gitleaks (R6) : interdit"
    if any(_HOOK_BYPASS_ENV.match(t) for t in [*assignments, *tokens]):
        return "variable d'environnement qui désactive les hooks (R6) : interdite"
    return None


@dataclass
class GitCall:
    sub: str
    args: list[str]
    cwd: str | None


def parse_git(args: list[str], ctx: Context) -> GitCall:
    cwd, i = ctx.cwd, 0
    while i < len(args):
        arg = args[i]
        if arg in GIT_VALUE_OPTS:
            if arg == "-C" and i + 1 < len(args):
                cwd = c.normalise(args[i + 1], cwd) if cwd else None
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return GitCall(arg.lower(), args[i + 1 :], cwd)
    return GitCall("", [], cwd)


def current_branch(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    for query in (["symbolic-ref", "--short", "-q", "HEAD"], ["rev-parse", "--abbrev-ref", "HEAD"]):
        try:
            result = subprocess.run(
                ["git", "-C", cwd, *query], capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _is_protected_branch(ref: str) -> bool:
    name = ref.removeprefix("refs/heads/").lower()
    return name in PROTECTED_BRANCHES or "*" in name


def check_push(call: GitCall) -> str | None:
    positional: list[str] = []
    i = 0
    while i < len(call.args):
        arg, low = call.args[i], call.args[i].lower()
        forced_cluster = _SHORT_CLUSTER.match(arg) and "f" in arg[1:]
        if low in ("-f", "--force") or forced_cluster or low.startswith("--force"):
            return "git push forcé interdit"
        if low in ("--all", "--mirror", "--branches"):
            return "git push --all / --mirror interdit : il pousserait main"
        if low in PUSH_VALUE_OPTS:
            i += 2
            continue
        if not low.startswith("-"):
            positional.append(arg)
        i += 1
    refspecs = positional[1:]
    if not refspecs:
        branch = current_branch(call.cwd)
        if branch is None:
            return "branche courante inconnue : git push refusé par précaution"
        if _is_protected_branch(branch):
            return f"git push depuis {branch} interdit (pas de push vers main)"
        return None
    for spec in refspecs:
        if spec.startswith("+"):
            return "refspec forcée (+) interdite"
        target = spec.split(":", 1)[1] if ":" in spec else spec
        if target in ("HEAD", "@"):
            target = current_branch(call.cwd) or "main"
        if _is_protected_branch(target):
            return f"git push vers {target} interdit"
    return None


def check_git(call: GitCall) -> str | None:
    if call.sub == "push":
        return check_push(call)
    if call.sub == "reset" and any(a.lower() == "--hard" for a in call.args):
        return "git reset --hard interdit (perte de travail non commité)"
    if call.sub == "clean" and not any(
        a in ("-n", "--dry-run") or (_SHORT_CLUSTER.match(a) and "n" in a) for a in call.args
    ):
        return "git clean interdit hors --dry-run (suppression irréversible)"
    if call.sub == "commit":
        args = call.args
        for index, arg in enumerate(args):
            if index > 0 and args[index - 1] in ("-m", "-F", "-C", "-c", "-t"):
                continue
            if _SHORT_CLUSTER.match(arg):
                for letter in arg[1:]:
                    if letter in "mFCct":
                        break
                    if letter == "n":
                        return "git commit -n contourne les hooks (gitleaks, R6) : interdit"
    return None


def write_capable(cmd: str, args: list[str], git: GitCall | None) -> bool:
    """Whether a normally read-only command is used with an option that writes."""
    lowered = [a.lower() for a in args]
    if cmd == "sed":
        in_place = any(
            a.startswith("--in-place")
            or (_SHORT_CLUSTER.match(a) and "i" in a)
            or a.startswith("-i")
            for a in args
        )
        return in_place or any(_SED_WRITE_COMMAND.search(a) for a in args)
    if cmd == "find":
        return any(a in FIND_WRITE for a in lowered)
    if cmd == "yq":
        return any(a in ("-i", "--inplace") or a.startswith("--inplace") for a in lowered)
    if cmd == "tree":
        return any(a == "-o" for a in args)
    if cmd == "icacls":
        return any(a.startswith(ICACLS_WRITE) for a in lowered)
    if cmd == "attrib":
        return any(re.fullmatch(r"[+-][rahsiox]+", a) for a in lowered)
    if cmd == "git":
        if git is None or git.sub not in GIT_SAFE:
            return True
        return any(a.startswith("--output") for a in lowered)
    return False


def check_protected_write(
    seg: Segment,
    tokens: list[str],
    cmd_index: int | None,
    cmd: str,
    ctx: Context,
    git: GitCall | None,
) -> str | None:
    for target in seg.redirects:
        if target.lower() in NULL_SINKS:
            continue
        for path in ctx.resolve(target):
            if reason := c.write_protection_reason(path):
                return f"redirection vers un chemin protégé : {reason}"
        if ctx.glob_hit(target, c.GLOB_SAMPLES_WRITE + c.GLOB_SAMPLES_READ):
            return f"redirection vers un motif qui couvre un chemin protégé : {target}"

    others = [t for i, t in enumerate(tokens) if i != cmd_index]
    folded = (seg.raw + "\n" + seg.heredoc).replace("\\", "/").lower()
    detail = next((f"mentionne {name}" for name in WRITE_PROTECTED_NAMES if name in folded), None)
    for token in others:
        if detail:
            break
        detail = next(filter(None, map(c.write_protection_reason, ctx.resolve(token))), None)
        if not detail and ctx.glob_hit(token, c.GLOB_SAMPLES_WRITE + c.GLOB_SAMPLES_READ):
            detail = f"le motif {token} couvre un chemin protégé"
    mutating = cmd in MUTATORS or (cmd in READ_ONLY and write_capable(cmd, others, git))
    if not detail and mutating:
        for token in others:
            if any(c.is_ancestor_of(p) for p in ctx.resolve(token)) or ctx.glob_hit(
                token, c.GLOB_SAMPLES_WRITE + c.GLOB_SAMPLES_READ, ancestors=True
            ):
                detail = f"{token} contient un chemin protégé"
                break
    if not detail:
        return None
    if cmd in READ_ONLY and not write_capable(cmd, others, git):
        return None
    label = cmd or "affectation de variable"
    return (
        f"« {label} » pourrait écrire, déplacer ou changer les droits "
        f"d'un chemin protégé ({detail})"
    )


def _grep_paths(args: list[str]) -> list[str]:
    """Arguments of a grep-like command that name files (the search pattern is skipped)."""
    positional: list[str] = []
    named: list[str] = []
    pattern_given, i = False, 0
    while i < len(args):
        arg, low = args[i], args[i].lower()
        if arg == "--":
            positional.extend(args[i + 1 :])
            break
        if _ps_param(low, "-pattern", 4):
            pattern_given, i = True, i + 2
            continue
        if low in ("-path", "-literalpath", "-lp", "-pspath"):
            named.extend(args[i + 1 : i + 2])
            i += 2
            continue
        if arg in GREP_VALUE_OPTS:
            pattern_given |= arg in ("-e", "-f", "--regexp", "--file")
            i += 2
            continue
        if arg.startswith(("--regexp=", "--file=")):
            pattern_given = True
        elif not arg.startswith("-"):
            positional.append(arg)
        i += 1
    return named + (positional if pattern_given else positional[1:])


def check_secret_read(
    seg: Segment,
    tokens: list[str],
    cmd_index: int | None,
    cmd: str,
    ctx: Context,
    git: GitCall | None,
) -> str | None:
    if cmd in SECRET_READ_EXEMPT:
        return None
    if git is not None and (
        git.sub in ("status", "check-ignore")
        or (
            git.sub == "commit"
            and not any(a in ("-F", "--file") or a.startswith("--file=") for a in git.args)
        )
    ):
        return None
    args = tokens[cmd_index + 1 :] if cmd_index is not None else tokens
    paths = None
    if git is not None and git.sub == "grep":
        paths = _grep_paths(git.args)
    elif cmd in GREP_LIKE or cmd in ("select-string", "sls", "findstr"):
        paths = _grep_paths(args)
    if paths is not None:
        scanned = [*tokens[: cmd_index or 0], *paths, *seg.redirects]
        text = " ".join(scanned) + "\n" + seg.heredoc
    else:
        scanned = [t for i, t in enumerate(tokens) if i != cmd_index] + seg.redirects
        text = seg.raw + "\n" + seg.heredoc
    text = text.replace("\\", "/")
    if _ENV_FILE.search(text) or _SECRETS_DIR.search(text):
        return "lecture d'un fichier .env ou du dossier secrets/ interdite (R6)"
    for token in scanned:
        if any(c.read_protection_reason(p) for p in ctx.resolve(token)):
            return "lecture d'un fichier .env ou du dossier secrets/ interdite (R6)"
        if ctx.glob_hit(token, c.GLOB_SAMPLES_READ):
            return f"le motif {token} couvre .env ou secrets/ (R6)"
    return None


def _recursive_grep(cmd: str, args: list[str]) -> bool:
    if cmd == "rg":
        return any(
            a in ("--hidden", "-.", "--unrestricted")
            or a.startswith("--no-ignore")
            or (_SHORT_CLUSTER.match(a) and "u" in a)
            for a in args
        )
    return any(
        a in ("--recursive", "--dereference-recursive", "--directories=recurse")
        or (_SHORT_CLUSTER.match(a) and ("r" in a[1:] or "R" in a[1:]))
        for a in args
    ) or ("-d" in args and "recurse" in args)


def check_recursive_read(
    seg: Segment, args: list[str], cmd: str, ctx: Context, segments: list[Segment]
) -> str | None:
    hint = (
        "lecture récursive qui inclurait .env ou secrets/ (R6) : utiliser l'outil Grep ou git grep"
    )
    others = [basename(command_word(s.tokens)[1]) for s in segments if s is not seg]
    others += [basename(s.tokens[0]) for s in segments if s is not seg and s.tokens]
    paths: list[str] | None = None
    if cmd in GREP_LIKE and _recursive_grep(cmd, args):
        paths = _grep_paths(args) or ["."]
    elif cmd == "findstr" and any(a.lower() == "/s" for a in args):
        files = [a for a in args if not a.startswith("/")]
        files = files if any(a.lower().startswith("/c:") for a in args) else files[1:]
        if any(fnmatch.fnmatch(name, pattern) for pattern in files for name in (".env", "key")):
            return hint
        return None
    elif cmd == "find" and (any(a in FIND_EXEC for a in args) or "xargs" in others):
        paths = []
        for arg in args:
            if arg.startswith(("-", "(", "!")):
                break
            paths.append(arg)
        paths = paths or ["."]
    elif (
        ctx.powershell
        and cmd in ("get-childitem", "gci", "dir", "ls")
        and any(_ps_param(a, "-recurse") for a in args)
        and any(name in PS_CONTENT_READERS for name in others)
    ):
        paths = [a for a in args if not a.startswith("-")] or ["."]
    if paths is None:
        return None
    for path in paths:
        resolved = ctx.resolve(path)
        if any(c.is_ancestor_of(p, c.READ_SENSITIVE_LOCATIONS) for p in resolved) or any(
            c.read_protection_reason(p) for p in resolved
        ):
            return hint
        if ctx.glob_hit(path, c.GLOB_SAMPLES_READ, ancestors=True):
            return hint
    return None


def check_nested(seg: Segment, args: list[str], cmd: str, ctx: Context) -> str | None:
    """Recurse into `bash -c`, `pwsh -Command`, `cmd /c`, eval / Invoke-Expression."""
    if cmd in SHELLS:
        for index, arg in enumerate(args):
            if _SHORT_CLUSTER.match(arg) and "c" in arg[1:]:
                inner = args[index + 1] if index + 1 < len(args) else ""
                return analyse(inner, False, ctx.cwd, ctx.depth + 1)
        if not [a for a in args if not a.startswith("-")]:
            if seg.heredoc:
                return analyse(seg.heredoc, False, ctx.cwd, ctx.depth + 1)
            if seg.piped:
                return "flux envoyé à un shell : contenu non analysable, refus par précaution"
    elif cmd in PS_SHELLS:
        for arg in args:
            low = arg.lower()
            if low.startswith("-e") and (low in ("-e", "-ec") or "-encodedcommand".startswith(low)):
                return "PowerShell -EncodedCommand : contenu non analysable, refus par précaution"
        for index, arg in enumerate(args):
            if _ps_param(arg, "-command"):
                return analyse(" ".join(args[index + 1 :]), True, ctx.cwd, ctx.depth + 1)
            if _ps_param(arg, "-file"):
                return None
        positional = [a for a in args if not a.startswith("-")]
        if positional:
            return analyse(" ".join(positional), True, ctx.cwd, ctx.depth + 1)
        if seg.piped:
            return "flux envoyé à PowerShell : contenu non analysable, refus par précaution"
    elif cmd == "cmd":
        for index, arg in enumerate(args):
            if arg.lower() in ("/c", "/k", "/r"):
                return analyse(" ".join(args[index + 1 :]), True, ctx.cwd, ctx.depth + 1)
    elif cmd in EVALUATORS:
        inner = " ".join(a for a in args if not _ps_param(a, "-command"))
        if "$" in inner or "…" in inner:
            return "évaluation d'une commande dynamique : non analysable, refus par précaution"
        return analyse(inner, ctx.powershell or cmd != "eval", ctx.cwd, ctx.depth + 1)
    elif cmd in INTERPRETERS and seg.piped and not [a for a in args if not a.startswith("-")]:
        return "flux envoyé à un interpréteur : contenu non analysable, refus par précaution"
    return None


def update_cwd(cmd: str, args: list[str], ctx: Context) -> None:
    if cmd == "popd":
        ctx.cwd = None
    if cmd not in ("cd", "set-location", "sl", "chdir", "pushd"):
        return
    targets = [a for a in args if not a.startswith("-") or a == "-"]
    if not targets or targets[0] in ("-", "~") or is_dynamic(targets[0]):
        ctx.cwd = None
        return
    target = targets[0]
    absolute = target.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", target)
    if ctx.cwd is None and not absolute:
        return
    ctx.cwd = c.normalise(target, ctx.cwd)


def check_segment(seg: Segment, ctx: Context, segments: list[Segment]) -> str | None:
    tokens = seg.tokens
    if _HOOK_BYPASS_ENV.search(seg.raw) and ctx.powershell:
        return "variable d'environnement qui désactive les hooks (R6) : interdite"
    if (
        ctx.powershell
        and len(tokens) >= 2
        and tokens[0].startswith("$")
        and tokens[1].endswith("=")
    ):
        tokens = tokens[2:]  # `$x = <expression>`: analyse the expression
        seg = Segment(seg.raw, tokens, seg.redirects, seg.heredoc, seg.piped)
    cmd_index, cmd, assignments = command_word(tokens)
    args = tokens[cmd_index + 1 :] if cmd_index is not None else []
    git = parse_git(args, ctx) if cmd == "git" else None
    checks = (
        lambda: check_nested(seg, args, cmd, ctx),
        lambda: check_recursive_delete(tokens, cmd, ctx.powershell),
        lambda: check_force_and_bypass(tokens, cmd, assignments),
        lambda: check_git(git) if git else None,
        lambda: check_protected_write(seg, tokens, cmd_index, cmd, ctx, git),
        lambda: check_secret_read(seg, tokens, cmd_index, cmd, ctx, git),
        lambda: check_recursive_read(seg, args, cmd, ctx, segments),
    )
    for check in checks:
        if reason := check():
            return reason
    update_cwd(cmd, args, ctx)
    return None


def analyse(command: str, powershell: bool, cwd: str | None, depth: int = 0) -> str | None:
    """Reason to refuse `command`, or None when no rule applies."""
    if depth > MAX_DEPTH:
        return "commande trop imbriquée pour être analysée : refus par précaution"
    scanner = Scanner(command, powershell).scan()
    for substitution in scanner.substitutions:
        if reason := analyse(substitution, powershell, cwd, depth + 1):
            return reason
    ctx = Context(powershell, depth, cwd)
    for seg in scanner.segments:
        if reason := check_segment(seg, ctx, scanner.segments):
            return reason
    return None


def main() -> None:
    hook_input = c.read_hook_input()
    tool_input = hook_input.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        c.deny(hook_input, str(tool_input), "commande absente ou illisible : refus par précaution")
    powershell = str(hook_input.get("tool_name", "")).lower() == "powershell"
    cwd = c.normalise(str(hook_input.get("cwd") or c.ROOT))
    if reason := analyse(command, powershell, cwd):
        c.deny(hook_input, command, reason)


if __name__ == "__main__":
    c.run_fail_closed(main)
