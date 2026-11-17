"""Scripts des skills youtube, replica, public-apis, uiverse (galaxy) et scrapegraph (sgai), lancés comme l'utilisateur
les lance, sur de petits fichiers d'un dossier temporaire. Rien ne part sur le réseau : vérification d'URL,
téléchargement de liste, install, capture et extraction ScrapeGraphAI ne sont pas lancés.

Lancement : python tests/test_scripts_skills.py   (sortie : « N vérifications OK, M échec(s) »)"""
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-scripts-skills-test-"))
CODE = Path(__file__).resolve().parent.parent
SKILLS = CODE / "skills"
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")
os.environ["BRAIN_HOME"] = str(TMP / "brain")
sys.path.insert(0, str(CODE))

from brainkit.common import remove_tree  # noqa: E402

WORK, HOME = TMP / "travail", TMP / "maison"  # faux dossier personnel : ni la liste d'API ni la copie Galaxy du PC
WORK.mkdir()
HOME.mkdir()
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HOME=str(HOME), USERPROFILE=str(HOME),
           GALAXY_DIR=str(WORK / "galaxy"))


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def run(script, *args, raw=False):
    """skills/<script> lancé dans le dossier de travail → (code de sortie, sortie standard + erreurs)."""
    r = subprocess.run([sys.executable, str(SKILLS / script), *map(str, args)], capture_output=True, cwd=str(WORK),
                       env=ENV, timeout=120, stdin=subprocess.DEVNULL)
    out, err = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    return (r.returncode, out, err) if raw else (r.returncode, out + err)


def data(script, *args):
    """Le même avec --json → (code, JSON lu sur la sortie standard ou None, toute la sortie)."""
    code, out, err = run(script, *args, "--json", raw=True)
    try:
        return code, json.loads(out), out + err
    except ValueError:
        return code, None, out + err


def write(name, text):
    (WORK / name).parent.mkdir(parents=True, exist_ok=True)
    (WORK / name).write_text(text, encoding="utf-8")


def srt(cues):
    """[(début, fin, texte)] en secondes → sous-titres SRT."""
    def ts(t):
        ms = round(t * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, 1))


def png(name, box, size=48):
    """PNG RGB 8 bits écrit avec zlib seul : fond blanc, carré noir box = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    raw = b"".join(b"\0" + b"".join(b"\0\0\0" if x0 <= x < x1 and y0 <= y < y1 else b"\xff\xff\xff"
                                    for x in range(size)) for y in range(size))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    (WORK / name).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                              + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ================================================================== YouTube (skills/youtube/scripts)
YT = "youtube/scripts/"

# ------------------------------------------------------------------ deadair.py : la liste de coupes du montage
write("prise.srt", srt([(0, 2, "Today we build a desk from scratch."), (4, 5, "um"),
                        (5.2, 7, "The first thing you need is wood."), (7.1, 7.6, "euh, du coup"),
                        (7.7, 10, "The first thing you need is good dry wood.")]))
code, out = run(YT + "deadair.py", "prise.srt")
check(code == 0 and "10.00s in, 5 cues" in out and "4 cuts, 4.85s removed, 5.15s out" in out,
      "deadair : liste de coupes, total retiré et durée finale", out)
code, d, out = data(YT + "deadair.py", "prise.srt")
cuts = [(c["kind"], c["start"], c["end"]) for c in (d or {}).get("cuts", [])]
check(cuts[:1] == [("DEAD", 2.225, 3.775)], "deadair : blanc de 2 s coupé au milieu, une respiration gardée", out)
check([c[0] for c in cuts] == ["DEAD", "FILLER", "REPEAT", "FILLER"] and cuts[2][1:] == (5.2, 7.0)
      and '"why": "euh, du coup"' in out, "deadair : « um », « euh, du coup » = FILLER ; reprise vue malgré le "
      "« euh » entre les prises, la première coupée", out)
code, d, out = data(YT + "deadair.py", "prise.srt", "--floor", "3")
check(code == 0 and d and "DEAD" not in [c["kind"] for c in d["cuts"]],
      "deadair : --floor 3 garde le blanc de 2 s", out)
write("auto.fr.vtt", "WEBVTT\nKind: captions\nLanguage: fr\n\n"  # sous-titres auto : chaque cue répète la ligne d'avant
      "00:00:00.000 --> 00:00:02.500 align:start position:0%\n \n"
      "bonjour<00:00:00.500><c> à</c><00:00:01.000><c> tous</c>\n\n"
      "00:00:02.500 --> 00:00:02.510 align:start position:0%\nbonjour à tous\n \n\n"
      "00:00:02.510 --> 00:00:05.000 align:start position:0%\nbonjour à tous\n"
      "aujourd'hui<00:00:03.000><c> on</c><00:00:03.500><c> parle</c><00:00:04.000><c> montage</c>\n\n"
      "00:00:05.000 --> 00:00:05.010 align:start position:0%\naujourd'hui on parle montage\n \n\n"
      "00:00:05.010 --> 00:00:08.000 align:start position:0%\naujourd'hui on parle montage\n"
      "et<00:00:05.500><c> de</c><00:00:06.000><c> rétention</c>\n")
code, out = run(YT + "deadair.py", "auto.fr.vtt")
check(code == 0 and "8.00s in, 3 cues" in out and "0 cuts" in out,
      "deadair : sous-titres auto YouTube (<c>), la ligne répétée d'une cue à l'autre n'est pas une reprise", out)
segments = [{"start": 0, "end": 2, "text": "hello my friends"}, {"start": 5, "end": 6, "text": "and welcome back"}]
write("whisper.json", json.dumps({"language": "en", "segments": segments}))
code, d, out = data(YT + "deadair.py", "whisper.json")
check(code == 0 and d and [c["why"] for c in d["cuts"]] == ["3.00s gap"], "deadair : JSON de whisper lu", out)
# Liste nue de segments : load() appelait d.get() avant de regarder le type (AttributeError, corrigé en 8.23.0) ;
# chapters.py et retention.py --transcript partagent ce lecteur.
write("segments.json", json.dumps(segments))
code, d, out = data(YT + "deadair.py", "segments.json")
check(code == 0 and d and [c["why"] for c in d["cuts"]] == ["3.00s gap"],
      "deadair : JSON en liste nue de segments lu comme {\"segments\": …}", out)

# ------------------------------------------------------------------ chapters.py : des chapitres que YouTube accepte
cues, t = [], 0.0
for sujet, verbes in (("pasta", "boil salt stir taste drain serve"), ("guitar", "tune strum press bend record play"),
                      ("tomatoes", "plant water prune stake feed pick")):
    for verbe in verbes.split():  # trois sujets de six répliques de 4 s, séparés par une vraie pause de 3 s
        cues.append((t, t + 4, f"{verbe.capitalize()} the {sujet} now."))
        t += 4
    t += 3
write("cours.srt", srt(cues))
code, d, out = data(YT + "chapters.py", "cours.srt", "--target", "3")
ch = (d or {}).get("chapters", [])
check(code == 0 and d and d["valid"] and [(c["start"], c["label"]) for c in ch] == [(0, "0:00"), (27, "0:27"),
      (54, "0:54")], "chapters : 0:00 en premier, puis les deux vraies pauses (0:27, 0:54)", out)
check([c["draft_title"].split()[0] for c in ch] == ["Pasta", "Guitar", "Tomatoes"],
      "chapters : titre provisoire tiré du mot le plus dit du passage", out)
code, out = run(YT + "chapters.py", "cours.srt")
lines = [x.strip() for x in out.splitlines() if x.strip()]
check(code == 0 and lines and lines[0].startswith("0:00 ") and "0:27 Guitar" in out and "0:54 Tomatoes" in out
      and "INVALID" not in out, "chapters : bloc à coller qui commence à 0:00, valide (cible par défaut)", out)
write("court.srt", srt(cues[:4]))
code, out = run(YT + "chapters.py", "court.srt")
check(code == 1 and "too few cues" in out, "chapters : moins de 6 répliques, refus net", out)
mots = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar".split()
write("sans-pause.srt", srt([(4 * i, 4 * i + 4, f"{mots[i // 2]} {mots[i // 2]} item {i}") for i in range(30)]))
code, d, out = data(YT + "chapters.py", "sans-pause.srt", "--target", "4")
starts = [c["start"] for c in (d or {}).get("chapters", [])]
check(code == 0 and d and d["valid"] and len(starts) == 4 and all(b - a >= 15 for a, b in zip(starts, starts[1:])),
      "chapters : sans pauses (sous-titres auto), chapitres espacés d'au moins durée / (2 × cible)", out)

# ------------------------------------------------------------------ retention.py : accroche, chutes, glissement
ys = [100, 85, 76, 70] + list(range(69, 60, -1)) + list(range(45, 37, -1))  # chute de 16 points entre 2:00 et 2:10
write("retention.csv", "Position (s),Retention (%)\n" + "".join(f"{10 * i},{y}\n" for i, y in enumerate(ys)))
write("voix.vtt", "WEBVTT\n\n00:00.000 --> 00:05.000\nHello and welcome\n\n01:00.000 --> 01:05.000\nThe middle part\n\n"
      "01:58.000 --> 02:03.000\nAnd now a quick word from our sponsor\n\n03:10.000 --> 03:15.000\nSee you next week\n")
code, d, out = data(YT + "retention.py", "retention.csv")
check(code == 0 and d and d["points"] == 21 and d["hook_leak"] == 30.0,
      "retention : fuite de l'accroche = 30 points perdus dans les 30 premières secondes", out)
first = ((d or {}).get("cliffs") or [{}])[0]
check(first.get("from") == 120 and first.get("lost") == 16 and first.get("at_seconds") == 120,
      "retention : la chute la plus raide est celle mise à 2:00 (−16 points)", out)
code, out = run(YT + "retention.py", "retention.csv", "--transcript", "voix.vtt")
check(code == 0 and "[leaking]" in out and any("120s" in x and "sponsor" in x for x in out.splitlines()),
      "retention : --transcript (VTT) donne ce qui était dit à la chute", out)
fr = [100, 91, 82] + list(range(81, 63, -1))  # % de la vidéo, de 5 en 5
write("fidelisation.csv", "Position (%);Audience (%)\n" + "".join(f"{5 * i};{y},0 %\n" for i, y in enumerate(fr)))
code, d, out = data(YT + "retention.py", "fidelisation.csv")
first = ((d or {}).get("cliffs") or [{}])[0]
check(code == 0 and d and (d["points"], d["hook_leak"], first.get("at_seconds", 0)) == (21, 18, None),
      "retention : export français (« ; », virgule décimale, %) ; axe en %, accroche = premiers 10 %", out)
code, d, out = data(YT + "retention.py", "fidelisation.csv", "--duration", "200")
check(code == 0 and d and {c["from"]: c["at_seconds"] for c in d["cliffs"]}.get(5.0) == 10.0,
      "retention : --duration change les % en secondes", out)
code, d2, out = data(YT + "retention.py", "--duration", "200", "fidelisation.csv")
check(code == 0 and d2 == d, "retention : --duration placé avant le fichier, sa valeur n'est pas prise pour le fichier",
      out)
write("trop-court.csv", "0,100\n10,90\n")
code, out = run(YT + "retention.py", "trop-court.csv")
check(code == 1 and "at least 8 data points" in out, "retention : moins de 8 points, refus net", out)

# ------------------------------------------------------------------ hookscore.py : noter une accroche
fort = "97% of you will lose your channel before video 30, but nobody tells you why?"
code, d, out = data(YT + "hookscore.py", "--hook", fort)
r = (d or [{}])[0]
v = list(r.get("properties", {}).values())
check(code == 0 and r.get("band") == "STRONG" and r.get("formula") == "The Statistic" and v
      and r["verdict"] == round(0.6 * (sum(v) / len(v)) + 0.4 * min(v)),
      "hookscore : accroche chiffrée STRONG (« The Statistic »), verdict = 60 % moyenne + 40 % maillon faible", out)
write("accroches.txt", "Salut à tous, bienvenue sur la chaîne, aujourd'hui une vidéo vraiment incroyable\n"
      "Tu perds 80 % de tes abonnés avant la 30e seconde, mais personne ne t'explique pourquoi ?\n" + fort + "\n")
code, d, out = data(YT + "hookscore.py", "accroches.txt")
check(code == 0 and d and [x["band"] for x in d] == ["STRONG", "STRONG", "WEAK"] and d[2]["hook"].startswith("Salut")
      and [x["verdict"] for x in d] == sorted((x["verdict"] for x in d), reverse=True),
      "hookscore : fichier classé, accroche française STRONG, « Salut à tous, bienvenue » dernière (WEAK)", out)
(code, out), (code2, out2) = run(YT + "hookscore.py"), run(YT + "hookscore.py", "--help")
check(code == 1 and code2 == 0 and "hookscore.py --hook" in out2,
      "hookscore : mode d'emploi (code 1 ; 0 avec --help)", out)
code, out = run(YT + "hookscore.py", "absent.txt")
check(code == 1 and "file not found: absent.txt" in out, "hookscore : fichier absent, erreur (code 1)", out)

# ------------------------------------------------------------------ title.py : titre et miniature
long_t = "I Tried Every Single Productivity App On My Phone For An Entire Month"  # 69 caractères
code, d, out = data(YT + "title.py", "--title", long_t)
issues = dict((d or [{}])[0].get("issues", []))
check(code == 0 and "cuts near 60" in issues.get("length", "") and "mobile" in issues and "no-number" in issues,
      "title : 69 caractères, coupé vers 60 sur ordinateur et 40 sur mobile, sans chiffre", out)
code, d, out = data(YT + "title.py", "--title", "I tried 7 apps for 30 days", "--thumb", "WORTH IT?")
code2, d2, out2 = data(YT + "title.py", "--title", "I tried 7 apps for 30 days", "--thumb", "7 APPS")
check(code == 0 and d and (d[0]["issues"], d[0]["score"]) == ([], 100) and code2 == 0 and d2
      and "7, apps" in dict(d2[0]["issues"]).get("duplicate", ""), "title : titre court et chiffré sans défaut ; "
      "miniature qui répète le titre (7, apps) signalée", out + out2)
write("titres.txt", f"{long_t}\n{long_t} And Here Is Exactly What Happened To My Focus\nI tried 7 apps for 30 days\n")
code, d, out = data(YT + "title.py", "titres.txt")
check(code == 0 and d and d[0]["chars"] == 26 and d[-1]["chars"] == 115
      and "hard limit is 100" in dict(d[-1]["issues"]).get("length", ""),
      "title : fichier classé du meilleur au pire, limite dure de 100 caractères", out)

# ------------------------------------------------------------------ swipe.py : les vidéos qui battent LEUR chaîne
vids = [{"channel": "Petit Atelier", "title": title, "views": views, "url": f"https://www.youtube.com/watch?v=a{i}"}
        for i, (title, views) in enumerate([("Desk tour", 10000), ("My week", 12000), ("Q and A", 11000),
                                            ("Studio vlog", 9000), ("I built a desk in 24 hours", 60000)])]
write("collecte.json", json.dumps(vids + [{"channel": "Grosse Chaine", "title": "Live", "views": 90000},
                                          {"channel": "Grosse Chaine", "title": "Teaser", "views": 500}]))
code, d, out = data(YT + "swipe.py", "collecte.json")
top = (d or {}).get("outliers") or [{}]
check(code == 0 and len(top) == 1 and top[0].get("title") == "I built a desk in 24 hours"
      and (top[0].get("median"), top[0].get("multiple"), top[0].get("formula")) == (11000, 5.45, "The Clock"),
      "swipe : 60 000 vues sur une chaîne à 11 000 de médiane = ×5,45 (formule « The Clock »)", out)
check(d and d["skipped_thin_channels"] == [["Grosse Chaine", 2]],
      "swipe : chaîne de moins de 4 vidéos écartée, ses 90 000 vues ne sont pas classées", out)
write("yt-dlp.json", json.dumps({"channel": "Petit Atelier", "entries": [None] + [
    {"title": x["title"], "view_count": x["views"], "url": x["url"]} for x in vids]}))
code, d, out = data(YT + "swipe.py", "yt-dlp.json", "--min", "5")
check(code == 0 and d and [x["title"] for x in d["outliers"]] == ["I built a desk in 24 hours"],
      "swipe : sortie brute de yt-dlp --flat-playlist -J lue, --min respecté", out)

# ================================================================== Replica (skills/replica/scripts)
RP = "replica/scripts/"

# ------------------------------------------------------------------ contrast.py : contraste WCAG
(code, out), (code2, out2) = run(RP + "contrast.py", "#777777", "#ffffff"), run(RP + "contrast.py", "#767676", "#fff")
check(code == 1 and "FAIL   4.48:1" in out and code2 == 0 and "AA     4.54:1" in out2, "contrast : gris #777 sur blanc "
      "(4,48:1) sous AA, code 1 ; #767676 (4,54:1) passe, code 0", out + out2)
write("tokens.json", json.dumps({"color": {"text": {"body": "#111", "muted": "#777777"}, "bg": "#ffffff"},
                                 "pairs": [["text-body", "bg"], ["text-muted", "bg", "large"], ["text-ghost", "bg"]]}))
code, d, out = data(RP + "contrast.py", "tokens.json")
rows = {x["fg"]: x for x in d or []}
check(code == 1 and rows.get("text-body", {}).get("aaa") and rows.get("text-muted", {}).get("aa")
      and rows.get("text-ghost", {}).get("error") == "unknown token",
      "contrast : jetons imbriqués, grand texte à 3:1, jeton inconnu signalé (code 1)", out)
code, out = run(RP + "contrast.py", SKILLS / "replica" / "assets" / "tokens.json")
check(code == 0 and "0 failing AA" in out, "contrast : la palette d'exemple de la skill passe", out)

# ------------------------------------------------------------------ imgdiff.py : capture de l'original contre le clone
png("original.png", (8, 8, 24, 24))
png("clone.png", (8, 8, 24, 24))
png("decale.png", (24, 24, 40, 40))
code, d, out = data(RP + "imgdiff.py", "original.png", "clone.png")
check(code == 0 and d and (d["score"], d["verdict"], d["regions"]) == (100, "matches", []),
      "imgdiff : deux PNG identiques, mise en page à 100 (matches)", out)
write("visuel.json", json.dumps(d))
code, d, out = data(RP + "imgdiff.py", "original.png", "decale.png", "--out", "ecarts.png")
check(code == 0 and d and d["score"] < 50 and d["regions"] and (WORK / "ecarts.png").is_file()
      and (WORK / "ecarts.png").read_bytes()[:4] == b"\x89PNG",
      "imgdiff : carré déplacé, mise en page « different », zones listées, image des écarts écrite", out)
write("pas-une-image.png", "texte")
code, out = run(RP + "imgdiff.py", "original.png", "decale.png", "--mode", "pixel", "--fail-under", "95")
code2, out2 = run(RP + "imgdiff.py", "original.png", "pas-une-image.png")
check(code == 1 and "PIXEL" in out and "77.8" in out and code2 == 2 and "is not a PNG" in out2,
      "imgdiff : mode pixel sous --fail-under 95, code 1 ; fichier qui n'est pas un PNG refusé (code 2)", out + out2)

# ------------------------------------------------------------------ listing.py : fiche App Store / Google Play
code, out = run(RP + "listing.py", SKILLS / "replica" / "assets" / "listing.example.json")
check(code == 0 and "0 errors" in out, "listing : la fiche d'exemple de la skill passe (avertissements seulement)", out)
write("fiche.json", json.dumps({"app_store": {"name": "Slotwise, the best booking app for teams",  # 40 caractères
                                              "description": "Like Calendly, but simpler.",
                                              "keywords": "booking, calendar,booking"}}))
code, d, out = data(RP + "listing.py", "fiche.json", "--avoid", "Calendly")
found = "\n".join(f"{i['level']} {i['field']}: {i['message']}" for i in d or [])
check(code == 1 and "error name: 40 characters, limit is 30" in found
      and "error description: mentions 'Calendly'" in found and "warn name: 'best'" in found
      and "warn keywords: repeated: booking" in found,
      "listing : nom trop long, nom de l'original = erreurs (code 1) ; « best », doublon = avertissements", out)

# ------------------------------------------------------------------ parity.py : part de l'original refaite
write("features.csv", "feature,area,priority,original,clone,notes\nBook a slot,booking,must,yes,yes,\n"
      "Reschedule a booking,booking,must,yes,partial,\nEmail reminders,notifications,should,yes,no,\n"
      "Export to CSV,settings,could,yes,yes,\nDark mode,settings,could,yes,skip,out of scope\n"
      "Our own extra,settings,could,no,yes,\n")
code, d, out = data(RP + "parity.py", "features.csv")
check(code == 0 and d and d["feature_score"] == 61.1 and (d["must_have_done"], d["must_have_total"]) == (1, 2),
      "parity : score pondéré (must 3, should 2, could 1 ; partial = moitié) = 61,1", out)
check(d and [m["feature"] for m in d["missing"]] == ["Reschedule a booking", "Email reminders"]
      and [m["feature"] for m in d["skipped"] + d["extras"]] == ["Dark mode", "Our own extra"],
      "parity : manques dans l'ordre de construction ; skip et ajouts hors score", out)
code, d, out = data(RP + "parity.py", "features.csv", "--visual", "visuel.json", "--fail-under", "80")
check(code == 1 and d and (d.get("layout_score"), d.get("overall")) == (100, 68.9),
      "parity : --visual (sortie d'imgdiff) = 80 % fonctions + 20 % mise en page ; sous --fail-under, code 1", out)
write("sans-colonne.csv", "name,clone\nx,yes\n")
code, out = run(RP + "parity.py", "sans-colonne.csv")
check(code == 2 and "no 'feature' column" in out, "parity : matrice sans colonne feature refusée (code 2)", out)

# ------------------------------------------------------------------ reviews.py : ce que les utilisateurs détestent
avis = [a.split("|") for a in (  # source, url, date, note, texte
    "app-store|https://apps.example.com/r/1|2026-09-01|1|It crashes every time I open a booking. Useless.",
    "google-play|https://play.example.com/r/2|2026-08-15|2|Constant crashes since the update. I wish it had dark mode.",
    "reddit|https://reddit.example.com/r/3|2026-07-01||The app is buggy and crashed twice during a call.",
    "g2|https://g2.example.com/r/4|2026-06-01|4|Way too expensive for a small team.",
    "g2||2026-06-01|1|No link, never counted.",
    "app-store|https://apps.example.com/r/5|2026-09-01|1|It crashes every time I open a booking. Useless.",
    "app-store|https://apps.example.com/r/6|2026-09-02|1|Terrible, just terrible.")]
write("reviews.csv", "source,url,date,rating,text\n" + "".join(",".join(f'"{c}"' for c in a) + "\n" for a in avis))
code, d, out = data(RP + "reviews.py", "reviews.csv", "--today", "2026-11-01")
top = ((d or {}).get("themes") or [{}])[0]
check(code == 0 and (top.get("id"), top.get("count"), top.get("thin")) == ("bugs", 3, False)
      and (d["dropped"], d["duplicates"]) == (1, 1),
      "reviews : « bugs » en tête (3 avis, 3 sources) ; ligne sans lien écartée, doublon retiré", out)
quotes = [q for th in (d or {}).get("themes", []) for q in th["quotes"]] + (d or {}).get("requests", [])
check(quotes and all(any(q["quote"] in a[4] and q["url"] == a[1] for a in avis) for q in quotes)
      and [q["quote"] for q in d["requests"]] == ["I wish it had dark mode."]
      and [x["text"] for x in d["unthemed_negative"]] == ["Terrible, just terrible."], "reviews : citations exactes "
      "avec leur lien ; demande relevée mot pour mot ; 1 étoile sans thème laissée à lire à la main", out)
code, out = run(RP + "reviews.py", "reviews.csv", "--today", "2026-11-01", "--out", "retours.md")
rapport = (WORK / "retours.md").read_text(encoding="utf-8") if (WORK / "retours.md").is_file() else ""
check(code == 0 and rapport.startswith("# What users of the original hate and want"), "reviews : rapport --out", out)

# ------------------------------------------------------------------ sweep.py : traces de l'original avant lancement
for rel, text in {"clone/src/app.js": "export const CalendlyButton = () => null;\n",
                  "clone/src/theme.css": ".a { color: #06F; }\n.b { color: #123456; }\n",
                  "clone/public/calendly-logo.svg": "<svg/>\n", "clone/replica/notes.md": "We clone Calendly.\n",
                  "clone/node_modules/x/index.js": "calendly\n", "propre/index.html": "<h1>Slotwise</h1>\n"}.items():
    write(rel, text)
code, d, out = data(RP + "sweep.py", "clone", "--avoid", "Calendly", "--colors", "#0066ff")
hits = sorted((h["kind"], h["file"].replace("\\", "/")) for h in d or [])
check(code == 1 and hits == [("color", "src/theme.css"), ("name", "src/app.js"), ("path", "public/calendly-logo.svg")],
      "sweep : nom dans un identifiant, nom de fichier, couleur courte (#06F) ; replica/, node_modules ignorés", out)
code, out = run(RP + "sweep.py", "propre", "--avoid", "Calendly", "--domains", "calendly.com")
code2, out2 = run(RP + "sweep.py", "propre")
check(code == 0 and out.startswith("Clean.") and code2 == 2 and "nothing to look for" in out2,
      "sweep : dossier propre, code 0 ; rien à chercher, refus (code 2)", out + out2)

# ================================================================== public-apis : l'index embarqué, hors ligne
AP = "public-apis/scripts/apis.py"
code, d, out = data(AP, "cherche", "weather", "--sans-cle", "--https")
res = (d or {}).get("resultats", [])
check(code == 0 and res and len(res) == min(15, d["total"]) and all(
    not e["cle"] and e["https"] and "weather" in (e["nom"] + " ".join(e["cats"]) + e["desc"]).lower() for e in res),
      "public-apis : recherche hors ligne, filtres sans clé + HTTPS respectés, 15 résultats au plus", out)
(code, out), (code2, out2) = run(AP, "categories"), run(AP, "cherche", "--cat", "zzzz")
code3, out3 = run(AP, "cherche")
check(code == 0 and out.startswith("public-apis du ") and "\nWeather (" in out and (code2, code3) == (1, 1)
      and "Aucune catégorie" in out2 and "Donne des mots" in out3,
      "public-apis : catégories ; catégorie inconnue ou recherche vide, message clair (code 1)", out + out2 + out3)
write("README.md", "# Public APIs\n\n## Index\n* [Animals](#animals)\n\n### Animals\n"
      "API | Description | Auth | HTTPS | CORS\n|:---|:---|:---|:---|:---|\n"
      "| [Cat Facts](https://catfacts.example.com/?utm_source=list&lang=en) | Daily cat facts | No | Yes | Yes |\n"
      "| [Dog Pics](javascript:alert(1)) | Trapped link | No | Yes | No |\n"
      "| [Owl Data](http://owls.example.com/) | Owl sightings | `apiKey` | No | Unknown |\n\n### Weather\n"
      "| [Rain Now](https://rain.example.com/) | Rain radar | No | Yes | No |\n\n## MCP Servers\n"
      "| Name | Description | Auth | Transport | Install |\n|:---|:---|:---|:---|:---|\n"
      "| [Mail MCP](https://mailmcp.example.com/) | Send mail from agents | `apiKey` | `stdio` | "
      "[Cursor](https://cursor.example.com/x?utm_medium=a) |\n")
code, out = run(AP, "maj", "--depuis", "README.md", "--vers", "index.json")
idx = json.loads((WORK / "index.json").read_text(encoding="utf-8")) if (WORK / "index.json").is_file() else {}
apis = {e["nom"]: e for e in idx.get("apis", [])}
check(code == 0 and sorted(apis) == ["Cat Facts", "Owl Data", "Rain Now"]
      and apis["Cat Facts"]["url"] == "https://catfacts.example.com/?lang=en"
      and (apis["Cat Facts"]["cors"], apis["Owl Data"]["cors"], apis["Owl Data"]["cle"]) == ("oui", "?", "apiKey")
      and [m["install"] for m in idx["mcp"]] == [[["Cursor", "https://cursor.example.com/x"]]],
      "public-apis : maj --depuis un README local, lien javascript: écarté, utm_ retirés, CORS, clé et MCP lus", out)
code, out = run(AP, "maj", "--depuis", "README.md")
check(code == 1 and "Liste suspecte" in out and not list(HOME.rglob("apis.json")),
      "public-apis : liste deux fois plus courte que l'index embarqué refusée, rien d'écrit", out)

# ================================================================== uiverse : galaxy.py sur une copie locale factice
GX = "uiverse/scripts/galaxy.py"
code, out = run(GX)
code2, out2 = run(GX, "search", "button")
check(code == 0 and "galaxy.py search" in out and code2 == 1 and "Galaxy absente" in out2,
      "galaxy : mode d'emploi sans argument ; sans copie locale, renvoie vers install", out + out2)
for rel, text in {"Buttons/alice_shiny-cat-12.html": '<!-- From Uiverse.io by alice - Tags: button, gradient -->\n'
                  '<button class="btn">Go</button>\n<img src="https://images.example.com/star.png" alt="">\n'
                  "<style>\n/* reset */\nbody { margin: 0 }\n.btn { color: #fff; background: #0af }\n</style>\n",
                  "loaders/bob_quick-dog-7.html": "<!-- From Uiverse.io by bob - Tags: loader, spinner -->\n"
                  '<div class="animate-spin h-8 w-8 rounded-full border-4"></div>\n',  # Tailwind : pas de <style>
                  "loaders/carol_big-owl-3.html": "<!-- From Uiverse.io by carol - Tags: loader, huge -->\n"
                  '<div class="x"></div><style>.x { color: red }</style>\n' + "/* x */\n" * 4000}.items():  # 32 Ko
    write(Path("galaxy") / rel, text)
code, out = run(GX, "search")
code2, out2 = run(GX, "search", "buttons")
check(code == 0 and "Galaxy : 3 éléments" in out and code2 == 0 and "1 élément(s)" in out2
      and "alice/shiny-cat-12 · Buttons · CSS" in out2, "galaxy : sommaire ; recherche par tag, pluriel compris",
      out + out2)
code, out = run(GX, "search", "loader", "--tailwind")
code2, out2 = run(GX, "search", "loader", "--css")
check("bob/quick-dog-7 · loaders · Tailwind" in out and "carol" not in out and "carol/big-owl-3" in out2
      and "bob" not in out2, "galaxy : --tailwind / --css, la technique lue à l'absence d'un <style>", out + out2)
code, out = run(GX, "show", "alice/shiny-cat-12")
check(code == 0 and "sélecteurs globaux, à ramener sur le conteneur du composant : body" in out
      and "chargée depuis images.example.com" in out and "<button class" in out,
      "galaxy : show donne le code et ce qui casserait le site (sélecteur body, image chargée ailleurs)", out)
code, out = run(GX, "show", "https://uiverse.io/carol/big-owl-3")
code2, out2 = run(GX, "show", "carol/big-owl-3", "--full")
check(code == 0 and "Trop gros" in out and "/* x */" not in out and code2 == 0 and "/* x */" in out2,
      "galaxy : lien uiverse.io accepté ; élément de plus de 25 Ko seulement avec --full", out + out2[:300])
write("index.html", "<h1>mon site</h1>")
code, out = run(GX, "preview", "alice/shiny-cat-12", "--out", "index.html")
check(code == 1 and "Rien d'écrit" in out and (WORK / "index.html").read_text(encoding="utf-8") == "<h1>mon site</h1>",
      "galaxy : preview n'écrase pas une page qui n'est pas un ancien aperçu", out)

# ================================================================== scrapegraph : sgai.py (bibliothèque absente en CI)
SG = "scrapegraph/scripts/sgai.py"
code, out = run(SG, "--help")
check(code == 0 and "--search N" in out and "prompt" in out, "scrapegraph : --help", out)
code, out = run(SG, "liste les prix")
check(code == 2 and "donner soit une ou plusieurs sources, soit --search N" in out,
      "scrapegraph : ni source ni --search, refus clair (code 2)", out)
if importlib.util.find_spec("scrapegraphai") is None:
    write("page.html", "<h1>Bonjour</h1>")
    code, out = run(SG, "titre de la page", "page.html")
    check(code == 1 and "No module named 'scrapegraphai'" in out and "2. Installer" in out
          and "Traceback" not in out, "scrapegraph : sans la bibliothèque, arrêt clair qui renvoie à l'installation", out)
else:  # installée : l'extraction appellerait le modèle local et le navigateur
    print("· scrapegraphai installé : extraction non lancée")

if not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
