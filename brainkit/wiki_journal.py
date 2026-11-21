"""Journal du wiki : `journal/<PC>/AAAA-MM.md`, l'historique des sessions et des observations datées, mois par mois,
un dossier par PC (les mois d'avant la 8.31.0 dans `journal/ancien/`), et la lecture des sessions des autres PC.

Découpé de wiki.py le 21/11/2026 (étape 8 du plan), sans changer le comportement : ces noms restent accessibles
depuis wiki (`wiki.write_journal`, `wiki.other_sessions`…)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import wikistore as ws
from .common import STATE_DIR, log, now_iso, read_json, short, write_json, write_text
from .wiki import DAYS, JOURNAL_DIR, MONTHS, pc_name


def journal_pages(sessions=True, keep=None) -> dict:
    """L'historique du cerveau (sa mémoire épisodique) en pages : sessions passées et observations datées, archivées
    comprises, mois par mois → {« journal/AAAA-MM.md »: texte}. Généré : rien ne s'y écrit à la main.
    sessions=False / keep(observation) → bool : la part publique (cerveau commun) — observations choisies seulement."""
    import datetime as _dt
    from . import journal as jr
    from . import observations as ob
    from .privacy import mask
    days = {}

    def day(d):
        return days.setdefault(d, {"s": [], "o": {}})

    for sess in (jr.load().get("sessions") or {}).values() if sessions else ():
        d = str(sess.get("end") or sess.get("start") or "")[:10]
        if len(d) == 10 and (sess.get("title") or sess.get("first") or sess.get("brief")):
            day(d)["s"].append(sess)
    olds = []
    try:
        with open(ob.ARCHIVE_FILE, encoding="utf-8") as fh:  # observations condensées par le rêve : les originales
            olds = [json.loads(x) for x in fh if x.strip()]
    except (OSError, ValueError):
        olds = []
    for o in olds + list(ob.load().get("obs") or []):
        d = str(o.get("at") or "")[:10]
        if len(d) == 10 and o.get("t") and (keep is None or keep(o)):
            day(d)["o"][o.get("id") or f"{o['at']}{o['t']}"] = o
    months = {}
    for d in sorted(days):
        months.setdefault(d[:7], []).append(d)
    pages = {}
    for m, ds in months.items():
        mo = int(m[5:7])
        out = [f"# 🗓️ Journal — {MONTHS[mo - 1]} {m[:4]}", "",
               "_Généré par le cerveau à partir de ses sessions et de ses observations datées : réécrit en fin de "
               "session, ne pas modifier. 💬 session · 🔴 décision, blocage · 🟡 avancée · 🟢 détail._", ""]
        for d in ds:
            date = _dt.date.fromisoformat(d)
            out += [f"## {DAYS[date.weekday()]} {date.day} {MONTHS[mo - 1]}", ""]
            for sess in sorted(days[d]["s"], key=lambda x: str(x.get("end") or "")):
                bits = [f"💬 {str(sess.get('end') or '')[11:16]} « {short(sess.get('title') or sess.get('first') or sess.get('brief'), 90)} »"]
                if sess.get("project"):
                    bits.append(f"projet {sess['project']}")
                if sess.get("last") and sess.get("last") != sess.get("first"):
                    bits.append(f"dernière demande : « {short(sess['last'], 140)} »")
                if sess.get("edits"):
                    names = ", ".join(os.path.basename(str(e)) for e in sess["edits"][:5])
                    bits.append(f"modifiés : {names}" + (f" +{len(sess['edits']) - 5}" if len(sess["edits"]) > 5 else ""))
                out.append("- " + " — ".join(bits))
            for o in sorted(days[d]["o"].values(), key=lambda x: str(x.get("at") or "")):
                tail = f" · {o['proj']}" if o.get("proj") else ""
                out.append(f"- {ob.PRIO.get(o.get('p', 2), '🟡')} {str(o.get('at') or '')[11:16]} {o['t']}{tail}")
            out.append("")
        pages[f"{JOURNAL_DIR}/{m}.md"] = mask("\n".join(out).rstrip() + "\n")[0]
    return pages


# Journal du wiki, un dossier par PC : journal/<PC>/AAAA-MM.md. Avant la 8.31.0, un seul journal/AAAA-MM.md refait par
# chaque PC à partir de ses propres sessions : GitHub gardait le mois du dernier PC synchronisé, et les mois changeaient
# d'un PC à l'autre. Chaque PC n'écrit plus que son dossier : deux PC n'écrivent jamais le même fichier.
MONTH_RX = re.compile(r"^(\d{4})-(\d{2})\.md$")


JOURNAL_PC_FILE = STATE_DIR / "wiki-pc.json"  # nom de ce PC dans journal/, choisi une fois (propre à ce PC)


OLD_JOURNAL = "ancien"  # journal/ancien/AAAA-MM.md : les mois d'avant la 8.31.0, tous PC confondus, figés


CLOUD_JOURNAL = "cloud"  # sessions cloud (conteneur jetable) : un seul dossier, fusionné au lieu d'être réécrit


SESSION_RX = re.compile(r"^- 💬 (\d{2}:\d{2}) « (.*) »((?: — .*)?)$")


DAY_RX = re.compile(r"^## \S+ (\d{1,2}) ")


def _cloud() -> bool:
    return bool(os.environ.get("CLAUDE_CODE_REMOTE") or os.environ.get("CERVEAU_CLOUD"))


def journal_pc(root=None, create=True):
    """Dossier de ce PC dans journal/ : choisi une fois puis gardé (le nom réseau d'un Mac change parfois). Un dossier
    du même nom déjà dans le wiki vient d'un autre PC (même nom) : suffixe -2, -3… Session cloud : « cloud ».
    create=False : None tant qu'il n'est pas choisi."""
    if _cloud():
        return CLOUD_JOURNAL
    st = read_json(JOURNAL_PC_FILE, {}) or {}
    if st.get("pc") or not create:
        return st.get("pc")
    base = pc_name()
    if base in (OLD_JOURNAL, CLOUD_JOURNAL):
        base = f"PC-{base}"
    name, i, root = base, 2, Path(root or ws.root() or "")
    while str(root) and (root / JOURNAL_DIR / name).is_dir() and i < 100:
        name, i = f"{base}-{i}", i + 1
    write_json(JOURNAL_PC_FILE, {"pc": name, "le": now_iso()})
    return name


def _sections(text):
    """Un mois du journal → (lignes d'en-tête, {titre du jour: lignes}, ordre des jours)."""
    head, days, order, cur = [], {}, [], None
    for ln in text.splitlines():
        if ln.startswith("## "):
            cur = ln
            if cur not in days:
                days[cur] = []
                order.append(cur)
        elif cur is None:
            head.append(ln)
        elif ln.strip():
            days[cur].append(ln)
    return head, days, order


def _merge_month(ours, theirs) -> str:
    """Deux versions d'un même mois du journal : chaque jour garde ses lignes des deux côtés, jamais rien d'effacé
    (jours rangés par date)."""
    head, days, order = _sections(ours)
    _, more, order2 = _sections(theirs)
    for d in order2:
        if d not in days:
            days[d], order = [], order + [d]
        days[d] += [ln for ln in more[d] if ln not in days[d]]

    def num(d):
        m = DAY_RX.match(d)
        return int(m.group(1)) if m else 99
    order.sort(key=num)
    out = "\n".join(head).rstrip()
    for d in order:
        out += "\n\n" + d + "\n\n" + "\n".join(days[d])
    return out.strip() + "\n"


def _migrate_journal(root) -> list:
    """journal/AAAA-MM.md (avant la 8.31.0) → journal/ancien/AAAA-MM.md, qui ne sera plus jamais réécrit : rien de ce
    qu'il contient ne se perd. Déjà là (un autre PC a migré, ou un PC pas encore à jour a réécrit le mois) : les deux
    versions fusionnées. → mois déplacés."""
    jdir = Path(root) / JOURNAL_DIR
    moved = []
    for p in sorted(jdir.glob("*.md")) if jdir.is_dir() else []:
        if not MONTH_RX.match(p.name):
            continue
        dest = jdir / OLD_JOURNAL / p.name
        try:
            old = p.read_text(encoding="utf-8")
            have = dest.read_text(encoding="utf-8") if dest.is_file() else None
            if have != old:
                write_text(dest, old if have is None else _merge_month(have, old))
            p.unlink()
        except OSError as exc:
            log(f"wiki : journal {p.name} pas déplacé : {exc!r}")
            continue
        moved.append(p.name)
    if moved:
        log(f"wiki : journal d'avant la 8.31.0 rangé dans {JOURNAL_DIR}/{OLD_JOURNAL}/ ({', '.join(moved)})")
    return moved


def write_journal(root=None) -> int:
    """journal/<ce PC>/ à jour dans le wiki (seuls les mois qui changent sont réécrits ; en session cloud, fusionnés avec
    ceux des sessions cloud d'avant). Range d'abord les mois d'avant la 8.31.0 dans journal/ancien/. → mois écrits."""
    root = Path(root or ws.root() or "")
    if not str(root) or not (root / ws.MARKER).is_file():
        return 0
    _migrate_journal(root)
    pages = journal_pages()
    if not pages:
        return 0
    pc, n = journal_pc(root), 0
    for rel, text in pages.items():
        p = root / JOURNAL_DIR / pc / rel.rsplit("/", 1)[-1]
        text = text.replace("# 🗓️ Journal — ", f"# 🗓️ Journal — {pc} — ", 1)
        try:
            have = p.read_text(encoding="utf-8")
        except OSError:
            have = None
        if have is not None and pc == CLOUD_JOURNAL:
            text = _merge_month(have, text)
        if have == text:
            continue
        write_text(p, text)
        n += 1
    return n


def journal_months(root=None) -> list:
    """Dossiers du journal du wiki → [(dossier, dernier mois « journal/<dossier>/AAAA-MM »)], ce PC d'abord."""
    root = Path(root or ws.root() or "")
    jdir = root / JOURNAL_DIR if str(root) else None
    if not jdir or not jdir.is_dir():
        return []
    me, out = journal_pc(root, create=False), []
    for d in sorted(x for x in jdir.iterdir() if x.is_dir()):
        months = sorted(p.stem for p in d.glob("*.md") if MONTH_RX.match(p.name))
        if months:
            out.append((d.name, f"{JOURNAL_DIR}/{d.name}/{months[-1]}"))
    return sorted(out, key=lambda x: (x[0] != me, x[0] == OLD_JOURNAL, x[0].lower()))


def other_sessions(root=None, known=()) -> list:
    """Sessions des autres PC (et des mois d'avant la 8.31.0), lues dans journal/ du wiki, au format du journal local
    (journal.session_line) : `brain q` et la page Cerveau les montrent avec celles de ce PC. Celles de ce PC n'y sont
    pas reprises (son journal local est plus complet) ; `known` : sessions déjà connues (pas de doublon)."""
    root = Path(root or ws.root() or "")
    jdir = root / JOURNAL_DIR if str(root) else None
    if not jdir or not jdir.is_dir():
        return []
    me = journal_pc(root, create=False)
    seen = {(str(s.get("end") or "")[:16].replace(" ", "T"), short(s.get("title") or s.get("first") or s.get("brief"), 90))
            for s in known}
    out = []
    for p in sorted(jdir.glob("*/*.md")):
        m = MONTH_RX.match(p.name)
        pc = p.parent.name
        if not m or pc == me:
            continue
        day = None
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            d = DAY_RX.match(ln)
            if d:
                day = int(d.group(1))
                continue
            s = SESSION_RX.match(ln)
            if not s or not day:
                continue
            end = f"{m.group(1)}-{m.group(2)}-{day:02d}T{s.group(1)}"
            if (end, s.group(2)) in seen:
                continue
            seen.add((end, s.group(2)))
            label = "avant la 8.31" if pc == OLD_JOURNAL else pc
            row = {"id": f"{pc}/{end}/{i}", "end": end + ":00", "title": f"[{label}] {s.group(2)}", "pc": pc}
            for bit in s.group(3).split(" — ")[1:]:
                if bit.startswith("projet "):
                    row["project"] = bit[7:].strip()
                elif bit.startswith("dernière demande : « ") and bit.endswith("»"):
                    row["last"] = bit[len("dernière demande : « "):-1].strip()
                elif bit.startswith("modifiés : "):
                    row["edits"] = [x.strip() for x in bit[11:].split(",") if x.strip() and not x.strip().startswith("+")]
            out.append(row)
    return out
