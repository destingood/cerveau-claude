"""Vérifications de la skill Carrière commerciale (skills/carriere-commerciale) : en-tête, fichiers cités, et ses
trois outils, dans des dossiers temporaires (aucun accès réseau, jamais le vrai journal).

Lancement : python tests/test_carriere.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-carriere-test-"))
CODE = Path(__file__).resolve().parent.parent
SKILL_DIR = CODE / "skills" / "carriere-commerciale"
SCRIPTS = SKILL_DIR / "scripts"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", CARRIERE_HOME=str(TMP / "carriere"))
OK, FAIL = [], []


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def run(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, cwd=str(TMP),
                       timeout=60, env=ENV, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ 1. la skill
skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
front = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check(front is not None, "SKILL.md : en-tête YAML")
meta = dict(re.findall(r"(?m)^(\w+): (.*)$", front.group(1))) if front else {}
check(meta.get("name") == "carriere-commerciale", "SKILL.md : name = carriere-commerciale", meta.get("name"))
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
    check(not re.search(r"urllib|http\.client|socket", texte), f"{o} : aucun accès réseau")
    code, out = run(o)
    check(code in (0, 1) and "Traceback" not in out and len(out) > 100, f"{o} sans argument : mode d'emploi", out)

# ------------------------------------------------------------------ 2. remuneration.py
code, out = run("remuneration.py", "calcul", "--fixe", "32k", "--variable", "12 000", "--atteinte", "40,50,100,150",
                "--seuil", "50", "--accelerateur", "1,5".replace(",", "."), "--plafond", "200", "--json")
r = json.loads(out)
par = {s["atteinte"]: s for s in r["scenarios"]}
check(r["package_a_objectif"] == 44000 and round(r["part_fixe"]) == 73, "remuneration.py : package et part de fixe", r)
check(par[40]["variable"] == 0 and par[50]["variable"] == 6000, "remuneration.py : rien sous le seuil, proportionnel au-dessus")
check(par[150]["variable"] == 12000 * 1.75, "remuneration.py : accélérateur au-delà de 100 %", par[150])
code, out = run("remuneration.py", "calcul", "--fixe", "30000", "--variable", "10000", "--atteinte", "300",
                "--accelerateur", "2", "--plafond", "200", "--json")
check(json.loads(out)["scenarios"][0]["variable"] == 20000, "remuneration.py : plafond respecté")
code, out = run("remuneration.py", "calcul", "--fixe", "30000", "--variable", "10000", "--net", "22", "--json")
s100 = next(s for s in json.loads(out)["scenarios"] if s["atteinte"] == 100)
check(round(s100["net_estime"]) == 31200, "remuneration.py : net estimé au taux donné", s100)
code, out = run("remuneration.py", "comparer", "Startup A;30000;15000;45", "Éditeur B;36 000;8000;75", "--json")
r = json.loads(out)
check([o["nom"] for o in r] == ["Éditeur B", "Startup A"] and r[0]["total"] == 42000 and r[0]["mauvaise_annee"] == 40000
      and r[1]["package_a_objectif"] == 45000, "remuneration.py comparer : classées sur l'attendu, pas l'annonce", r)
code, out = run("remuneration.py", "comparer", "Startup A;30000;15000;45", "Éditeur B;36000;8000;75")
check("Attention : Startup A affiche le plus gros package" in out, "remuneration.py : gros package trompeur signalé", out)
code, out = run("remuneration.py", "calcul", "--fixe", "abc", "--variable", "1")
check(code != 0 and "illisible" in out and "Traceback" not in out, "remuneration.py : montant illisible refusé")

# ------------------------------------------------------------------ 3. progression.py
code, out = run("progression.py", "bilan")
check(code == 1 and "vide" in out, "progression.py : journal vide expliqué")
code, out = run("progression.py", "noter", "--semaine", "2026-W45", "--appels", "220", "--conversations", "28",
                "--rdv", "6", "--opportunites", "3", "--signes", "1", "--ca", "9000", "--objectif-ca", "12000")
check(code == 0 and (TMP / "carriere" / "journal.json").is_file(), "progression.py noter : journal écrit dans CARRIERE_HOME")
run("progression.py", "noter", "--semaine", "2026-W46", "--appels", "250", "--conversations", "35", "--rdv", "8",
    "--opportunites", "4", "--signes", "2", "--ca", "15k", "--objectif-ca", "12000")
code, out = run("progression.py", "noter", "--semaine", "2026-W46", "--mails", "120", "--reponses", "9")
j = json.loads((TMP / "carriere" / "journal.json").read_text(encoding="utf-8"))
check(j["semaines"]["2026-W46"]["appels"] == 250 and j["semaines"]["2026-W46"]["mails"] == 120,
      "progression.py : une semaine se complète sans écraser le reste")
code, out = run("progression.py", "bilan", "--json")
b = json.loads(out)
taux = {t["etape"]: round(t["taux"], 1) for t in b["taux"]}
check(b["totaux"]["appels"] == 470 and taux.get("appels → conversation") == 13.4 and taux.get("messages → réponse") == 7.5,
      "progression.py bilan : totaux et taux", b)
check(b["atteinte_ca"] == 100, "progression.py bilan : objectif de chiffre", b["atteinte_ca"])
code, out = run("progression.py", "preuves", "--json")
p = json.loads(out)
check(any("100 % de l'objectif" in x for x in p) and any("14 rendez-vous" in x for x in p),
      "progression.py preuves : phrases exactes", p)
check(not any("rendez-vous → opportunité" in x for x in p), "progression.py preuves : pas de taux sur moins de 20 essais")
code, out = run("progression.py", "noter", "--semaine", "47", "--appels", "1")
check(code != 0 and "2026-W47" in out, "progression.py : semaine mal écrite refusée")
code, out = run("progression.py", "exporter", TMP / "journal.csv")
csv = (TMP / "journal.csv").read_text(encoding="utf-8-sig")
check(code == 0 and csv.startswith("semaine;") and "2026-W46;250" in csv, "progression.py exporter : CSV à « ; »", csv[:200])

# ------------------------------------------------------------------ 4. cv.py
code, out = run("cv.py", "--modele")
modele = json.loads(out)
(TMP / "cv.json").write_text(out, encoding="utf-8")
code, out = run("cv.py", TMP / "cv.json")
check(code == 1 and not (TMP / "cv.html").exists(), "cv.py : modèle non rempli → rien d'écrit", out)
modele.update(nom="Camille <Test>", contact={"telephone": "06 11 22 33 44", "email": "c.test@exemple.fr"},
              accroche="Je suis dynamique et motivé.")
modele["experiences"] = [{"poste": "Vendeur", "entreprise": "Magasin", "debut": "2025-09", "fin": "2026-06",
                          "resultats": ["Conseil des clients en rayon"]},
                         {"poste": "Équipier", "entreprise": "Club", "debut": "2024", "fin": "septembre",
                          "resultats": ["Trouvé 6 sponsors locaux pour le tournoi du club, 1 200 € récoltés"]}]
(TMP / "cv.json").write_text(json.dumps(modele, ensure_ascii=False), encoding="utf-8")
code, out = run("cv.py", TMP / "cv.json", "--controle")
check(code == 0 and "dynamique, motivé" in out and "Vendeur — Magasin : aucun chiffre" in out
      and "date « septembre »" in out and "Équipier — Club : aucun chiffre" not in out,
      "cv.py --controle : qualités sans preuve, expérience sans chiffre, date mal écrite", out)
code, out = run("cv.py", TMP / "cv.json", "-o", TMP / "sortie" / "cv.html")
html = (TMP / "sortie" / "cv.html").read_text(encoding="utf-8") if code == 0 else ""
check("Camille &lt;Test&gt;" in html and "<Test>" not in html, "cv.py : texte échappé")
check("sept. 2025 – juin 2026" in html and "@page{size:A4" in html, "cv.py : dates en français, page A4")
check(not re.search(r"<script|https?://", html), "cv.py : ni script ni ressource distante")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
