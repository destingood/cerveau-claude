"""Déclenchement des skills du plugin, mesuré (étape 15 du plan, point 5, d'après le routage calibré du guide de
F. Bruniaux) : pour chaque skill, des demandes dites autrement que ses phrases-déclencheurs (elles doivent la
déclencher) et des phrases voisines qui ne la concernent pas (elles ne doivent pas). Le déclenchement repose sur des
phrases, pas sur un score : il n'y a pas de seuil par skill à régler, mais un corpus d'acceptation, avec un plancher de
précision et de rappel qui ne peut que monter. `python tests/test_declencheurs.py -v` montre chaque cas raté.

Lancement : python tests/test_declencheurs.py   (sortie : « N vérifications OK, M échec(s) »)"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-declencheurs-test-"))
CODE = Path(__file__).resolve().parent.parent
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "BRAIN_HOME": str(TMP / "brain")})
sys.path.insert(0, str(CODE))
OK, FAIL = [], []
VERBOSE = "-v" in sys.argv

from brainkit import skills  # noqa: E402
from brainkit.common import remove_tree  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-1200:]}" if detail else ""))


# skill : (demandes qui doivent la déclencher, phrases voisines qui ne doivent pas)
CORPUS = {
    "animation": (["fais bouger le bouton quand on passe la souris", "l'animation de ma page saccade, corrige-la",
                   "ajoute une transition douce entre les pages"],
                  ["j'ai regardé un dessin animé hier soir", "on organise une animation en magasin samedi"]),
    "apprendre-en-livrant": (["j'ai suivi ce cours, aide-moi à le mettre en pratique",
                              "transforme ce tuto UEFN en petits projets à livrer", "je veux apprendre en faisant"],
                             ["livre ce colis demain matin", "j'ai appris la nouvelle ce matin"]),
    "automaton": (["installe automaton sur mon serveur", "lance l'agent automaton", "c'est quoi les crédits Conway"],
                  ["automatise l'envoi de mes factures", "le jeu de la vie de Conway en python"]),
    "carriere-commerciale": (["je voudrais devenir commercial", "aide-moi à préparer un entretien pour un poste de vendeur",
                              "comment négocier mon salaire de commercial"],
                             ["vends mes vieux meubles sur leboncoin", "le salaire minimum en France"]),
    "composants": (["ajoute un composant kokonutui à ma page", "trouve-moi un loader sympa pour mon site",
                    "un fond animé pour mon hero"],
                   ["les composants électroniques de mon PC", "décompose ce problème en étapes"]),
    "cuisine-moi": (["cuisine-moi sur mon idée de boutique", "pose-moi toutes les questions sur mon projet de map",
                     "challenge mon plan avant que je me lance"],
                    ["une recette de cuisine pour ce soir", "j'ai une question sur Python"]),
    "design": (["refais le design de ma landing page", "mon site fait trop template, rends-le plus beau",
                "je veux un site dans le style d'Apple"],
               ["le design de mon salon", "un designer m'a envoyé sa facture"]),
    "ecommerce": (["ma boutique ne vend pas, aide-moi", "trouve-moi des clients sans pub",
                   "fais le tirage au sort du concours de la boutique"],
                  ["achète-moi des chaussures en ligne", "le commerce de mon quartier ferme"]),
    "factures-recus": (["range mes factures de l'année", "prépare un tableau pour mon comptable",
                        "renomme mes factures en vrac"],
                       ["crée une facture pour mon client", "combien coûte un expert-comptable"]),
    "fortnite": (["ma map fortnite n'a pas de joueurs", "quel titre pour ma map UEFN", "les tendances fortnite en ce moment"],
                 ["je joue à fortnite ce soir", "dessine une carte de France"]),
    "logo-design": (["fais-moi un logo pour ma boutique de thé", "critique mon logo", "crée un favicon pour mon site"],
                    ["le logo est en haut à gauche de la page", "envoie le logo au client par mail"]),
    "obsidian": (["fais un kanban dans Obsidian", "ajoute une vue au tableau de bord de mon coffre",
                  "fais un canvas de mes idées"],
                 ["ouvre le fichier de mes notes", "obsidienne : quelle pierre choisir"]),
    "passation": (["fais une passation pour la prochaine session", "prépare la reprise dans une autre session",
                   "écris un document de passation"],
                  ["la passation de pouvoir au conseil municipal", "passe-moi le sel"]),
    "preuve-avant-fini": (["tu as vraiment vérifié que ça marche ?", "montre-moi la preuve que les tests passent",
                           "c'est vraiment fini ?"],
                          ["la preuve que le colis est parti", "j'ai fini mon livre"]),
    "public-apis": (["trouve une API gratuite pour la météo", "une API sans clé pour les taux de change",
                     "des données gratuites pour mon app"],
                    ["l'API de mon site ne répond plus", "explique-moi ce qu'est une API REST"]),
    "rea": (["décompile cet APK", "analyse ce binaire", "rétro-ingénierie de cette appli"],
            ["compile mon projet", "analyse mes ventes du mois"]),
    "recherche": (["fais un dossier sur les pompes à chaleur", "creuse le sujet du dropshipping en France",
                   "recherche approfondie sur les marques de thé"],
                  ["cherche mon fichier de notes", "recherche les doublons dans ce tableau"]),
    "replica": (["clone cette app de prise de notes", "fais ma version de Notion", "refais cette app pour moi"],
                ["clone ce dépôt git", "réplique à ce message"]),
    "securite": (["est-ce que ce code est sécurisé ?", "cherche les failles XSS de mon formulaire",
                  "audite cette skill avant que je l'installe"],
                 ["la sécurité sociale m'a écrit", "ferme bien la porte de sécurité"]),
    "spec-kit": (["installe spec kit dans ce projet", "on part sur du développement piloté par la spec",
                  "lance specify init"],
                 ["les spécifications du téléphone", "un kit de démarrage pour peindre"]),
    "web": (["ouvre ce site et liste les prix", "teste mon site dans le navigateur", "transforme ce site en API"],
            ["le web est lent chez moi", "envoie-moi le lien du site"]),
    "youtube": (["écris le script de ma vidéo", "trouve un titre pour ma vidéo YouTube", "fais des shorts de ma vidéo"],
                ["regarde cette vidéo de chat", "le titre de mon livre"]),
}


def catalog():
    out = []
    for d in sorted((CODE / "skills").iterdir()):
        f = d / "SKILL.md"
        if f.is_file() and d.name != "brain":
            s = skills.parse(f, plugin="cerveau")
            if s:
                out.append(s)
    return out


cat = catalog()
names = {s["name"] for s in cat}
short = {n.partition(":")[2] or n: n for n in names}
check(set(CORPUS) == set(short), "le corpus couvre chaque skill du plugin (hors brain), et rien d'autre",
      sorted(set(CORPUS) ^ set(short)))

hits = total = fires = negs = 0
misses, wrong = [], []
for skill, (pos, neg) in sorted(CORPUS.items()):
    name = short.get(skill)
    for msg in pos:
        total += 1
        got = skills.match(msg, cat)
        if got and got[0]["name"] == name and got[0]["strong"]:
            hits += 1
        else:
            misses.append(f"{skill} « {msg} » → {got[0]['name'] if got else '∅'}")
    for msg in neg:
        negs += 1
        got = [r["name"] for r in skills.match(msg, cat) if r["strong"]]
        if name in got:
            fires += 1
            wrong.append(f"{skill} « {msg} »")
        others = [g for g in got if g != name]
        if others:
            wrong.append(f"« {msg} » → {', '.join(others)}")
recall = hits / max(1, total)
precision = hits / max(1, hits + len(wrong))
f1 = 2 * precision * recall / max(1e-9, precision + recall)
print(f"Déclenchement : rappel {hits}/{total} ({recall:.0%}) · faux déclenchements {len(wrong)} sur {negs} phrases voisines · "
      f"précision {precision:.0%} · F1 {f1:.2f}")
if VERBOSE:
    for m in misses:
        print("  manqué :", m)
    for w in wrong:
        print("  à tort :", w)
# Planchers (le guide demande précision ≥ 0,80 et F1 ≥ 0,70). Mesuré le 24/11 : 92 % et 0,92 avant correction des
# déclencheurs, 100 % et 1,00 après (sur ce même corpus, qui a servi à corriger) ; ces planchers ne peuvent que monter.
check(precision >= 0.95, f"précision ≥ 95 % (mesuré : {precision:.0%})", wrong)
check(f1 >= 0.80, f"F1 ≥ 0,80 (mesuré : {f1:.2f})", misses)
check(not wrong, "aucune phrase voisine ne déclenche une skill du plugin", wrong)

remove_tree(TMP, wait=30)
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
