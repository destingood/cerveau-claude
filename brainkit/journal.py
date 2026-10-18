"""Journal des sessions (coût : zéro token) — extrait des transcripts Claude Code le titre de la session,
la 1re et la dernière demande, le nombre d'actions et les fichiers modifiés. Sert à « reprendre où on en était »."""
from __future__ import annotations

import json
import os
import re

from .common import CLAUDE_HOME, JOURNAL_FILE, FileLock, fmt_date, fold, is_scratch, read_json, short, write_json

PASTE_RE = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content>", re.S)
BLOCK_RE = re.compile(r"<(system-reminder|local-command-stdout|local-command-stderr|ide_[a-z_]+)[^>]*>.*?</\1>", re.S)
CMD_RE = re.compile(r"<command-(?:name|message|args)>(.*?)</command-(?:name|message|args)>", re.S)
TAG_RE = re.compile(r"</?[a-zA-Z][\w\-]*(?:\s[^<>]*)?>")
AUTO_RE = re.compile(r"^(None of the sessions you started|Background \(from the session|<side-sessions|"
                     r"The user hasn't heard|\[Request interrupted|This session is being continued from)", re.I)
# Sections du résumé de compaction de Claude Code (« 8. Current Work », « 9. Optional Next Step »…)
SUMMARY_HEAD_RE = re.compile(r"^\s*(?:#+\s*)?(?:\d+\.\s*)?(?:\*\*)?\s*(Primary Request|Pending Tasks|Current Work|"
                             r"Optional Next Step)\b", re.I | re.M)
CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SAVE_RE = re.compile(r"brain\.py[\"']?\s+(?:add|save|retiens|edit|obs|observe|wiki\s+(?:add|log))\b")
OBS_RE = re.compile(r"brain\.py[\"']?\s+(?:obs|observe)\b[^|;&\n]*?[\"']")  # observations notées (pas une simple lecture)
LOCK = JOURNAL_FILE.with_name("journal.lock")


def clean_prompt(text, n=200) -> str:
    text = BLOCK_RE.sub(" ", str(text))
    text = PASTE_RE.sub(lambda m: " [collé] " + short(m.group(1).strip("`\n "), 80) + " ", text)
    text = CMD_RE.sub(lambda m: m.group(1) + " ", text)
    text = TAG_RE.sub(" ", text)
    return short(re.sub(r"^[\s`\"'#]+", "", text), n)


def new_state() -> dict:
    return {"offset": 0, "tools": 0, "edits": [], "prompts": 0, "first": None, "last": None, "title": None,
            "brief": None, "cwd": None, "start": None, "end": None, "last_save_tools": 0, "last_obs_tools": 0,
            "recent": [], "answer": None, "summary": None}


def parse_transcript(path, state=None) -> dict:
    """Lecture incrémentale du transcript (reprend à state['offset'])."""
    st = new_state()
    if state:
        st.update(state)
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return st
    if size < st["offset"]:
        st = new_state()
    try:
        fh = open(path, "rb")
    except OSError:
        return st
    with fh:
        fh.seek(st["offset"])
        for raw in fh:
            if not raw.endswith(b"\n"):
                break  # ligne en cours d'écriture
            st["offset"] += len(raw)
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                _consume(st, obj)
    return st


def _consume(st, o):
    typ = o.get("type")
    ts = o.get("timestamp")
    if ts:
        st["start"] = st["start"] or ts
        st["end"] = ts
    if not st["cwd"] and o.get("cwd"):
        st["cwd"] = o["cwd"]
    if typ == "custom-title" and o.get("customTitle"):
        st["title"] = o["customTitle"]
        return
    if o.get("isSidechain"):
        return
    if typ == "user" and not o.get("isMeta"):
        content = (o.get("message") or {}).get("content")
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                return
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if not isinstance(content, str) or not content.strip():
            return
        if o.get("isCompactSummary"):  # résumé de compaction (parfois marqué « human ») : où on en était, pas une demande
            st["summary"] = summary_part(content, limit=800)
            return
        text = clean_prompt(content)
        if not text:
            return
        turn = o.get("turnOrigin")  # app desktop : "human" = tapé par l'utilisateur, "sdk" = message automatique
        human = turn == "human" if turn else (o.get("origin") or {}).get("kind", "human") == "human"
        if human and not AUTO_RE.match(text):
            st["prompts"] += 1
            st["first"] = st["first"] or text
            st["last"] = text
            recent = st.setdefault("recent", [])  # derniers messages tapés (capture assistée en fin de tâche)
            recent.append({"t": clean_prompt(content, 300), "i": st["tools"]})
            del recent[:-15]
        elif text.startswith("Background (from") and not st.get("brief"):
            st["brief"] = short(text.split(":", 1)[-1], 200)  # consigne d'une session lancée par une autre
    elif typ == "assistant":
        for b in (o.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text" and not o.get("isApiErrorMessage"):
                txt = (b.get("text") or "").strip()
                if len(txt) >= 40 and not SYSMSG_RE.search(txt[:200]):
                    st["answer"] = _answer(txt)  # dernière vraie réponse : « où on en est » pour la session suivante
                _scan(st, txt)
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            st["tools"] += 1
            name, inp = b.get("name", ""), b.get("input") or {}
            _scan(st, json.dumps(inp, ensure_ascii=False)[:3000])
            if name in EDIT_TOOLS:
                fp = inp.get("file_path") or inp.get("notebook_path")
                if fp and fp not in st["edits"] and len(st["edits"]) < 40:
                    st["edits"].append(fp)
            elif name in ("Bash", "PowerShell") and SAVE_RE.search(str(inp.get("command", ""))):
                st["last_save_tools"] = st["tools"]
                if OBS_RE.search(str(inp.get("command", ""))):
                    st["last_obs_tools"] = st["tools"]


def _scan(st, text):
    """Ce que Claude a écrit ou fait depuis la dernière lecture (transitoire, jamais enregistré) : sert à repérer
    les souvenirs réellement utilisés (montré ≠ utilisé)."""
    if text:
        buf = st.setdefault("_scan", [])
        buf.append(text[:4000])
        while sum(len(x) for x in buf) > 30000:
            buf.pop(0)


SYSMSG_RE = re.compile(r"hit your (?:session|usage|weekly)? ?limit|usage limit|session limit|API Error|Request was aborted|"
                       r"Prompt is too long|Credit balance|rate limit|Interrupted by user|No response requested", re.I)


def _answer(text, n=320) -> str:
    """Réponse de Claude → une ligne lisible (sans blocs de code, titres, gras ni tableaux)."""
    text = re.sub(r"```.*?```", " ", str(text), flags=re.S)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)
    text = re.sub(r"[#*_`>|]+", " ", text)
    return short(" ".join(text.split()), n)


def load() -> dict:
    j = read_json(JOURNAL_FILE, None)
    if not isinstance(j, dict) or not isinstance(j.get("sessions"), dict):
        j = {"sessions": {}}
    return j


def summary_part(text, start="current work", stop=None, limit=1500) -> str:
    """Morceau d'un résumé de compaction : de la section `start` jusqu'à la section `stop` (exclue), sans blocs de
    code. Sans sections reconnues : la fin du résumé (là où il décrit le travail en cours)."""
    text = str(text or "")
    heads = list(SUMMARY_HEAD_RE.finditer(text))
    part = None
    for i, m in enumerate(heads):
        if m.group(1).lower() == start:
            end = next((h.start() for h in heads[i + 1:] if stop and h.group(1).lower() == stop), len(text))
            part = text[m.start():end]
            break
    if part is None:
        part = text[-limit:]
    return short(" ".join(CODE_BLOCK_RE.sub(" ", part).split()), limit)


def last_compact_summary(path, tail=2_000_000):
    """Dernier résumé de compaction d'un transcript, lu par la fin → (texte, horodatage) ou (None, None)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - tail))
            lines = fh.read().splitlines()
    except (OSError, TypeError, ValueError):
        return None, None
    for raw in reversed(lines):
        if b"isCompactSummary" not in raw:
            continue
        try:
            o = json.loads(raw)
        except Exception:
            continue
        if not isinstance(o, dict) or not o.get("isCompactSummary"):
            continue
        content = (o.get("message") or {}).get("content")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(content, str) and content.strip():
            return content, o.get("timestamp")
    return None, None


def upsert(session_id, st, project_id, keep=500):
    if not session_id or not st or not (st.get("prompts") or st.get("brief")):
        return
    from .privacy import redact_contacts
    clean = lambda v: redact_contacts(v) if v else v  # noqa: E731 — jamais de coordonnées de tiers ni de secret au journal
    st = dict(st, title=clean(st.get("title")), first=clean(st.get("first")), last=clean(st.get("last")),
              brief=clean(st.get("brief")), answer=clean(st.get("answer")), summary=clean(st.get("summary")))
    entry = {
        "id": session_id, "project": project_id, "cwd": st.get("cwd"), "title": st.get("title"),
        "first": st.get("first"), "last": st.get("last"), "brief": st.get("brief"), "prompts": st.get("prompts", 0),
        "tools": st.get("tools", 0), "edits": list(st.get("edits") or [])[:40],
        "saved": bool(st.get("last_save_tools")), "start": st.get("start"), "end": st.get("end"),
        "answer": st.get("answer"), "summary": st.get("summary"),
    }
    with FileLock(LOCK, timeout=3):
        j = load()
        j["sessions"][session_id] = entry
        if len(j["sessions"]) > keep:
            ordered = sorted(j["sessions"].values(), key=lambda s: s.get("end") or "")
            for s in ordered[: len(ordered) - keep]:
                j["sessions"].pop(s["id"], None)
        write_json(JOURNAL_FILE, j)


def recent(project=None, limit=3, exclude=None, journal=None) -> list:
    j = journal or load()
    items = [s for s in j["sessions"].values()
             if s.get("id") != exclude and (project is None or s.get("project") == project)]
    items.sort(key=lambda s: s.get("end") or "", reverse=True)
    return items[:limit]


def last_seen_by_project(journal=None) -> dict:
    j = journal or load()
    out = {}
    for s in j["sessions"].values():
        p = s.get("project")
        if p and (s.get("end") or "") > out.get(p, ""):
            out[p] = s.get("end") or ""
    return out


def session_line(s) -> str:
    title = s.get("title") or s.get("first") or s.get("brief") or "?"
    parts = [f"- {fmt_date(s.get('end'))} « {short(title, 70)} »"]
    if s.get("last") and (s.get("last") != s.get("first") or s.get("title")):
        parts.append(f"dernière demande : « {short(s['last'], 110)} »")
    elif s.get("brief"):
        parts.append(f"lancée par une autre session : « {short(s['brief'], 110)} »")
    if s.get("edits"):
        names = ", ".join(os.path.basename(e) for e in s["edits"][:4])
        more = f" +{len(s['edits']) - 4}" if len(s["edits"]) > 4 else ""
        parts.append(f"modifiés : {names}{more}")
    return " — ".join(parts)


def transcripts() -> list:
    root = CLAUDE_HOME / "projects"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)


def search_transcripts(query, limit=8):
    """Cherche dans le texte des sessions passées (messages de l'utilisateur et réponses de Claude)."""
    from .common import STOPWORDS
    terms = [w for w in re.findall(r"[a-z0-9]+", fold(query)) if len(w) >= 3 and w not in STOPWORDS]
    if not terms:
        return []
    meta = load()["sessions"]
    out = []
    for path in transcripts():
        sid = os.path.splitext(os.path.basename(path))[0]
        count, snippet, date = 0, "", None
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"type":"user"' not in line and '"type":"assistant"' not in line:
                        continue
                    low = fold(line)
                    if not all(t in low for t in terms):
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("isSidechain"):
                        continue
                    content = (o.get("message") or {}).get("content")
                    if isinstance(content, list):
                        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                    text = " ".join(str(content or "").split())
                    ftext = fold(text)
                    if not text or not all(t in ftext for t in terms):
                        continue
                    count += 1
                    date = o.get("timestamp") or date
                    if not snippet:
                        i = ftext.find(terms[0])
                        snippet = short(text[max(0, i - 70): i + 110], 180)
        except OSError:
            continue
        if count:
            m = meta.get(sid, {})
            out.append({"id": sid, "count": count, "snippet": snippet, "date": date or m.get("end"),
                        "title": m.get("title") or m.get("first") or sid[:8], "project": m.get("project")})
    out.sort(key=lambda h: (h["date"] or ""), reverse=True)
    return out[:limit]


def backfill(brain) -> int:
    """Remplit le journal à partir de tous les transcripts existants."""
    count = 0
    for path in transcripts():
        st = parse_transcript(path)
        if not (st.get("prompts") or st.get("brief")):
            continue
        cwd = st.get("cwd")
        proj = brain.project_for_path(cwd) if cwd and not is_scratch(cwd) else None
        upsert(path.stem, st, proj["id"] if proj else None)
        count += 1
    return count
