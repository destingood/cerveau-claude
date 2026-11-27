"""Secret environment variables (B228): Claude Code never reads their values.

The secrets of the interfaces (``config/interfaces.yaml``) live in the environment of the
service account that runs the bot and the API (``docs/procedure-live.md``, prerequisite 5).
Two layers keep them away from Claude Code:

- part B: Claude Code's settings (``.claude/settings.json``, at the repository root and in
  ``plateforme/``) set the approval-chain secrets (``MASKED_VARIABLES``) to an empty value, so
  every process Claude Code starts inherits them empty;
- part A, here: ``guard_shell`` refuses any command that would print or read the value of one of
  ``SECRET_VARIABLES``: whole-environment dumps (``printenv``, ``env``, ``export -p``,
  ``declare -x``, ``set``, ``Get-ChildItem env:``...), expansions (``$NAME``, ``${NAME}``,
  ``$env:NAME``, ``%NAME%``), the .NET, WMI and registry readers, ``/proc/*/environ``, ``ps e``
  and inline interpreter code that reads them.

Naming a variable as plain text (``git grep NAME``, ``echo NAME``, a commit message) stays
allowed: only reading its value is refused. Like the rest of the hooks this is a convenience: a
script written to a file and then run is not read. The masking, and later the Windows Credential
Manager (ADR-073, proposed), are the protections that hold.
"""

from __future__ import annotations

import fnmatch
import re

# Every secret listed in the comment of config/interfaces.yaml: their values are never read.
SECRET_VARIABLES = (
    "CERVEAU_TOTP_SECRET",
    "CERVEAU_API_TOKEN",
    "DISCORD_BOT_TOKEN",
    "NTFY_TOKEN",
    "NTFY_TOPIC",
)
# Blanked for every process Claude Code starts (settings `env`): the secrets that let one approve
# an N3 order or speak for the approval channel. The ntfy pair is kept, so that an alert raised by
# a command Claude Code runs (kill switch, budget) still reaches the user's phone (R4).
MASKED_VARIABLES = ("CERVEAU_TOTP_SECRET", "CERVEAU_API_TOKEN", "DISCORD_BOT_TOKEN")
# Code names of these variables in the repository: `os.environ[SECRET_ENV]` reads the secret too.
CODE_NAMES = (
    "SECRET_ENV",
    "TOKEN_ENV",
    "DISCORD_TOKEN_ENV",
    "API_TOKEN_ENV",
    "TOKEN_VARIABLE",
    "TOPIC_VARIABLE",
    "key_from_environment",
)

VALUE_REFUSAL = (
    "lecture de la valeur d'un secret d'environnement ({names}) interdite (R6, B228) : "
    "seuls le bot et l'API, sous leur compte de service, le lisent"
)
DUMP_REFUSAL = (
    "affichage de tout l'environnement interdit : il montrerait les secrets des approbations "
    "(R6, B228) ; nommer la variable voulue (printenv PATH, $env:PATH)"
)
INDIRECT_REFUSAL = (
    "expansion indirecte d'une variable (${!nom}) : valeur non analysable, refus par précaution "
    "(R6, B228)"
)

_NAMES = "|".join(SECRET_VARIABLES)
# $NAME, ${NAME}, ${NAME:-x}, ${#NAME}, $env:NAME, ${env:NAME}
_EXPANSION = re.compile(rf"\$\{{?[!#]?\s*(?:env:)?(?:{_NAMES})(?!\w)", re.IGNORECASE)
# cmd.exe: %NAME%, %NAME:~0,4%, !NAME! (delayed expansion)
_CMD_EXPANSION = re.compile(rf"[%!](?:{_NAMES})[%!:]", re.IGNORECASE)
_INDIRECT = re.compile(r"\$\{!\w+\}")
_PROC_ENVIRON = re.compile(r"/proc/[^\s'\"]*environ\b", re.IGNORECASE)
# The persistent user and machine variables, read straight from the registry or WMI.
_REGISTRY = re.compile(
    r"(?:hkcu|hkey_current_user)[:/]+environment\b|session manager/+environment\b"
    r"|\bwin32_environment\b|\bwmic\b[^\n]*\benvironment\b",
    re.IGNORECASE,
)
_DOTNET_ALL = re.compile(r"getenvironmentvariables\b", re.IGNORECASE)
_DOTNET_ONE = re.compile(r"getenvironmentvariable\s*\(\s*([^),]*)", re.IGNORECASE)
_LITERAL_NAME = re.compile(r"""\s*(['"])(\w+)\1\s*""")
_LAUNCHCTL = re.compile(r"\blaunchctl\s+(?:getenv|export)\b", re.IGNORECASE)
# The env: drive of PowerShell, also as a parameter value (`-Path:env:`).
_ENV_DRIVE = re.compile(r"(?:-\w+:)?env:[\\/]?([^\\/]*)", re.IGNORECASE)
# Inline interpreter code: a secret named next to an environment reader, or the whole environment.
_NAME_IN_CODE = re.compile(rf"(?:{_NAMES}|{'|'.join(CODE_NAMES)})", re.IGNORECASE)
_ENV_READER = re.compile(
    r"environ|getenv|process\.env|deno\.env|bun\.env|\$_(?:env|server)\b|%env\b", re.IGNORECASE
)
_ENV_READER_CASED = re.compile(r"\bENV\b")
_DUMP_IN_CODE = re.compile(
    r"\benviron\s*(?:\)|\.(?:items|values)\s*\()"
    r"|\bprocess\.env\s*(?:\)|;|$)"
    r"|(?:stringify|entries|values)\s*\(\s*process\.env\b"
    r"|%ENV\b|\bENV\.(?:to_h|to_a|each|inspect|map)\b|\b(?:p|pp|puts|print)\s*\(?\s*ENV\b"
    r"|\bgetenv\s*\(\s*\)|\$_(?:ENV|SERVER)\b",
    re.MULTILINE,
)
# Removing, testing or setting an env: entry does not show its value.
ENV_DRIVE_SAFE = frozenset(
    {
        "test-path", "remove-item", "ri", "del", "erase", "rm", "rd", "rmdir", "set-item", "si",
        "new-item", "ni", "clear-item", "cli",
    }
)  # fmt: skip


def _secret_reason() -> str:
    return VALUE_REFUSAL.format(names=", ".join(SECRET_VARIABLES))


def _is_secret(name: str) -> bool:
    return name.strip("'\"").upper() in SECRET_VARIABLES


def _covers_secret(pattern: str) -> bool:
    """Whether an env: name, possibly a wildcard, is empty or could name a secret."""
    name = pattern.strip("'\"").upper()
    return not name or any(fnmatch.fnmatchcase(secret, name) for secret in SECRET_VARIABLES)


def _basename(token: str) -> str:
    name = re.split(r"[\\/]", token.strip("'\""))[-1].lower()
    return name.removesuffix(".exe")


def check_text(command: str) -> str | None:
    """Reasons found in the whole command text, before it is split into segments."""
    text = command.replace("\\", "/")
    if _EXPANSION.search(command) or _CMD_EXPANSION.search(command):
        return _secret_reason()
    if _INDIRECT.search(command):
        return INDIRECT_REFUSAL
    if _PROC_ENVIRON.search(text) or _LAUNCHCTL.search(command):
        return DUMP_REFUSAL
    if _REGISTRY.search(text):
        return (
            "lecture des variables d'environnement enregistrées (registre, WMI) interdite : "
            "elle montrerait les secrets des approbations (R6, B228)"
        )
    if _DOTNET_ALL.search(command):
        return DUMP_REFUSAL
    for match in _DOTNET_ONE.finditer(command):
        literal = _LITERAL_NAME.fullmatch(match.group(1))
        if literal is None or _is_secret(literal.group(2)):
            return _secret_reason()
    return None


def _positional(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith(("-", "+"))]


def _dump_command(cmd: str, cmd_index: int | None, tokens: list[str], args: list[str]) -> bool:
    """`env`, `printenv`, `export -p`, `declare -x`, `set`...: the whole environment shown."""
    if cmd_index is None:  # `env`, `env -0`, `sudo env`: a wrapper with nothing to run
        return any(_basename(t) == "env" for t in tokens)
    options = [a for a in args if a.startswith(("-", "+"))]
    positional = _positional(args)
    if cmd == "printenv":
        return not positional
    if cmd == "export":
        return not args or any(re.fullmatch(r"-\w*p\w*", a) for a in options)
    if cmd in ("declare", "typeset"):
        functions_only = any(set(a[1:]) & {"f", "F"} for a in options)
        return not positional and not functions_only
    if cmd == "set":  # bash `set`, cmd.exe `set` and `set PREFIX` list variables with values
        if not args:
            return True
        first = args[0]
        prefix = first.upper()
        return (
            not first.startswith(("-", "+", "/"))
            and "=" not in first
            and any(secret.startswith(prefix) for secret in SECRET_VARIABLES)
        )
    if cmd == "ps" and args:  # BSD options `ps e`, `ps auxe`: the environment of every process
        return bool(re.fullmatch(r"[A-Za-z]*e[A-Za-z]*", args[0]))
    return False


def check_segment(
    raw: str,
    heredoc: str,
    tokens: list[str],
    cmd_index: int | None,
    cmd: str,
    interpreter: bool,
) -> str | None:
    """Reasons found in one simple command (`cmd` is its lower-case command word)."""
    args = tokens[cmd_index + 1 :] if cmd_index is not None else []
    if _dump_command(cmd, cmd_index, tokens, args):
        return DUMP_REFUSAL
    if cmd == "printenv" and any(_is_secret(a) or "$" in a for a in _positional(args)):
        return _secret_reason()
    if (
        cmd in ("declare", "typeset")
        and any(re.fullmatch(r"-\w*p\w*", a) for a in args)
        and any(_is_secret(a.split("=", 1)[0]) or "$" in a for a in _positional(args))
    ):
        return _secret_reason()
    if cmd not in ENV_DRIVE_SAFE:
        for index, token in enumerate(tokens):
            drive = _ENV_DRIVE.fullmatch(token.strip("'\""))
            if index != cmd_index and drive and _covers_secret(drive.group(1)):
                return _secret_reason()
    if interpreter:
        code = raw + "\n" + heredoc
        reads = _ENV_READER.search(code) or _ENV_READER_CASED.search(code)
        if (reads and _NAME_IN_CODE.search(code)) or _DUMP_IN_CODE.search(code):
            return _secret_reason()
    return None
