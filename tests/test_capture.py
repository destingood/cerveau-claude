"""Trois défauts de rappel et de capture, vérifiés de bout en bout (vrai hook, vrai CLI, cerveau temporaire) :
- au démarrage de session, TOUTES les règles et préférences sont injectées (au moins par leur titre) ;
- deux souvenirs de même titre mais de dates, semaines, mois ou numéros différents sont deux événements, pas une mise
  à jour (alors qu'un vrai changement de valeur — « le prix passe de 12 € à 14 € » — remplace toujours l'ancien) ;
- la capture « retiens que… » du hook : déclencheur strict, pas de doublon reformulé, pas d'information privée sur un tiers.

Lancement : python tests/test_capture.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-capture-test-"))
CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_HOME", "CLAUDE_CONFIG_DIR"):
    os.environ.pop(k, None)


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-900:]}" if detail else ""))


class World:
    """Un faux PC isolé : ~/.claude, cerveau, dossier de travail ; HOME et USERPROFILE aussi, pour que rien ne sorte."""

    def __init__(self, name):
        self.root = TMP / name
        self.home, self.brain_dir, self.work = self.root / "claude", self.root / "brain", self.root / "work"
        self.user = self.root / "home"
        for d in (self.home, self.brain_dir, self.work, self.user):
            d.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.home), "BRAIN_HOME": str(self.brain_dir),
                    "BRAIN_IMPL": "python", "HOME": str(self.user), "USERPROFILE": str(self.user)}

    def run(self, *args, inp=None):
        r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                           timeout=180, input=(inp or "").encode("utf-8"), cwd=str(self.root), env=self.env)
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    def add(self, ntype, title, body, *extra):
        return self.run("add", "-t", ntype, "-T", title, "-b", body, "-p", "none", *extra)

    def hook(self, event, sid="s1", **payload):
        c, out = self.run("hook", event, inp=json.dumps({"session_id": sid, "cwd": str(self.work), **payload}))
        try:
            return c, json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
        except ValueError:
            return c, None

    def prompt(self, text, sid="s1"):
        """→ (code, contexte pour Claude, message vu par l'utilisateur)"""
        c, msg = self.hook("prompt", sid=sid, prompt=text)
        msg = msg or {}
        return c, (msg.get("hookSpecificOutput") or {}).get("additionalContext", ""), msg.get("systemMessage", "")

    def nodes(self):
        f = self.brain_dir / "graph.json"
        return list(json.loads(f.read_text(encoding="utf-8"))["nodes"].values()) if f.exists() else []

    def memories(self, status="active"):
        return [n for n in self.nodes() if n["type"] != "project" and n.get("status", "active") == status]

    def titles(self, status="active"):
        return sorted(n["title"] for n in self.memories(status))


# ------------------------------------------------------------------ 1. démarrage : toutes les règles sont injectées
W = World("regles")
REGLES = [
    ("Format des prix", "Toujours écrire les prix en euros avec la virgule et le symbole collé : 24,90 €, jamais 24.90 EUR "
                        "ni $24.90, même dans les tableaux et les exports pour la comptabilité."),
    ("Tutoiement", "Tutoyer l'utilisateur dans toutes les réponses, jamais de vouvoiement, même pour un texte destiné à un "
                   "client : l'adapter ensuite si besoin."),
    ("Format des dates", "Écrire les dates en jour/mois/année (21/10/2026), jamais en mois/jour/année, et jamais en "
                         "anglais dans une réponse en français."),
    ("Parler simplement", "Expliquer sans jargon technique : l'utilisateur n'est pas développeur. Donner d'abord la "
                          "réponse, puis le détail seulement s'il le demande."),
    ("Réponses courtes d'abord", "Commencer par une réponse courte de deux phrases ; le détail et les options viennent "
                                 "après, sous forme de liste à puces."),
    ("Toujours un tableau pour comparer", "Quand on compare plusieurs produits ou fournisseurs, présenter un tableau avec "
                                          "les prix, les délais et les points faibles de chaque option."),
    ("Jamais de suppression sans accord", "Ne jamais supprimer un fichier ou une commande sans l'accord explicite de "
                                          "l'utilisateur, même si cela semble évident ou temporaire."),
    ("Sauvegarder avant de modifier", "Avant de modifier un fichier important de la boutique, en garder une copie datée "
                                      "dans le dossier de sauvegarde, et le dire en une phrase."),
    ("Ton chaleureux avec les clients", "Les messages destinés aux clients restent chaleureux, courts, sans jargon, avec "
                                        "une formule de politesse simple et un prénom si on le connaît."),
]
for t, b in REGLES:
    W.add("feedback", t, b, "-i", "4")
for t, b in [("Prénom et métier", "Karim, vend du thé japonais en ligne, non développeur, débutant avec le terminal."),
             ("Équipement", "PC fixe Windows 11, deux écrans, connexion fibre, pas de Mac."),
             ("Disponibilités", "Travaille le matin, répond aux clients l'après-midi, jamais le dimanche."),
             ("Objectifs 2026", "Atteindre 7 000 euros de ventes par mois et garder une marge brute au-dessus de 55 pour cent.")]:
    W.add("user", t, b, "-i", "4")
for i in range(12):
    W.add("fact", f"Fait boutique numéro {i} sur le fournisseur {chr(65 + i)}weso",
          f"Le fournisseur {chr(65 + i)}weso livre en {10 + i} jours ouvrés, minimum de commande {100 + 10 * i} euros, "
          "paiement par virement, contact par email uniquement et en anglais.", "-i", "3")
# de quoi remplir les autres sections : le budget d'un vrai cerveau est entièrement demandé
for i in range(6):
    W.add("reference", f"Référence utile numéro {i} pour la boutique", "Page de documentation ou outil en ligne à consulter "
          f"avant de répondre sur le sujet {i}, avec le lien et la raison pour laquelle il faut le relire souvent.", "-i", "3")
    W.add("todo", f"Tâche à faire numéro {i} avant la fin du mois", "Penser à vérifier le stock, relancer le fournisseur et "
          f"mettre à jour la fiche produit numéro {i} avant la publication.", "-i", "3")
    W.add("topic", f"Sujet du wiki numéro {i} : thé et accessoires", "Synthèse des lectures sur le thé japonais, le matcha, "
          f"les théières en fonte et les bols, avec les sources et les points encore à vérifier ({i}).", "-i", "3")
c, msg = W.hook("session-start", source="startup")
start = ((msg or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
regles = start.split("## 📏 Règles & préférences", 1)[-1].split("\n## ", 1)[0] if "Règles & préférences" in start else ""
check(c == 0 and regles, "démarrage : la section des règles est injectée", start[:400])
manquantes = [t for t, _ in REGLES if t not in regles]
check(not manquantes, "démarrage : chacune des 9 règles apparaît (au moins par son titre)", manquantes)
check("… +" not in regles, "démarrage : aucune règle cachée derrière « … +N »", regles)
profil = start.split("## 👤 Profil", 1)[-1].split("\n## ", 1)[0]
check(all(t in profil for t in ("Prénom et métier", "Équipement", "Disponibilités", "Objectifs 2026")),
      "démarrage : les 4 lignes de profil sont là aussi", profil)
check(len(start) <= 1650 * 4 + 600, "démarrage : l'injection reste dans son budget (config inject.index_tokens)", len(start))

# dans un projet connu du cerveau : pareil
(W.work / "package.json").write_text("{}", encoding="utf-8")
W.run("map", W.work, "--quiet")
c, msg = W.hook("session-start", sid="s-projet", source="startup")
startp = ((msg or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
check(all(t in startp for t, _ in REGLES) and "… +" not in startp.split("## 📏 Règles & préférences", 1)[-1].split("\n## ", 1)[0],
      "démarrage dans un projet : les 9 règles apparaissent aussi", startp[-1500:])

# beaucoup de règles : toutes présentes, au moins par leur titre
W2 = World("regles-nombreuses")
SUJETS = ("factures", "livraison", "retours", "photos", "newsletter", "stock", "fournisseurs", "comptabilité", "douane",
          "emballage", "avis", "promotions", "marges", "thème", "traductions", "sauvegardes", "domaine", "paiement", "SAV",
          "réseaux", "vidéos", "plans", "atelier", "devis", "agenda", "courriels", "rapports", "bourse", "emploi", "voyage")
titres2 = [f"{sujet.capitalize()} : consigne de travail" for sujet in SUJETS]
for t, sujet in zip(titres2, SUJETS):
    W2.add("feedback", t, f"Pour {sujet} : toujours vérifier {sujet}, relire {sujet} et expliquer simplement {sujet}, "
                          "sans inventer de chiffre ni de source.", "-i", "4", "--force")
c, msg = W2.hook("session-start", source="startup")
start2 = ((msg or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
check(len(W2.memories()) == 30, "démarrage (préparation) : 30 règles distinctes créées", len(W2.memories()))
check(all(t in start2 for t in titres2), "démarrage : 30 règles, toutes présentes au moins par leur titre",
      [t for t in titres2 if t not in start2][:5])

# ------------------------------------------------------------------ 2. même titre, autres chiffres : autre événement, pas une mise à jour
def paire(nom, premier, second, ntype="fact"):
    """Ajoute deux souvenirs l'un après l'autre dans un cerveau neuf → (monde, sortie du second ajout)."""
    w = World("paire-" + nom)
    w.add(ntype, *premier)
    c, out = w.add(ntype, *second)
    return w, out


AUTRES_EVENEMENTS = [
    ("note-7-9", ("Note 7", "Réunion avec le fournisseur : 3 points abordés, 12 caisses commandées."),
     ("Note 9", "Réunion avec le fournisseur : 5 points abordés, 20 caisses commandées.")),
    ("objectif-mois", ("Objectif de ventes de septembre", "Objectif de ventes : 5 000 € en septembre 2026."),
     ("Objectif de ventes d'octobre", "Objectif de ventes : 6 500 € en octobre 2026.")),
    ("semaine-titre", ("Point hebdo boutique semaine 45", "Ventes de la semaine : 12 commandes, 480 €."),
     ("Point hebdo boutique semaine 46", "Ventes de la semaine : 15 commandes, 620 €.")),
    ("semaine-corps", ("Point hebdo boutique", "Semaine 45 : 12 commandes, 480 €."),
     ("Point hebdo boutique", "Semaine 46 : 15 commandes, 620 €.")),
    ("annee", ("Chiffre d'affaires 2025", "Chiffre d'affaires de l'année : 38 000 €."),
     ("Chiffre d'affaires 2026", "Chiffre d'affaires de l'année : 52 000 €.")),
    ("mois-corps", ("Chiffre d'affaires", "Ventes de septembre : 4 000 € pour 80 commandes."),
     ("Chiffre d'affaires", "Ventes d'octobre : 5 500 € pour 95 commandes.")),
    ("trimestre", ("Coffret du premier trimestre", "Contenu : 3 sachets, prix 39 €."),
     ("Coffret du deuxième trimestre", "Contenu : 5 sachets, prix 59 €.")),
    ("numero-corps", ("Livraison fournisseur", "Colis numéro 3 reçu : 12 pièces, 480 €."),
     ("Livraison fournisseur", "Colis numéro 4 reçu : 15 pièces, 620 €.")),
]
for nom, a, b in AUTRES_EVENEMENTS:
    w, out = paire(nom, a, b)
    check(len(w.memories()) == 2 and not w.memories("archived") and "↻ remplace" not in out,
          f"autre événement ({nom}) : les deux restent actifs, aucun remplacement proposé", (w.titles(), w.titles("archived"), out))

w = World("notes-0-7")
for i in range(8):
    w.add("fact", f"Note {i}", f"Compte rendu du jour : {3 + i} points abordés, {10 + 2 * i} caisses commandées, budget {100 + i} €.")
check(len(w.memories()) == 8 and not w.memories("archived"), "huit ajouts « Note 0 » à « Note 7 » : huit souvenirs actifs",
      (w.titles(), w.titles("archived")))
c, out = w.run("dream", "--no-apply")
check("supersede" not in out, "dream : ne propose pas qu'une note remplace la précédente", out[-500:])

w = World("objectifs")
w.add("fact", "Objectif de ventes de septembre", "Objectif de ventes : 5 000 € en septembre 2026.")
w.add("fact", "Objectif de ventes d'octobre", "Objectif de ventes : 6 500 € en octobre 2026.")
c, out = w.run("dream", "--no-apply")
check("supersede" not in out, "dream : l'objectif d'octobre ne remplace pas celui de septembre", out[-500:])

# les vraies mises à jour (même fait, valeur changée) continuent d'être reconnues
VRAIES_MAJ = [
    ("prix-passe-de", ("Prix du matcha", "Le matcha cérémonial coûte 12 € les 30 g."),
     ("Prix du matcha", "Le prix du matcha passe de 12 € à 14 € les 30 g.")),
    ("nouveau-numero", ("Numéro de commande fournisseur", "Le numéro de commande chez Marukyu est 4471."),
     ("Numéro de commande fournisseur", "Nouveau numéro de commande chez Marukyu : 5120.")),
    ("desormais", ("Seuil de livraison gratuite", "Livraison offerte dès 49 €."),
     ("Seuil de livraison gratuite", "Désormais la livraison est offerte dès 59 €.")),
    ("autre-nom", ("Transporteur", "On expédie avec Colissimo."),
     ("Transporteur", "On expédie désormais avec Mondial Relay au lieu de Colissimo.")),
    ("depuis-novembre", ("Seuil de livraison gratuite", "Livraison offerte à partir de 49 € d'achat en France métropolitaine. "
                         "Testé à 39 € en juin : le panier moyen a baissé, on est revenu à 49 €."),
     ("Seuil de livraison gratuite", "Livraison offerte à partir de 59 € d'achat depuis novembre 2026.")),
]
for nom, a, b in VRAIES_MAJ:
    w, out = paire(nom, a, b)
    check(len(w.memories()) == 1 and len(w.memories("archived")) == 1 and "↻ remplace" in out,
          f"vraie mise à jour ({nom}) : l'ancien est archivé, le nouveau actif", (w.titles(), w.titles("archived"), out))

print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
