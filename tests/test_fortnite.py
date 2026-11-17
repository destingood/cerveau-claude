"""Vérifications de la skill Maps Fortnite (skills/fortnite) : en-tête, fichiers cités, et les cinq outils — avec un
faux serveur local à la place de l'API d'Epic (aucun accès réseau), dans des dossiers temporaires.

Lancement : python tests/test_fortnite.py   (sortie : « N vérifications OK, M échec(s) »)"""
import http.server
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TMP = Path(tempfile.mkdtemp(prefix="cerveau-fortnite-test-"))
CODE = Path(__file__).resolve().parent.parent
SKILL_DIR = CODE / "skills" / "fortnite"
SCRIPTS = SKILL_DIR / "scripts"
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def run(script, *args, env=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, cwd=str(TMP),
                       timeout=120, env=e, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ 1. la skill elle-même
skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
front = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check(front is not None, "SKILL.md : en-tête YAML")
meta = dict(re.findall(r"(?m)^(\w+): (.*)$", front.group(1))) if front else {}
check(meta.get("name") == "fortnite", "SKILL.md : name = fortnite", meta.get("name"))
desc = meta.get("description", "").strip('"')
check(0 < len(desc) <= 1024, f"SKILL.md : description de 1 à 1024 caractères ({len(desc)})")
check(len(skill.splitlines()) < 500, "SKILL.md : moins de 500 lignes")
cites = sorted(set(re.findall(r"`((?:references|scripts|assets)/[\w./-]+)", skill)))
manquants = [c for c in cites if not (SKILL_DIR / c).exists()]
check(cites and not manquants, f"SKILL.md : les {len(cites)} fichiers cités existent", manquants)
refs = sorted(p.name for p in (SKILL_DIR / "references").glob("*.md"))
check(not [r for r in refs if f"references/{r}" not in skill], "SKILL.md : chaque fiche est citée")
outils = sorted(p.name for p in SCRIPTS.glob("*.py"))
check(all(f"`{o}`" in skill for o in outils), "SKILL.md : chaque outil est présenté", outils)
for o in outils:
    texte = (SCRIPTS / o).read_text(encoding="utf-8")
    externes = set(re.findall(r"(?m)^\s*(?:import|from) (\w+)", texte)) - set(sys.stdlib_module_names) - {"__future__"}
    check(not externes, f"{o} : bibliothèque standard seulement", externes)
    code, out = run(o)
    check(code in (0, 1) and "Traceback" not in out and len(out) > 100, f"{o} sans argument : mode d'emploi", out)
fiches = "\n".join((SKILL_DIR / "references" / r).read_text(encoding="utf-8") for r in refs)
check("This is not sponsored, endorsed, or administered by Epic Games, Inc." in fiches + skill,
      "fiches : la mention exigée par Epic est donnée mot pour mot")
check("[FAIT" in fiches and "[HYPOTHÈSE" in fiches and "[NON VÉRIFIÉ" in fiches, "fiches : faits, hypothèses et "
      "points non vérifiés sont marqués")

# ------------------------------------------------------------------ 2. fiche.py
code, out = run("fiche.py", "--titre", "FREE XP ZONE WARS discord.gg/x", "--titre", "NEON 2V2 ZONE WARS",
                "--tags", "ZoneWars, 2v2, Competitive, Practice", "--genre", "Battle Royale", "--json")
r = json.loads(out)
check(code == 0 and r["titres"][0]["titre"] == "NEON 2V2 ZONE WARS", "fiche.py : le titre sûr passe devant", out[:300])
mauvais = next(t for t in r["titres"] if "XP" in t["titre"])
interdits = " ".join(n[1] for n in mauvais["notes"] if n[0] == "bloquant")
check("XP" in interdits and "adresse web" in interdits, "fiche.py : XP et adresse web bloquants (règles 1.13, 1.2)",
      interdits)
check(set(mauvais["termes"]) == {"zone wars"} and "2v2" in r["titres"][0]["termes"], "fiche.py : termes de recherche lus")
code, out = run("fiche.py", "--titre", "Zone Wars", "--tags", "ZoneWars,2v2,1v1,Practice,Competitive", "--json")
r = json.loads(out)
check(code == 1 and any("quatre au plus" in n[1] for n in r["tags"]), "fiche.py : cinq tags → bloquant")
check(any("au-delà du genre" in n[1] for n in r["titres"][0]["notes"]), "fiche.py : titre qui ne dit que le genre signalé")
(TMP / "titres.txt").write_text("NEON ZONE WARS 2V2\nSPEED 2V2 REALISTICS\n", encoding="utf-8")
code, out = run("fiche.py", "--titre", "Neon 2v2 Zone Wars", "--concurrents", TMP / "titres.txt")
check(code == 1 and "règle 1.6" in out, "fiche.py : mêmes mots qu'un concurrent → bloquant", out)
code, out = run("fiche.py", "--titre", "Neon Zone Wars", "--genre", "Shooter", "--json")
check("Battle Royale" in json.dumps(json.loads(out)["genre"], ensure_ascii=False),
      "fiche.py : zone wars en Shooter → Battle Royale proposé (définition d'Epic)")
code, out = run("fiche.py", "--titre", "Neon Zone Wars", "--genre", "Arcade")
check(code == 1 and "13 genres" in out, "fiche.py : genre inconnu bloquant")
code, out = run("fiche.py", "--titre", "Neon 1v1", "--tags", "2v2", "--description",
                "1v1 rapide sur 6 arènes, manches de 2 minutes. Use code NEON !", "--json")
r = json.loads(out)
check(any("1v1" in n[1] and "2v2" in n[1] for n in r["tags"]), "fiche.py : taille d'équipe du titre ≠ tags signalée")
check(any("code créateur" in n[1] for n in r["description"] if n[0] == "bloquant"),
      "fiche.py : solliciter son code créateur bloquant (règle 4.2)")

# ------------------------------------------------------------------ 3. medias.py
def png(chemin, l, h, alpha):
    ligne = b"\x00" + (b"\x00\x00\x00\x00" if alpha else b"\x00\x00\x00") * l
    brut = zlib.compress(ligne * h)
    def bloc(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    chemin.write_bytes(b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", l, h, 8, 6 if alpha else 2, 0, 0, 0))
                       + bloc(b"IDAT", brut) + bloc(b"IEND", b""))


def jpg(chemin, l, h):
    chemin.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                       + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, l) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
                       + b"\xff\xd9")


img = TMP / "images"
img.mkdir()
png(img / "paysage-logo.png", 1920, 1080, False)
jpg(img / "paysage-art.jpg", 1920, 1080)
png(img / "portrait-logo.png", 1440, 1920, False)
png(img / "portrait-art.png", 1440, 1920, False)
png(img / "logo.png", 1440, 608, True)
code, out = run("medias.py", img, "--json")
r = json.loads(out)
check(code == 0 and r["bloquants"] == 0 and len(r["images"]) == 5, "medias.py : jeu complet accepté", out[:400])
check(any(i["format"] == "JPG" and i["largeur"] == 1920 for i in r["images"]), "medias.py : dimensions JPEG lues")
png(img / "logo.png", 1440, 608, False)
png(img / "paysage-logo.png", 1280, 720, False)
code, out = run("medias.py", img)
check(code == 1 and "transparent" in out and "exactement 1920 × 1080" in out,
      "medias.py : logo opaque et paysage 1280 × 720 bloquants", out)
check("2 obligatoire" in out, "medias.py : miniature paysage manquante comptée", out)

# ------------------------------------------------------------------ 4. diagnostic.py
code, out = run("diagnostic.py", "entonnoir", "--impressions", "48000", "--clics", "2600", "--rebond5", "41",
                "--j1", "9", "--ref-ctr", "5,2", "--ref-rebond5", "30", "--ref-j1", "14", "--json")
r = json.loads(out)
check(code == 0 and r["goulot"]["cle"] == "rebond5", "diagnostic.py : goulot = premier écart (rebond à 5 min)",
      r.get("goulot"))
check(r["etapes"][0]["etat"] == "au niveau", "diagnostic.py : taux de clic tiré des impressions et clics")
code, out = run("diagnostic.py", "entonnoir", "--j1", "9", "--j7", "3", "--json")
check(json.loads(out)["goulot"] is None, "diagnostic.py : sans référence, aucun verdict")
code, out = run("diagnostic.py", "ab", "--a", "12000:540", "--b", "11800:610", "--json")
r = json.loads(out)
check(r["tranche"] and r["gagnante"] == "B" and r["p"] < 0.1, "diagnostic.py : test A/B tranché à 90 %", r)
code, out = run("diagnostic.py", "ab", "--a", "1200:54", "--b", "1180:61", "--json")
check(not json.loads(out)["tranche"], "diagnostic.py : petit échantillon non tranché")
code, out = run("diagnostic.py", "ab", "--a", "100:200", "--b", "1:1")
check(code != 0 and "Traceback" not in out, "diagnostic.py : plus de clics que d'impressions refusé", out)

# ------------------------------------------------------------------ 5. page_ile.py
code, out = run("page_ile.py", "--modele")
modele = json.loads(out)
(TMP / "ile.json").write_text(out, encoding="utf-8")
code, out = run("page_ile.py", TMP / "ile.json")
check(code == 1 and not (TMP / "index.html").exists(), "page_ile.py : modèle non rempli → rien d'écrit", out)
modele.update(titre="Neon <Zone> Wars", code="1234-5678-9012", createur="@testeur", url="https://maps.example.org/neon/",
              mise_a_jour="2026-11-14", accroche="Zone Wars 2 à 16 joueurs, zones aléatoires.",
              faq=[{"q": "Combien de joueurs ?", "r": "De 2 à 16."}] * 3, video="https://youtu.be/abcdefghijk")
(TMP / "ile.json").write_text(json.dumps(modele, ensure_ascii=False), encoding="utf-8")
code, out = run("page_ile.py", TMP / "ile.json", "-o", TMP / "site" / "index.html")
page = (TMP / "site" / "index.html").read_text(encoding="utf-8") if code == 0 else ""
check(code == 0 and "1234-5678-9012" in page, "page_ile.py : page écrite avec le code d'île", out)
check("Neon &lt;Zone&gt; Wars" in page and "<Zone>" not in page, "page_ile.py : texte échappé")
ld = json.loads(re.search(r'ld\+json">\s*(.*?)\s*</script>', page, re.S).group(1)) if page else {}
check(ld.get("@type") == "VideoGame" and ld.get("numberOfPlayers", {}).get("maxValue") == 16
      and ld.get("sameAs") == ["https://www.fortnite.com/@testeur/1234-5678-9012"],
      "page_ile.py : données structurées VideoGame et lien fortnite.com", ld)
check("This is not sponsored, endorsed, or administered by Epic Games, Inc." in page, "page_ile.py : mention d'Epic")
check("youtube.com/embed" not in page and "watch?v=abcdefghijk" in page and "<link rel=\"canonical\"" in page,
      "page_ile.py : vidéo en lien (sans lecteur tiers), adresse canonique")
check(not re.search(r"<(?:script|link)[^>]+(?:src|href)=\"https?://(?!maps\.example)", page),
      "page_ile.py : aucune ressource tierce chargée")

# ------------------------------------------------------------------ 6. tendances.py contre un faux serveur
ILES = {
    "1111-1111-1111": {"title": "ALPHA 2V2 ZONE WARS", "creatorCode": "alpha", "tags": ["zonewars", "2v2"], "base": 1000},
    "2222-2222-2222": {"title": "BRAVO BOXFIGHT", "creatorCode": "bravo", "tags": ["boxfight", "1v1"], "base": 400},
    "3333-3333-3333": {"title": "CHARLIE ZONE WARS", "creatorCode": "charlie", "tags": ["zonewars"], "base": 4},
}
APPELS = []


def mesures(base, depuis):
    from datetime import datetime, timedelta
    debut = datetime.fromisoformat(depuis.replace("Z", "+00:00"))
    jours = [(debut + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00.000Z") for i in range(7)]
    serie = lambda f: [{"value": (None if base < 5 else f(i)), "timestamp": t} for i, t in enumerate(jours)]  # noqa: E731
    return {"uniquePlayers": serie(lambda i: base + 100 * i), "plays": serie(lambda i: 2 * base),
            "minutesPlayed": serie(lambda i: 20 * base), "averageMinutesPerPlayer": serie(lambda i: 20.0),
            "peakCCU": serie(lambda i: base // 10), "favorites": serie(lambda i: base // 100),
            "recommendations": serie(lambda i: base // 200),
            "retention": [{"d1": None if base < 5 else 0.2, "d7": None if base < 5 else 0.1, "timestamp": t} for t in jours]}


class Faux(http.server.BaseHTTPRequestHandler):
    trop = [1]  # premier appel aux genres : 429, pour tester la reprise

    def log_message(self, *a):
        pass

    def envoie(self, code, data):
        corps = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if code == 429:
            self.send_header("Retry-After", "0")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        APPELS.append(self.path)
        chemin = u.path.replace("/ecosystem/v1", "")
        if chemin == "/genres":
            if self.trop[0]:
                self.trop[0] = 0
                return self.envoie(429, {"errorCode": "rate"})
            return self.envoie(200, {"data": [{"slug": "battle-royale", "displayName": "Battle Royale"},
                                              {"slug": "shooter", "displayName": "Shooter"}]})
        if chemin == "/genres/battle-royale/rankings":
            return self.envoie(200, {"meta": {"total": 3, "snapshot": "2026-11-14T16:00:00.000Z"},
                                     "data": [{"islandCode": c, "rank": i + 1} for i, c in enumerate(ILES)]})
        if chemin == "/islands":
            return self.envoie(200, {"meta": {"page": {"nextCursor": None}},
                                     "data": [{"code": c, **{k: v for k, v in d.items() if k != "base"}}
                                              for c, d in ILES.items()]})
        m = re.fullmatch(r"/islands/([\d-]+)(/.*)?", chemin)
        if m and m.group(1) in ILES:
            d = ILES[m.group(1)]
            if not m.group(2):
                return self.envoie(200, {"code": m.group(1), "createdIn": "UEFN",
                                         **{k: v for k, v in d.items() if k != "base"}})
            if m.group(2) == "/metrics/day":
                return self.envoie(200, mesures(d["base"], q.get("from", ["2026-11-07T00:00:00.000Z"])[0]))
            if m.group(2) == "/rankings":
                return self.envoie(200, {"data": [{"timestamp": "2026-11-14T16:00:00.000Z", "genres": [
                    {"genreSlug": "battle-royale", "genre": "Battle Royale", "rank": 1}]}]})
        return self.envoie(404, {"errorCode": "not_found"})


serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=serveur.serve_forever, daemon=True).start()
ENV = {"FORTNITE_API": f"http://127.0.0.1:{serveur.server_port}/ecosystem/v1", "FORTNITE_HOME": str(TMP / "fortnite"),
       "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}

code, out = run("tendances.py", "genres", "--pause", "0", env=ENV)
check(code == 0 and "battle-royale" in out and "Battle Royale" in out, "tendances.py genres : après un 429, reprise", out)
code, out = run("tendances.py", "classement", "battle-royale", "--tag", "zonewars", "--pause", "0", "--json", env=ENV)
r = json.loads(out) if code == 0 else {}
check([i["code"] for i in r.get("iles", [])] == ["1111-1111-1111", "3333-3333-3333"],
      "tendances.py classement : filtre par tag", out[:400])
alpha = r["iles"][0] if r.get("iles") else {}
check(alpha.get("j1") == 20 and alpha.get("minutes_par_joueur") == 20.0 and round(alpha.get("tendance") or 0) == 36,
      "tendances.py : rétention en %, minutes par joueur, tendance sur 7 jours", alpha)
check(r.get("iles") and r["iles"][1]["joueurs"] is None and r["mediane"]["j1"] == 20,
      "tendances.py : île sous 5 joueurs → valeurs vides, ignorées par la médiane", r.get("mediane"))
check(any("from=" in a and "to=" in a for a in APPELS if "/metrics/day" in a),
      "tendances.py : fenêtre de jours complets demandée (from, to)")
code, out = run("tendances.py", "classement", "battle-royale", "--titres", TMP / "concurrents.txt", "--pause", "0",
                env=ENV)
check(code == 0 and "BRAVO BOXFIGHT" in (TMP / "concurrents.txt").read_text(encoding="utf-8"),
      "tendances.py : titres écrits pour fiche.py --concurrents", out)
code, out = run("tendances.py", "ile", "1111-1111-1111", "--pause", "0", env=ENV)
check(code == 0 and "Rang 1 dans le genre Battle Royale" in out and "fortnite.com/@alpha/1111-1111-1111" in out,
      "tendances.py ile : rang et lien", out)
code, out = run("tendances.py", "ile", "9999-9999-9999", "--pause", "0", env=ENV)
check(code == 2 and "inconnue" in out and "Traceback" not in out, "tendances.py ile : île inconnue expliquée", out)
code, out = run("tendances.py", "ile", "12-34", env=ENV)
check(code == 1 and "12 chiffres" in out, "tendances.py : code d'île mal formé refusé")
code, out = run("tendances.py", "comparer", "1111-1111-1111", "2222-2222-2222", "--pause", "0", "--json", env=ENV)
(TMP / "niche.json").write_text(out, encoding="utf-8")
check(code == 0 and json.loads(out)["mediane"]["iles"] == 2, "tendances.py comparer : médiane de deux îles")
code, out = run("diagnostic.py", "entonnoir", "--j1", "12", "--reference", TMP / "niche.json", "--json")
check(json.loads(out)["goulot"]["cle"] == "j1", "diagnostic.py : références J1 lues dans tendances.py comparer --json")
code, out = run("tendances.py", "nouveautes", "--mot", "zone", "--pause", "0", env=ENV)
check(code == 0 and "2 île(s) sur les 3" in out and "wars (2)" in out, "tendances.py nouveautes : filtre et mots", out)
for _ in range(2):
    code, out = run("tendances.py", "suivre", "1111-1111-1111", "--pause", "0", env=ENV)
suivi = json.loads((TMP / "fortnite" / "suivi" / "1111-1111-1111.json").read_text(encoding="utf-8"))
check(code == 0 and len(suivi["jours"]) == 7 and "0 nouveau" in out, "tendances.py suivre : historique gardé sans "
      "doublon", out)
ENV_KO = dict(ENV, FORTNITE_API="http://127.0.0.1:9/ecosystem/v1")
code, out = run("tendances.py", "genres", "--pause", "0", env=ENV_KO)
check(code == 2 and "injoignable" in out and "Traceback" not in out, "tendances.py : API injoignable expliquée", out)
serveur.shutdown()

# ------------------------------------------------------------------ 7. livraison dans le plugin
sys.path.insert(0, str(CODE))
from brainkit import publish  # noqa: E402

dest = TMP / "plugin"
files = publish.build(dest, "Auteur", "proprietaire/depot")
check("skills/fortnite/SKILL.md" in files and "skills/fortnite/scripts/tendances.py" in files,
      "brain publish : la skill fortnite part dans le plugin")
check("/cerveau:fortnite" in (dest / "README.md").read_text(encoding="utf-8"), "README du plugin : skill présentée")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
