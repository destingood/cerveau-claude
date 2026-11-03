"""Galaxy d'Uiverse.io (github.com/uiverse-io/galaxy, licence MIT, © 2023 Uiverse.io) : 3 802 éléments d'interface en
HTML + CSS ou en Tailwind, cherchés dans une copie locale, comparés en aperçu, puis sortis pour être intégrés à un site.

  python galaxy.py install                              copie locale (≈ 21 Mo), ou mise à jour si elle existe
  python galaxy.py search [mots…] [--cat C] [--css | --tailwind] [-n N]
  python galaxy.py show ID [ID…] [--full]               code complet et points à adapter
  python galaxy.py preview ID [ID…] [--sombre] [--out F]  page HTML + capture PNG pour les comparer côte à côte

ID : « auteur/nom » tel que l'affiche search (ex. 0xnihilism/pretty-fireant-33), son lien uiverse.io ou le chemin du
fichier. Copie locale : ~/.claude/galaxy, ou le dossier de la variable GALAXY_DIR. Bibliothèque standard seulement."""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/uiverse-io/galaxy"
ROOT = Path(os.environ.get("GALAXY_DIR") or Path.home() / ".claude" / "galaxy")
BIG = 25 * 1024  # au-delà, show demande --full : le plus gros élément (185 Ko) coûterait ≈ 50 000 tokens
TAILWIND = "https://cdn.tailwindcss.com"  # CDN officiel de Tailwind v3, l'époque des éléments (2023-2024)
BROWSERS = ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")  # casse ASCII, celle des balises
LINK = re.compile(r"uiverse\.io/([^/\s?#]+)/([\w-]+)")
LOADED = re.compile(r"""(?:src=["']|url\(["']?)https?://([\w.-]+)""")
HREF = re.compile(r"""href=["']https?://([\w.-]+)""")
FRAME = ('<!doctype html><meta charset="utf-8">{head}<style>html,body{{height:100%;margin:0}}'
         'body{{display:grid;place-items:center;font-family:system-ui,sans-serif}}</style>{body}')
ADVANCE = "<style>*,*::before,*::after{animation-delay:-.6s!important}</style>"
CARD = ('<figure><div class="box"><iframe sandbox="{sandbox}" loading="lazy" title="{id}" srcdoc="{doc}"></iframe>'
        '</div><figcaption>{i}. <a href="https://uiverse.io/{id}" target="_blank" rel="noopener">{id}</a>'
        ' · {cat} · {tech}</figcaption></figure>')
PAGE = """<!doctype html>
<html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Galaxy — aperçu</title>
<style>
body{{margin:24px;font:14px/1.4 system-ui,sans-serif;background:#f4f4f5;color:#18181b}}
body.dark{{background:#09090b;color:#e4e4e7}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #a1a1aa55;border-radius:12px;overflow:hidden;background:#fff}}
.dark figure{{background:#18181b}}
.box{{height:340px;resize:vertical;overflow:hidden}}
iframe{{display:block;width:100%;height:100%;border:0}}
figcaption{{padding:8px 12px;border-top:1px solid #a1a1aa55}}
a{{color:inherit}}
</style>
<body class="{mode}"><p><button onclick="document.body.classList.toggle('dark')">Fond clair / sombre</button>
{n} élément(s) de Galaxy (Uiverse.io, MIT) — un nom ouvre l'original, interactif, sur uiverse.io.</p>
<div class="grid">
{cards}
</div>
</html>
"""


# Le texte des éléments est téléchargé : il se découpe avec str.find et str.split, en temps linéaire. Les regex
# paresseuses d'avant (Tags:\s*(.*?)\s*(?:\*/|-->), /\*.*?\*/, <style[^>]*>(.*?)</style>, ([^{}]+)\{) repartaient
# jusqu'au bout du texte à chaque essai raté : 8,5 s pour « Tags: » suivi de 2 000 espaces, ×8 à chaque doublement.
def tags(text) -> list:
    """Les tags de l'en-tête « Tags: a, b, c », jusqu'au premier */ (CSS) ou --> (Tailwind) qui suit."""
    i = text.find("Tags:")
    ends = [j for j in (text.find("*/", i), text.find("-->", i)) if j >= 0] if i >= 0 else []
    return [t.strip().lower() for t in text[i + 5:min(ends)].split(",") if t.strip()] if ends else []


def styles(text) -> list:
    """Le contenu de chaque balise <style>."""
    low, out, i = text.translate(LOWER), [], 0
    while (j := low.find("<style", i)) >= 0 and (k := low.find(">", j)) >= 0 and (end := low.find("</style>", k)) >= 0:
        out.append(text[k + 1:end])
        i = end + 8
    return out


def uncomment(css) -> str:
    """Le CSS sans ses commentaires /* … */."""
    out, i = [], 0
    while (j := css.find("/*", i)) >= 0 and (k := css.find("*/", j + 2)) >= 0:
        out.append(css[i:j])
        i = k + 2
    return "".join(out) + css[i:]


def elements() -> list:
    """Toute la collection, une fiche par fichier : catégorie, ID, chemin, taille, texte, technique, tags."""
    if not ROOT.is_dir():
        sys.exit(f"Galaxy absente de {ROOT} : lancer d'abord « python galaxy.py install ».")
    out = []
    for path in sorted(ROOT.glob("*/*.html")):
        author, _, slug = path.stem.rpartition("_")
        text = path.read_text(encoding="utf-8", errors="replace")
        # Tailwind = pas de <style> : le tag « tailwind » ne suffit pas, 4 éléments en CSS pur le portent à tort
        out.append({"cat": path.parent.name, "id": f"{author}/{slug}", "path": path, "bytes": path.stat().st_size,
                    "text": text, "tags": tags(text), "tailwind": "<style" not in text.lower()})
    return out


def short(text, n) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip(" ,") + "…"


def size(e) -> str:
    return f"{e['bytes'] / 1024:.1f} Ko".replace(".", ",")


def tech(e) -> str:
    return "Tailwind" if e["tailwind"] else "CSS"


def find(ident, els) -> dict:
    m = LINK.search(ident)
    key = (f"{m.group(1)}/{m.group(2)}" if m else ident.replace("\\", "/")).lower()
    key = key[:-5] if key.endswith(".html") else key
    tail2, tail1 = "/".join(key.split("/")[-2:]), key.split("/")[-1]
    for e in els:
        if tail2 in (e["id"].lower(), f"{e['cat']}/{e['path'].stem}".lower()) or e["path"].stem.lower() == tail1:
            return e
    sys.exit(f"Élément introuvable : {ident} (prendre l'ID affiché par search)")


def overview(els):
    by = {}
    for e in els:
        by.setdefault(e["cat"], [0, 0])[e["tailwind"]] += 1
    print(f"Galaxy : {len(els)} éléments dans {ROOT} — catégorie, total (CSS / Tailwind) :")
    for cat, (css, tw) in sorted(by.items(), key=lambda kv: -sum(kv[1])):
        print(f"  {cat:<16}{css + tw:>5}  ({css} / {tw})")


def search(words, cat="", only="", n=12):
    els = elements()
    if cat:
        cats = sorted({e["cat"] for e in els})
        keep = [c for c in cats if c.lower().startswith(cat.lower())]
        if not keep:
            sys.exit(f"Catégorie inconnue « {cat} » ; au choix : {', '.join(cats)}")
        els = [e for e in els if e["cat"] in keep]
    if only:
        els = [e for e in els if e["tailwind"] == (only == "tailwind")]
    words = [w.lower() for w in words]
    if not words:
        return overview(els)
    ranked = []
    for e in els:
        bag = {w for t in e["tags"] for w in re.findall(r"[\w-]+", t)} | set(e["tags"])
        found = score = 0
        for w in words:
            stem = w[:-1] if w.endswith("s") and len(w) > 3 else w
            if w in bag or stem in bag:
                found, score = found + 1, score + 3
            elif any(stem in t for t in e["tags"]) or stem in e["cat"].lower():
                found, score = found + 1, score + 2
        if found:
            ranked.append((-found, -score, e["bytes"], e))
    ranked.sort(key=lambda r: r[:3])
    print(f"{len(ranked)} élément(s) pour « {' '.join(words)} »" + (f", {n} premiers" if len(ranked) > n else "")
          + " — en direct : https://uiverse.io/<ID>")
    for i, (found, _, _, e) in enumerate(ranked[:n], 1):
        part = f" [{-found}/{len(words)} mots]" if -found < len(words) else ""
        print(f"{i:>2}. {e['id']} · {e['cat']} · {tech(e)} · {size(e)}{part} — {short(', '.join(e['tags']), 90)}")


def notes(e) -> list:
    """Ce qui casserait le site ou le ferait dépendre d'un autre une fois l'élément collé tel quel."""
    css = uncomment(" ".join(styles(e["text"])))
    # sélecteurs : ce qui précède chaque « { », depuis la dernière « } »
    rules = {s.strip() for part in css.split("{")[:-1] for s in part.rsplit("}", 1)[-1].split(",")}
    out = []
    glob = sorted(s for s in rules if re.match(r"(?:html|body|:root|\*)(?![\w-])", s))
    if glob:
        out.append("sélecteurs globaux, à ramener sur le conteneur du composant : " + ", ".join(glob))
    loaded = sorted(set(LOADED.findall(e["text"])))
    if loaded:
        out.append("ressource chargée depuis " + ", ".join(loaded) + " : la copier dans le site ou la remplacer")
    links = sorted(set(HREF.findall(e["text"])) - {"www.w3.org"})
    if links:
        out.append("liens d'exemple à remplacer : " + ", ".join(links))
    if re.search(r"<script|\son[a-z]+\s*=", e["text"], re.I):
        out.append("contient du JavaScript : à relire avant tout usage")
    return out


def show(ids, full=False):
    els = elements()
    for ident in ids:
        e = find(ident, els)
        print(f"=== {e['id']} · {e['cat']} · {tech(e)} · {size(e)} · https://uiverse.io/{e['id']}"
              " · MIT, © 2023 Uiverse.io")
        if e["bytes"] > BIG and not full:
            print(f"Trop gros pour la conversation ({size(e)}) : en choisir un plus léger, ou --full pour l'afficher.")
            continue
        for note in notes(e):
            print(f"⚠ {note}")
        print(e["text"].strip())


def page(picked, dark, extra="") -> str:
    cards = []
    for i, e in enumerate(picked, 1):
        head = extra + ((f'<meta http-equiv="Content-Security-Policy" content="script-src {TAILWIND}">'
                         f'<script src="{TAILWIND}"></script>') if e["tailwind"] else "")
        cards.append(CARD.format(i=i, id=html.escape(e["id"]), cat=html.escape(e["cat"]), tech=tech(e),
                                 sandbox="allow-scripts" if e["tailwind"] else "",
                                 doc=html.escape(FRAME.format(head=head, body=e["text"]), quote=True)))
    return PAGE.format(n=len(cards), cards="\n".join(cards), mode="dark" if dark else "")


def capture(path, picked, dark) -> str:
    """Capture PNG par Chrome ou Edge sans fenêtre : le navigateur intégré à Claude n'ouvre pas les fichiers locaux.
    Chromium y fige les animations CSS à leur départ, souvent invisible (loaders) : la page capturée les avance toutes
    de 0,6 s, en phase ; la page de l'utilisateur reste d'origine."""
    exe = next(filter(None, map(shutil.which, BROWSERS)), None)
    if not exe:
        return "aucune (ni Chrome ni Edge trouvé) : ouvrir la page dans un navigateur"
    src, shot = path.with_suffix(".capture.html"), path.with_suffix(".png")
    src.write_text(page(picked, dark, ADVANCE), encoding="utf-8")
    shot.unlink(missing_ok=True)
    rows = -(-len(picked) // 3)  # 3 colonnes sur 1 400 px de large
    try:
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={Path(tempfile.gettempdir()) / 'galaxy-navigateur'}",
                        f"--screenshot={shot}", f"--window-size=1400,{80 + 400 * rows}",
                        "--virtual-time-budget=5000", src.as_uri()], capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        pass
    src.unlink(missing_ok=True)
    return str(shot) if shot.exists() else "ratée : ouvrir la page dans un navigateur"


def is_preview(path) -> bool:
    """Page écrite par preview, reconnue à son titre : la seule que preview remplace."""
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", errors="replace") as f:
        return "<title>Galaxy — aperçu</title>" in f.read(500)


def preview(ids, out="", dark=False):
    els = elements()
    picked = [find(i, els) for i in ids]
    path = (Path(out) if out else Path(tempfile.gettempdir()) / "galaxy-apercu.html").resolve()
    # « --out index.html » dans un site écraserait la page, puis index.png à la capture
    taken = [p.name for p in (path, path.with_suffix(".png"), path.with_suffix(".capture.html")) if p.exists()]
    if taken and not is_preview(path):
        sys.exit(f"Rien d'écrit, déjà dans {path.parent} : {', '.join(taken)}. Choisir un autre --out : preview ne "
                 "remplace qu'un ancien aperçu Galaxy.")
    path.write_text(page(picked, dark), encoding="utf-8")
    print(f"Aperçu de {len(picked)} élément(s) : {path}")
    print(f"Capture : {capture(path, picked, dark)}")


def install():
    git = (["git", "-C", str(ROOT), "pull", "--ff-only", "--quiet"] if (ROOT / ".git").is_dir()
           else ["git", "clone", "--depth", "1", "--quiet", REPO, str(ROOT)])
    try:
        code = subprocess.run(git).returncode
    except FileNotFoundError:
        sys.exit("Git introuvable : l'installer (git-scm.com), puis relancer cette commande.")
    if code:
        sys.exit(code)
    search([])


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) == 1:
        return print(__doc__)
    p = argparse.ArgumentParser(prog="galaxy.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="copie locale, ou mise à jour si elle existe")
    s = sub.add_parser("search", help="mots-clés anglais (tags), catégorie, technique ; sans mot : le sommaire")
    s.add_argument("words", nargs="*")
    s.add_argument("--cat", default="", help="catégorie (le début du nom suffit : but, load, tog…)")
    only = s.add_mutually_exclusive_group()
    only.add_argument("--css", dest="only", action="store_const", const="css", default="")
    only.add_argument("--tailwind", dest="only", action="store_const", const="tailwind")
    s.add_argument("-n", type=int, default=12, help="nombre de résultats (12)")
    sh = sub.add_parser("show", help="code complet et points à adapter")
    sh.add_argument("ids", nargs="+")
    sh.add_argument("--full", action="store_true", help="afficher même un élément de plus de 25 Ko")
    pv = sub.add_parser("preview", help="page HTML et sa capture PNG, pour comparer côte à côte")
    pv.add_argument("ids", nargs="+")
    pv.add_argument("--sombre", action="store_true", help="fond sombre au départ (élément clair, site sombre)")
    pv.add_argument("--out", default="", help="fichier à écrire, nouveau ou ancien aperçu (défaut : galaxy-apercu.html"
                                              " du dossier temporaire)")
    a = p.parse_args()
    if a.cmd == "install":
        install()
    elif a.cmd == "search":
        search(a.words, a.cat, a.only, a.n)
    elif a.cmd == "show":
        show(a.ids, a.full)
    else:
        preview(a.ids, a.out, a.sombre)


if __name__ == "__main__":
    main()
