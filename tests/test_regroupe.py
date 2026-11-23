"""`brain regroupe` (étape 8 du plan, « Regrouper ») : doublons reformulés, souvenirs sans projet, sujets à réunir en
fiche — montrés d'abord, appliqués seulement sur accord, annulables.

Monde d'essai : 110 souvenirs fictifs repris du monde de l'audit du 20/11 (une boutique de thé, une chaîne YouTube, une
recherche d'emploi, du trading, un PC), dont des paires de doublons reformulés que la consolidation ne voyait jamais
(« Prétentions salariales » et « Salaire demandé »), des souvenirs sans projet dont le projet se devine, et des
souvenirs globaux qui doivent le rester.

Lancement : python tests/test_regroupe.py   (sortie : « N vérifications OK, M échec(s) »)"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-regroupe-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS", "BRAIN_BG", "BRAIN_TASK"):
    os.environ.pop(k, None)
os.environ["CLAUDE_CONFIG_DIR"] = str(TMP / "claude")  # import en direct de brainkit : jamais le vrai PC
os.environ["BRAIN_HOME"] = str(TMP / "brain")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(TMP / "home")
os.environ["BRAIN_OFFLINE"] = "1"
WORK = TMP / "travail"  # dossier courant hors de tout projet et de tout wiki
for d in (WORK, TMP / "brain", TMP / "home"):
    d.mkdir(parents=True, exist_ok=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))
(TMP / "brain" / "config.json").write_text(json.dumps({
    "auto_map": {"enabled": False}, "eco": {"auto": False}, "backup": {"enabled": False}, "pc": {"enabled": False},
    "promptlib": {"auto": False}, "journal": {"enabled": False}}), encoding="utf-8")

from brainkit import graph  # noqa: E402
from brainkit.common import STATE_DIR, remove_tree  # noqa: E402
from brainkit.store import Brain, clean_tags  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def verify(label, fn):
    """fn() → booléen, ou (booléen, détail). Une exception (commande absente du code d'avant…) compte comme un échec."""
    try:
        res = fn()
    except Exception as exc:
        check(False, label, repr(exc))
        return
    cond, detail = res if isinstance(res, tuple) else (res, "")
    check(bool(cond), label, detail)


def brain(*args):
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), *map(str, args)], capture_output=True,
                       cwd=str(WORK), env=os.environ, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def plan():
    try:
        return json.loads((STATE_DIR / "regroupe.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return []


def node(nid):
    return Brain.load().nodes.get(nid) or {}


PROJETS = [
    ("boutique", "Boutique Maison Yuzu", "Boutique en ligne Shopify de thé japonais (matcha, hojicha) et d'accessoires."),
    ("youtube", "Chaîne YouTube L'Établi", "Chaîne YouTube de bricolage et de menuiserie pour débutants."),
    ("emploi", "Recherche d'emploi", "Recherche d'un poste de chef de projet digital à Lyon ou en télétravail."),
    ("trading", "Trading", "Swing trading sur actions (PEA) et un peu de crypto, avec des règles de risque strictes."),
    ("pc", "Optimisation PC Windows", "Réglages, pannes résolues et entretien du PC fixe sous Windows 11."),
]
# (clé, sorte, projet, titre, contenu, importance, âge en jours, clé du souvenir dont c'est un doublon reformulé)
MONDE = [
    ('b01', 'fact', 'boutique', 'Délai de livraison du fournisseur Atelier Sato',
     "L'atelier Sato (Kyoto) expédie les théières en fonte sous 12 jours ouvrés, par DHL Express. Prévoir 3 semaines avant une promotion pour être livré à temps.", 4, 40, None),
    ('b03', 'decision', 'boutique', 'Transporteur par défaut : Mondial Relay',
     'Depuis octobre 2026 les colis de moins de 2 kg partent en Mondial Relay (4,40 €) au lieu de Colissimo (6,90 €). Pourquoi : la marge sur les petits paniers était mangée par le port. Colissimo reste proposé en option pour la livraison à domicile.', 4, 35, None),
    ('b04', 'fact', 'boutique', 'Seuil de livraison gratuite',
     "Livraison offerte à partir de 49 € d'achat en France métropolitaine. Testé à 39 € en juin : le panier moyen a baissé, on est revenu à 49 €.", 3, 150, None),
    ('b05', 'fact', 'boutique', 'Code promo de bienvenue',
     "BIENVENUE10 : 10 % sur la première commande, envoyé par l'email de bienvenue Klaviyo. Non cumulable avec les soldes.", 3, 200, None),
    ('b06', 'decision', 'boutique', 'Thème Shopify : rester sur Dawn',
     "On garde le thème Dawn (gratuit) plutôt que d'acheter Impulse à 380 $. Pourquoi : Dawn est rapide et suffisant, les sections personnalisées couvrent nos besoins.", 3, 250, None),
    ('b07', 'learning', 'boutique', 'Images produit trop lourdes : passer en WebP',
     "Les photos produit en PNG de 3 Mo ralentissaient la page (LCP 4,8 s). Converties en WebP 1600 px à 82 % de qualité : LCP 2,1 s. Toujours exporter en WebP avant d'envoyer sur Shopify.", 3, 180, None),
    ('b08', 'fact', 'boutique', 'Marge cible par produit',
     'Marge brute visée : 62 % sur le thé, 48 % sur les accessoires (théières, bols). En dessous de 40 % on ne référence pas le produit.', 4, 220, None),
    ('b09', 'fact', 'boutique', 'Prix du matcha cérémonial 30 g',
     'Vendu 24,90 € TTC (achat 8,10 € chez Marukyu). Prix relevé de 22,90 à 24,90 € en septembre 2026 après la hausse du fournisseur.', 3, 60, None),
    ('b11', 'entity', 'boutique', 'Marukyu — fournisseur de matcha (Uji)',
     'Grossiste de thé à Uji. Contact : M. Tanaka. Minimum de commande 300 €. Paiement par virement Wise, 30 % à la commande.', 3, 240, None),
    ('b12', 'entity', 'boutique', 'Atelier Sato — théières en fonte (Kyoto)',
     'Petit atelier familial. Ferme en août. Commandes par email uniquement, en anglais. Minimum 10 pièces par modèle.', 3, 245, None),
    ('b13', 'fact', 'boutique', 'Politique de retour',
     'Retours acceptés sous 14 jours, produit non ouvert, frais de retour à la charge du client sauf erreur de notre part. Remboursement sous 5 jours après réception.', 3, 230, None),
    ('b14', 'learning', 'boutique', "Emails de panier abandonné : le 2e message fait l'essentiel",
     "Séquence Klaviyo en 3 emails (1 h, 24 h, 72 h). Le 2e, avec la photo du produit et sans réduction, récupère 9 % des paniers ; le 3e avec -5 % n'ajoute presque rien. Ne pas brader dès le premier message.", 3, 120, None),
    ('b23', 'fact', 'boutique', "Chiffre d'affaires d'octobre 2026",
     'Octobre 2026 : 6 480 € de ventes, 187 commandes, panier moyen 34,65 €. +18 % par rapport à septembre.', 3, 18, None),
    ('b24', 'fact', 'boutique', "Chiffre d'affaires de septembre 2026",
     'Septembre 2026 : 5 490 € de ventes, 161 commandes, panier moyen 34,10 €.', 3, 48, None),
    ('b25', 'learning', 'boutique', 'Rupture de stock : activer « prévenez-moi »',
     'Quand un produit est épuisé, le bouton « Prévenez-moi du retour » (Klaviyo Back in Stock) récupère en moyenne 22 % des demandes. À activer sur tous les produits.', 3, 110, None),
    ('b34', 'decision', 'boutique', 'Livraison : on passe à Mondial Relay',
     'Les petits colis partent désormais en point relais Mondial Relay, moins cher que Colissimo.', 3, 33, 'b03'),
    ('b35', 'fact', 'boutique', 'Retours et remboursements',
     'Le client a 14 jours pour renvoyer un article non ouvert. Les frais de renvoi sont pour lui. On rembourse dans les 5 jours.', 3, 100, 'b13'),
    ('b45', 'learning', 'boutique', 'Mondial Relay : étiquettes via Boxtal',
     "Les étiquettes Mondial Relay sont achetées sur Boxtal (pas de contrat direct). Import automatique des commandes Shopify, 4,40 € jusqu'à 1 kg.", 3, 30, None),
    ('e01', 'fact', 'emploi', 'Poste recherché',
     'Chef de projet digital / e-commerce, en CDI, à Lyon ou en télétravail complet. Pas de poste purement technique.', 4, 220, None),
    ('e02', 'fact', 'emploi', 'Prétentions salariales',
     'Fourchette annoncée : 48 000 à 52 000 € brut annuel. Ne pas descendre sous 45 000 €.', 4, 200, None),
    ('e03', 'entity', 'emploi', 'Camille Arnaud — recruteuse au cabinet Talentis',
     "Chasseuse de têtes chez Talentis (Lyon). M'a contacté sur LinkedIn en septembre. Très réactive, préfère le téléphone.", 3, 70, None),
    ('e04', 'fact', 'emploi', 'Candidature Nordéa Logistique : entretien passé',
     'Entretien avec la DRH le 12/11/2026 pour le poste de chef de projet e-commerce. Bon contact. Deuxième tour avec le directeur digital prévu début décembre.', 4, 8, None),
    ('e05', 'fact', 'emploi', 'Candidature Groupe Valmont : refus',
     "Refus reçu le 28/10/2026 après le deuxième entretien : profil jugé trop junior en gestion d'équipe.", 3, 23, None),
    ('e06', 'learning', 'emploi', 'Entretien : préparer trois exemples chiffrés',
     'Méthode STAR avec trois exemples chiffrés (refonte du site : +27 % de conversion ; migration ERP livrée dans les délais ; équipe de 4). Les recruteurs retiennent les chiffres.', 4, 150, None),
    ('e07', 'fact', 'emploi', 'CV : version 2026 en une page',
     'CV refait en une page en mars 2026, modèle sobre. Fichier « CV_2026_chef-de-projet.pdf » dans Documents/Emploi.', 3, 240, None),
    ('e08', 'fact', 'emploi', 'Préavis',
     'Préavis de 3 mois dans le poste actuel, négociable à 2 mois selon la RH.', 3, 210, None),
    ('e09', 'reference', 'emploi', 'Tableau de suivi des candidatures',
     'Feuille Google Sheets « Candidatures 2026 » : entreprise, poste, date, contact, statut. 23 candidatures et 6 entretiens au 15/11.', 3, 5, None),
    ('e10', 'learning', 'emploi', 'Lettre de motivation : trois paragraphes',
     'Structure qui marche : vous (leur besoin), moi (une preuve chiffrée), nous (ce que je ferai dans les 90 premiers jours). 200 mots maximum.', 3, 160, None),
    ('e14', 'todo', 'emploi', 'Relancer Nordéa Logistique',
     'Si pas de nouvelles au 27/11, relancer la DRH par email.', 3, 2, None),
    ('e21', 'fact', 'emploi', 'Salaire demandé',
     'Je demande entre 48 et 52 k€ brut par an ; plancher 45 k€.', 3, 90, 'e02'),
    # « rythme » et « calendrier » sont synonymes (le rythme de publication, c'est son calendrier) ; ce seul mot en commun
    # ne fait pas un doublon : même projet, même sorte, deux sujets
    ('e30', 'fact', 'emploi', 'Rythme de travail souhaité',
     'Quatre jours par semaine, télétravail le vendredi ; pas de déplacements fréquents.', 3, 40, None),
    ('e31', 'fact', 'emploi', 'Calendrier des entretiens de décembre',
     'Premier tour en visio le 3 décembre, puis un cas pratique à préparer pour le 10.', 3, 12, None),
    ('g01', 'user', None, 'Profil : Karim, 38 ans, Lyon',
     "Karim, 38 ans, vit à Lyon. Chargé de projet web en poste, tient à côté une boutique en ligne de thé japonais et une chaîne YouTube de bricolage. N'est pas développeur.", 5, 320, None),
    ('g02', 'feedback', None, 'Toujours répondre en français, sans jargon',
     'Réponses en français simple. Expliquer chaque terme technique en une phrase. Pourquoi : je ne suis pas développeur.', 5, 320, None),
    ('g03', 'feedback', None, "Réponse courte d'abord, détail sur demande",
     'Commencer par la réponse en 3 lignes au plus, proposer le détail ensuite. Pourquoi : je lis souvent sur téléphone.', 4, 300, None),
    ('g04', 'feedback', None, 'Ne jamais supprimer un fichier sans demander',
     "Avant toute suppression ou écrasement de fichier, demander confirmation. Pourquoi : perte d'un dossier de photos en 2025.", 5, 310, None),
    ('g05', 'feedback', None, 'Format des prix : 12,90 €',
     'Prix avec une virgule, deux décimales et une espace avant le symbole €. Jamais « 12.9€ ».', 3, 280, None),
    ('g06', 'feedback', None, 'Tutoiement',
     'Me tutoyer. Ton direct, pas de formules de politesse à rallonge.', 3, 315, None),
    ('g07', 'feedback', None, 'Proposer un plan avant de modifier plusieurs fichiers',
     "Quand une demande touche plus de deux fichiers, lister d'abord ce qui va changer et attendre mon accord.", 4, 200, None),
    ('g08', 'user', None, 'Créneaux de travail sur les projets personnels',
     'Travaille sur ses projets personnels le soir après 20 h 30 et le samedi matin.', 3, 290, None),
    ('g09', 'user', None, 'Appareils : PC fixe Windows 11 et iPhone 14',
     'PC fixe sous Windows 11 au bureau de la maison, iPhone 14 pour tout le reste. Pas de Mac.', 3, 295, None),
    ('g10', 'fact', None, 'Comptes Google',
     'Compte Google Workspace de la boutique pour Sheets et Drive. Compte Google personnel séparé pour YouTube.', 3, 270, None),
    ('g11', 'fact', None, 'Vacances à Lisbonne en mai 2027',
     "Semaine du 8 au 15 mai 2027 à Lisbonne, appartement dans l'Alfama. Vol Transavia depuis Lyon déjà réservé.", 3, 30, None),
    ('g12', 'fact', None, 'Voiture : contrôle technique et révision',
     "Peugeot 308 de 2019. Contrôle technique valable jusqu'au 14/03/2027. Révision faite le 06/10/2026 au garage Martin.", 3, 45, None),
    ('g13', 'fact', None, 'Impôts : prélèvement à la source',
     "Taux de prélèvement à la source : 11,2 %. Déclaration du chiffre d'affaires de la micro-entreprise chaque trimestre à l'URSSAF.", 3, 180, None),
    ('g14', 'reference', None, 'Comptable : cabinet Lefèvre',
     'Experte-comptable : Sophie Lefèvre, cabinet Lefèvre & associés à Villeurbanne. Bilan annuel 890 € HT.', 3, 260, None),
    ('g15', 'fact', None, 'Assurance habitation',
     'MAIF, échéance le 1er février, 31 € par mois.', 2, 275, None),
    ('g16', 'learning', None, 'Estimer une tâche : multiplier par deux',
     "Mes estimations de temps sont toujours trop courtes : doubler la durée prévue avant de m'engager sur une date.", 3, 230, None),
    ('g17', 'fact', None, 'Abonnements mensuels',
     "Shopify 36 €, Klaviyo 20 €, Canva Pro 11,99 €, Epidemic Sound 9,99 €, TradingView 13 €, Google Workspace 6,90 €. Total d'environ 98 € par mois.", 3, 50, None),
    ('g18', 'feedback', None, "Un tableau plutôt qu'un long paragraphe pour comparer",
     'Pour comparer deux options ou plus : un tableau court. Pourquoi : plus rapide à lire.', 3, 240, None),
    ('g19', 'feedback', None, 'Dates au format jour/mois/année',
     'Écrire les dates comme 15/11/2026, jamais au format américain.', 3, 250, None),
    ('g20', 'fact', None, 'Banque professionnelle : Qonto',
     'Compte professionnel Qonto pour la micro-entreprise. Carte virtuelle pour les abonnements.', 3, 265, None),
    ('g21', 'fact', None, 'Salle de sport',
     'Abonnement Basic-Fit, séances le lundi et le jeudi à 7 h.', 2, 220, None),
    ('g22', 'todo', None, 'Cadeau de Noël pour Inès',
     'Vélo 20 pouces, à commander avant le 05/12.', 3, 7, None),
    ('g23', 'learning', None, 'Sauvegarder avant toute mise à jour importante',
     "Avant une mise à jour de Windows, de Shopify (thème) ou de DaVinci : sauvegarde d'abord. Deux mauvaises surprises en 2025.", 4, 255, None),
    ('g25', 'decision', None, 'Un seul projet par soir',
     "Pour ne pas s'éparpiller : boutique le lundi et le mardi, chaîne YouTube le mercredi et le samedi, trading le dimanche soir.", 4, 140, None),
    ('g26', 'fact', None, 'Objectif 2027 : vivre de la boutique et de la chaîne',
     'Objectif : 3 000 € nets par mois cumulés boutique et YouTube fin 2027 pour quitter le salariat.', 4, 150, None),
    ('g27', 'feedback', None, 'Parler simplement, en français',
     'Écrire en français courant et éviter les mots techniques non expliqués.', 3, 120, 'g02'),
    ('g28', 'fact', None, "Fournisseur d'accès à Internet : Free",
     'Freebox Pop, fibre. Assistance au 3244.', 2, 300, None),
    ('g29', 'learning', None, 'Relire chaque commande avant de valider',
     "Dans Claude Code, lire la commande proposée avant d'accepter, surtout si elle contient rm, del ou format.", 4, 210, None),
    ('g30', 'fact', None, 'Imprimante 3D : Bambu Lab A1 mini',
     "Sert pour les gabarits de l'atelier. Filaments PLA et PETG.", 2, 135, None),
    ('g31', 'todo', None, 'Prendre rendez-vous chez la comptable pour le bilan',
     'À faire avant le 15/12.', 3, 9, None),
    ('g32', 'user', None, 'Langues parlées',
     'Français langue maternelle, anglais niveau B2, arabe parlé.', 2, 305, None),
    ('g33', 'reference', None, 'Dossier des documents administratifs',
     'Dossier « Administratif » sur Google Drive : impôts, URSSAF, assurances, classés par année.', 3, 245, None),
    ('g34', 'learning', None, 'Notion : une base par projet',
     "Une base Notion par projet (boutique, chaîne, emploi) plutôt qu'une seule page fourre-tout : on retrouve tout plus vite.", 3, 175, None),
    ('o01', 'fact', None, 'Klaviyo : segment des clients VIP',
     'Segment « VIP » : clients avec 3 commandes ou plus, ou plus de 150 € dépensés. 64 personnes. Reçoivent les nouveautés 48 h avant les autres.', 3, 55, None),
    ('o02', 'learning', None, 'Idée : vendre des kits de bricolage en lien avec la chaîne',
     "Des abonnés demandent des kits prêts à monter (bois débité et quincaillerie). À tester avec le kit de l'étagère murale, vendu sur une petite boutique Shopify séparée.", 3, 28, None),
    ('o03', 'fact', None, "Alerte de prix sur l'action Hermès",
     'Alerte TradingView posée à 2 150 € sur Hermès (cassure du plus haut de 20 jours).', 3, 6, None),
    ('o04', 'learning', None, "DaVinci Resolve plante à l'export : mettre à jour le pilote Nvidia Studio",
     "Les plantages à l'export H.265 ont cessé avec le pilote Nvidia Studio 565.90 (et non le pilote Game Ready).", 3, 38, None),
    ('o05', 'fact', None, 'Entretien Nordéa : salle et accès',
     "Les locaux de Nordéa Logistique sont au 12 quai Perrache, 4e étage. Se présenter à l'accueil avec une pièce d'identité.", 3, 9, None),
    ('p01', 'fact', 'pc', 'Configuration du PC',
     'Ryzen 7 5800X3D, carte mère MSI B550 Tomahawk, 32 Go de DDR4 3600 CL16, RTX 4070, SSD NVMe Samsung 980 Pro 1 To, alimentation Corsair RM750x. Windows 11 Pro.', 4, 300, None),
    ('p02', 'learning', 'pc', 'Écran bleu WHEA : désactiver le PBO',
     'Écrans bleus WHEA_UNCORRECTABLE_ERROR au repos. Cause : Precision Boost Overdrive avec une courbe négative trop agressive (-30). Réglé en remettant le Curve Optimizer à -15.', 4, 200, None),
    ('p03', 'fact', 'pc', 'BIOS : profil XMP activé',
     'Profil XMP 1 activé (3600 MHz CL16). BIOS version 7C91vAH. Mise à jour faite le 02/04/2026.', 3, 230, None),
    ('p04', 'learning', 'pc', 'Micro-saccades en jeu : désactiver les optimisations plein écran',
     "Les saccades dans les jeux venaient des optimisations plein écran et de la barre de jeu Xbox. Désactivées : temps d'image stable.", 3, 150, None),
    ('p05', 'fact', 'pc', "Plan d'alimentation",
     "Plan « Performances élevées » sur secteur. Mise en veille de l'écran après 10 minutes, jamais de veille prolongée.", 3, 210, None),
    ('p06', 'learning', 'pc', 'Pilotes graphiques : toujours passer par DDU',
     "Avant d'installer un nouveau pilote Nvidia : désinstaller l'ancien avec DDU en mode sans échec. L'installation par-dessus a causé des plantages en mars.", 3, 240, None),
    ('p07', 'fact', 'pc', 'Températures normales',
     'Processeur : 42 °C au repos, 78 °C en jeu. Carte graphique : 68 °C en charge. Au-delà de 85 °C sur le processeur, vérifier la pâte thermique.', 3, 180, None),
    ('p08', 'decision', 'pc', 'Sauvegarde : Veeam Agent au lieu de Macrium',
     'Sauvegarde hebdomadaire du disque système avec Veeam Agent (gratuit) vers le disque dur externe de 4 To. Macrium Reflect est devenu payant.', 3, 170, None),
    ('p09', 'fact', 'pc', 'Programmes au démarrage',
     'Seuls Discord, Steam et le pilote audio démarrent avec Windows. Tout le reste est désactivé dans le Gestionnaire des tâches. Démarrage en 14 secondes.', 3, 160, None),
    ('p10', 'learning', 'pc', 'Mise à jour Windows 24H2 : bug du Wi-Fi',
     "Après la mise à jour 24H2, le Wi-Fi Intel AX200 se déconnectait. Corrigé avec le pilote 23.60 du site d'Intel (pas celui de Windows Update).", 3, 90, None),
    ('p13', 'fact', 'pc', 'Écran : 1440p 165 Hz',
     "Écran LG 27GP850 1440p 165 Hz, G-Sync activé, limite d'images à 162 par seconde dans le panneau Nvidia.", 3, 250, None),
    ('p22', 'learning', 'pc', 'Réinstallation propre de Windows : procédure',
     "Réinstallation propre de Windows 11, faite le 18/01/2026. Avant : sauvegarde complète avec Veeam, export des favoris, liste des logiciels (winget export), clé BitLocker notée. Création de la clé USB avec l'outil Media Creation Tool. Pendant l'installation : débrancher le deuxième SSD pour que le chargeur de démarrage n'aille pas dessus, supprimer toutes les partitions du SSD système, compte local d'abord. Après : pilotes de la carte mère depuis le site MSI (chipset AMD en premier), puis pilote Nvidia, puis Windows Update. Réglages à refaire : plan d'alimentation Performances élevées, démarrage rapide désactivé, optimisations plein écran désactivées, fichier d'échange à 16 Go. Durée totale : 2 h 30. Gain : démarrage passé de 31 à 14 secondes.", 3, 300, None),
    ('p23', 'learning', 'pc', 'Installer un pilote Nvidia proprement',
     'Passer DDU en mode sans échec, puis installer le nouveau pilote (installation personnalisée, sans GeForce Experience).', 3, 80, 'p06'),
    ('t01', 'decision', 'trading', 'Risque maximum : 1 % du capital par trade',
     'Jamais plus de 1 % du capital risqué par position (stop compris). Capital de trading : 15 000 €, donc 150 € de perte maximale par trade.', 5, 300, None),
    ('t02', 'decision', 'trading', "Pas d'effet de levier",
     'Aucun levier ni produit dérivé (CFD, turbos). Raison : perte de 2 300 € en 2024 sur des CFD.', 5, 310, None),
    ('t03', 'fact', 'trading', 'Courtier actions : Bourse Direct (PEA)',
     "PEA chez Bourse Direct. Frais : 0,99 € jusqu'à 500 €, 1,90 € jusqu'à 2 000 €. Compte-titres ordinaire chez Trade Republic.", 3, 280, None),
    ('t04', 'decision', 'trading', 'Crypto : passage de Binance à Kraken',
     'Compte crypto transféré de Binance à Kraken en mai 2026. Pourquoi : frais plus clairs et retraits SEPA gratuits. Compte Binance fermé.', 3, 180, None),
    ('t06', 'fact', 'trading', 'Stratégie : cassure au-dessus de la moyenne mobile 50 jours',
     "Swing trading : achat sur cassure d'un plus haut de 20 jours si le cours est au-dessus de la MM50 et que la MM50 monte. Sortie si clôture sous la MM20.", 4, 260, None),
    ('t07', 'fact', 'trading', 'Investissement mensuel programmé',
     "300 € par mois sur l'ETF MSCI World (CW8) dans le PEA, le 5 de chaque mois. Ne pas y toucher avant 2040.", 4, 290, None),
    ('t08', 'learning', 'trading', 'Ne pas trader les annonces de résultats',
     'Trois pertes sur quatre trades pris la veille de résultats trimestriels. Règle : pas de position ouverte 2 jours avant une publication.', 3, 140, None),
    ('t09', 'fact', 'trading', 'Fiscalité : flat tax de 30 %',
     "Plus-values du compte-titres et des cryptos : prélèvement forfaitaire unique de 30 %. PEA : exonéré d'impôt après 5 ans (prélèvements sociaux de 17,2 %).", 3, 230, None),
    ('t10', 'reference', 'trading', 'Journal de trades',
     "Fichier Excel « Journal_trades_2026.xlsx » : date, titre, entrée, stop, sortie, R obtenu, capture d'écran. Rempli le soir même.", 3, 250, None),
    ('t11', 'fact', 'trading', "Bilan des trades d'octobre 2026",
     'Octobre 2026 : 11 trades, 6 gagnants, +2,8 R au total, soit +420 €. Meilleur trade : Schneider Electric (+2,1 R).', 3, 17, None),
    ('t14', 'fact', 'trading', 'Liste de surveillance actuelle',
     'Titres suivis : Schneider Electric, Air Liquide, ASML, Hermès, Vinci. Crypto : bitcoin et ether uniquement.', 3, 9, None),
    ('t17', 'fact', 'trading', "Outils d'analyse",
     "Graphiques sur TradingView (abonnement Essential, 13 € par mois). Filtre d'actions sur Zonebourse. Alertes de prix sur TradingView.", 3, 240, None),
    ('t19', 'fact', 'trading', "Déclaration des comptes à l'étranger",
     'Trade Republic (Allemagne) et Kraken (États-Unis) à déclarer chaque année sur les formulaires 3916 et 3916-bis.', 3, 150, None),
    ('t21', 'fact', 'trading', 'Capital de trading',
     "15 000 € dédiés au swing trading dans le PEA. Le reste (ETF) n'est pas du capital de trading.", 3, 205, None),
    ('t22', 'decision', 'trading', 'Gestion du risque par position',
     "Je ne risque jamais plus d'un pour cent du capital sur un trade, stop inclus.", 3, 100, 't01'),
    ('t23', 'todo', 'trading', 'Faire la déclaration des plus-values crypto',
     "Formulaire 2086 à remplir avant mai 2027. Exporter l'historique Kraken en CSV.", 3, 20, None),
    ('t25', 'learning', 'trading', 'Routine du dimanche soir',
     "Routine du dimanche soir pour préparer la semaine de bourse. 1) Regarder la tendance du CAC 40 et du S&P 500 en hebdomadaire : si les deux sont sous leur moyenne mobile 50 jours, aucun nouvel achat. 2) Passer le filtre Zonebourse : actions au plus haut de 20 jours avec volume supérieur à la moyenne. 3) Garder cinq titres au plus dans la liste de surveillance et tracer les niveaux d'entrée et de stop sur TradingView. 4) Calculer la taille de chaque position avec la règle des 150 € de risque. 5) Poser les alertes de prix. 6) Relire le journal de la semaine passée et noter une seule chose à corriger. Durée : 45 minutes, pas plus.", 3, 165, None),
    ('t30', 'fact', 'trading', 'Dividendes réinvestis',
     "Les dividendes du PEA sont réinvestis dans l'ETF World chaque trimestre.", 2, 185, None),
    ('y01', 'fact', 'youtube', 'Rythme de publication',
     'Une vidéo chaque dimanche à 18 h. Un Short le mercredi, tiré de la vidéo précédente.', 4, 200, None),
    ('y02', 'fact', 'youtube', 'Matériel de tournage',
     'Caméra Sony ZV-E10 avec objectif Sigma 16 mm f/1.4, micro Rode Wireless Go II, deux panneaux LED Neewer. Trépied Manfrotto.', 3, 300, None),
    ('y03', 'decision', 'youtube', 'Montage sur DaVinci Resolve',
     'On monte sur DaVinci Resolve (gratuit) et plus sur Premiere Pro : abonnement Adobe arrêté en février 2026 (26 € par mois économisés).', 3, 270, None),
    ('y04', 'learning', 'youtube', 'Miniatures : visage et 3 mots maximum',
     "Les miniatures avec mon visage, l'objet fini et 3 mots au plus font 7,4 % de taux de clic, contre 4,1 % pour celles avec beaucoup de texte. Fond jaune ou bleu vif.", 4, 150, None),
    ('y05', 'fact', 'youtube', "Durée idéale d'une vidéo",
     'Les vidéos de 10 à 14 minutes ont la meilleure rétention (48 %). Au-delà de 20 minutes la rétention tombe à 31 %.', 3, 140, None),
    ('y06', 'fact', 'youtube', "Réglages d'export",
     "Export en 4K à 25 images par seconde, H.265, débit 45 Mb/s, audio AAC 320 kb/s. Fichier d'environ 4 Go pour 12 minutes.", 3, 260, None),
    ('y07', 'fact', 'youtube', "Nombre d'abonnés",
     '12 400 abonnés au 15/11/2026. Objectif : 20 000 en juin 2027. +900 abonnés en octobre.', 3, 5, None),
    ('y09', 'entity', 'youtube', 'Sponsor : Outillage Durand',
     "Partenariat avec Outillage Durand (quincaillerie en ligne) : 450 € par vidéo sponsorisée, une intégration de 60 secondes, lien affilié à 8 %. Contact : Élodie Marchand. Contrat jusqu'en mars 2027.", 4, 80, None),
    ('y10', 'learning', 'youtube', 'Les 30 premières secondes décident de tout',
     'Montrer le résultat fini dès les 5 premières secondes puis annoncer les étapes. Les vidéos avec ce début gardent 71 % des spectateurs à 30 s, contre 52 %.', 4, 130, None),
    ('y11', 'fact', 'youtube', 'Musique : Epidemic Sound',
     'Abonnement Epidemic Sound à 9,99 € par mois. Ne jamais utiliser une musique de la bibliothèque audio YouTube déjà entendue partout.', 3, 250, None),
    ('y24', 'fact', 'youtube', 'Calendrier de sortie des vidéos',
     "Sortie de la vidéo longue tous les dimanches en fin d'après-midi (18 h).", 3, 60, 'y01'),
]


TODAY = dt.date(2026, 11, 20)


def stamp(age, i):
    d = dt.datetime.combine(TODAY - dt.timedelta(days=age), dt.time(9 + i % 9, (i * 7) % 60, 0))
    return d.isoformat(timespec="seconds")


ids, PAIRES = {}, []
with Brain.edit() as b:
    for i, (key, title, body) in enumerate(PROJETS):
        path = TMP / "projets" / key
        path.mkdir(parents=True)
        n = b.add("project", title, body, source="utilisateur", meta={"path": str(path)}, nid=key)
        n["created"] = n["updated"] = stamp(330 - i, i)
        ids[key] = n["id"]
    for i, (key, ntype, proj, title, body, imp, age, dup) in enumerate(sorted(MONDE, key=lambda m: -m[6])):
        n = b.add(ntype, title, body, tags=clean_tags(graph.concept_tags(f"{title}\n{body}")),
                  project=ids[proj] if proj else None, importance=imp, source="claude")
        for s, m in b.similar(title, body, None, exclude=n["id"], threshold=0.5)[:2]:  # comme `brain add`
            b.link(n["id"], m["id"], "relates")
        n["created"] = stamp(age, i)
        n["updated"] = stamp(age, i)
        ids[key] = n["id"]
    for key, *_, dup in MONDE:
        if dup:
            PAIRES.append(frozenset((ids[key], ids[dup])))
    # même titre et même texte, deux projets : jamais un doublon (« Objectif du mois » de la boutique et de la chaîne)
    for proj in ("boutique", "youtube"):
        n = b.add("fact", "Objectif du mois", "Atteindre l'objectif du mois avant le 30/11, sans exception.",
                  project=proj, source="claude")
        ids[f"objectif-{proj}"] = n["id"]
    b.nodes[ids["e02"]]["hits"], b.nodes[ids["e21"]]["hits"] = 2, 3
    b.nodes[ids["e02"]]["last_hit"], b.nodes[ids["e21"]]["last_hit"] = stamp(10, 0), stamp(3, 0)
    b.dirty = True

# ------------------------------------------------------------------------------------------ montrer
code, out = brain("regroupe")
check(code == 0, "`brain regroupe` montre la liste (code 0)", out)
check("Rien n'est appliqué sans ton accord" in out and "--appliquer" in out, "la liste dit comment appliquer", out)
items = plan()
dups = [it for it in items if it.get("kind") == "doublon"]
found = {frozenset((it["keep"], it["drop"])) for it in dups}
check(len(found & set(PAIRES)) >= 5, f"doublons reformulés trouvés : {len(found & set(PAIRES))} paires sur {len(PAIRES)}",
      [sorted(p) for p in found])
for a, b_ in (("e02", "e21"), ("b13", "b35"), ("p06", "p23"), ("b03", "b34")):
    check(frozenset((ids[a], ids[b_])) in found, f"doublon reformulé proposé : « {node(ids[a]).get('title')} » et "
          f"« {node(ids[b_]).get('title')} »", out)
check(not (found - set(PAIRES)), "aucun autre doublon proposé (pas de faux doublon)",
      [(node(a).get("title"), node(c).get("title")) for a, c in map(sorted, found - set(PAIRES))])
check(all((node(it["keep"]).get("project") or None) == (node(it["drop"]).get("project") or None) for it in dups),
      "jamais un doublon entre deux projets")
check(frozenset((ids["objectif-boutique"], ids["objectif-youtube"])) not in found,
      "« Objectif du mois » de la boutique et de la chaîne : même titre, même texte, deux projets — jamais proposé")
check(frozenset((ids["b23"], ids["b24"])) not in found,
      "chiffre d'affaires de septembre et d'octobre : une série, pas un doublon")
check(frozenset((ids["y01"], ids["y24"])) in found, "doublon reformulé proposé : « Rythme de publication » et "
      "« Calendrier de sortie des vidéos » (rythme ≈ calendrier : la paire que l'étape 8 manquait)", out)
check(frozenset((ids["e30"], ids["e31"])) not in found and not {ids["e30"], ids["e31"]} & {i for p in found for i in p},
      "« Rythme de travail souhaité » et « Calendrier des entretiens » : un synonyme en commun ne fait pas un doublon",
      [(node(a).get("title"), node(c).get("title")) for a, c in map(sorted, found)])
check(not [it for it in items if it.get("kind") == "doublon"
           and {node(it["keep"]).get("type"), node(it["drop"]).get("type")} - {node(it["keep"]).get("type")}],
      "un doublon est toujours entre deux souvenirs de même sorte")

att = {it["id"]: it for it in items if it.get("kind") == "projet"}
check(att.get(ids["o05"], {}).get("project") == "emploi", "souvenir sans projet « Entretien Nordéa : salle et accès » "
      "→ rattachement proposé à la recherche d'emploi", out)
check("Nordéa" in " ".join(att.get(ids["o05"], {}).get("why", [])), "le rattachement dit pourquoi (le nom Nordéa, cité "
      "seulement par la recherche d'emploi)", att.get(ids["o05"]))
check(att.get(ids["o04"], {}).get("project") == "pc", "« DaVinci Resolve plante à l'export : … pilote Nvidia » → "
      "rattachement proposé au PC", out)
# Klaviyo n'est cité que par la boutique, mais ici ses plus proches souvenirs sont épars et sa communauté du graphe n'a
# pas de projet : un seul indice ne suffit pas
check(ids["o01"] not in att, "un seul indice (un nom propre) ne suffit pas pour proposer un rattachement",
      att.get(ids["o01"]))
check(all(len(it["why"]) >= 2 for it in att.values()), "chaque rattachement repose sur au moins deux indices",
      [it["why"] for it in att.values()])
check(not [i for i in att if node(i).get("type") in ("user", "feedback")], "le profil et les règles ne sont jamais "
      "rattachés à un projet")
check(ids["g22"] not in att, "« Cadeau de Noël pour Inès » reste global (le mot Noël ne fait pas un projet)", att.get(ids["g22"]))
wrong = [(node(i).get("title"), it["project"]) for i, it in att.items()
         if i not in (ids["o01"], ids["o02"], ids["o03"], ids["o04"], ids["o05"])]
check(not wrong, "aucun souvenir global rattaché à tort", wrong)

fiches = [it for it in items if it.get("kind") == "fiche"]
check(fiches, "au moins un sujet à réunir en fiche", out)
check(all(len({node(i).get("project") for i in it["ids"]}) == 1 and len(it["ids"]) >= 3 for it in fiches),
      "une fiche réunit au moins trois souvenirs d'un même projet")
check(all(n_ == k for k, n_ in enumerate((it["n"] for it in items), 1)), "les propositions sont numérotées 1, 2, 3…")


# Un gros cerveau a des centaines de sujets ; l'analyse (lue par les hooks) n'en garde que les 40 plus cités, et un sujet
# de 3 à 12 souvenirs n'y est presque jamais. Simulé ici : l'analyse ne garde que les 2 plus cités. Les fiches viennent
# de tous les sujets (graph.concepts_all), l'analyse et ce qu'en voient les hooks ne changent pas.
def fiches_hors_analyse():
    from brainkit import regroupe
    saved = (STATE_DIR / "regroupe.json").read_bytes()  # la liste montrée plus haut : les essais suivants l'appliquent
    real = graph._concepts
    graph._concepts = lambda nodes: real(nodes)[:2]
    try:
        kept = graph.ensure(Brain.load(), force=True).get("concepts", [])
        got = [it for it in regroupe.propose(Brain.load()) if it["kind"] == "fiche"]
    finally:
        graph._concepts = real
        graph.ensure(Brain.load(), force=True)
        (STATE_DIR / "regroupe.json").write_bytes(saved)
    want = {(it["key"], it["project"]) for it in fiches}
    have = {(it["key"], it["project"]) for it in got}
    return len(kept) == 2 and want and have == want, (len(kept), sorted(want), sorted(have))


verify("un sujet hors des concepts que garde l'analyse est quand même proposé en fiche (tous les sujets, pas les 40 "
       "plus cités)", fiches_hors_analyse)
verify("l'analyse lue par les hooks garde ses 40 concepts au plus, les mêmes qu'avant",
       lambda: (len(graph.ensure(Brain.load()).get("concepts", [])) <= 40
                and graph._concepts(list(Brain.load().active())) == graph.concepts_all(list(Brain.load().active()))[:40],
                len(graph.ensure(Brain.load()).get("concepts", []))))

# ------------------------------------------------------------------------------------------ erreurs
code, out = brain("regroupe", "--appliquer", str(len(items) + 5))
check(code == 1 and "numéro inconnu" in out and "✗" in out, "numéro qui n'existe pas → code 1 et message en français",
      (code, out))
code, out = brain("regroupe", "--appliquer", "abc")
check(code == 1 and "n'est pas un numéro" in out, "« --appliquer abc » → code 1 et l'exemple à suivre", (code, out))
code, out = brain("regroupe", "--appliquer", "1", "--ecarter", "2")
check(code == 2, "--appliquer et --ecarter ensemble → code 2 (commande mal écrite)", (code, out))
check(node(ids["e21"]).get("status", "active") == "active" and node(ids["e02"]).get("status", "active") == "active",
      "une erreur n'a rien appliqué")

# ------------------------------------------------------------------------------------------ appliquer une partie
num = {it["kind"] + ":" + (it.get("drop") or it.get("id") or it.get("key")): it["n"] for it in items}
NONE = {"n": 0, "keep": "?", "drop": "?", "ids": [], "key": "?"}  # proposition absente (code d'avant) : les essais échouent
d_salaire = next((it for it in dups if {it["keep"], it["drop"]} == {ids["e02"], ids["e21"]}), NONE)
other_dup = next((it for it in dups if it["n"] != d_salaire["n"]), NONE)
a_nordea = att.get(ids["o05"]) or NONE
fiche = fiches[0] if fiches else NONE
chosen = f"{d_salaire['n']},{a_nordea['n']},{fiche['n']}"
created_before = min(node(ids["e02"]).get("created"), node(ids["e21"]).get("created"))
before_snaps = len(list((TMP / "brain" / "history").glob("graph-*avant-regroupement*")))
code, out = brain("regroupe", "--appliquer", chosen)
check(code == 0 and "brain restore 1" in out, f"`brain regroupe --appliquer {chosen}` (code 0, dit comment annuler)",
      (code, out))
check(len(list((TMP / "brain" / "history").glob("graph-*avant-regroupement*"))) == before_snaps + 1,
      "un instantané est pris avant d'appliquer")
keep, drop = node(d_salaire["keep"]), node(d_salaire["drop"])
check(drop.get("status") == "archived" and (drop.get("meta") or {}).get("merged_into") == keep.get("id"),
      "le doublon fusionné est archivé, avec le souvenir qui le reprend", drop)
check("48 000" in keep.get("body", "") and "48 et 52 k€" in keep.get("body", ""),
      "le souvenir gardé contient les deux textes (rien de perdu)", keep.get("body"))
check(keep.get("hits") == 5 and keep.get("last_hit") == stamp(3, 0), "compteurs de rappel des deux additionnés, dernier "
      "rappel gardé", (keep.get("hits"), keep.get("last_hit")))
check(keep.get("created") == created_before, "date de création : la plus ancienne des deux",
      (keep.get("created"), created_before))
check("salaire demand" in str((keep.get("meta") or {}).get("keys", "")).lower()
      or "prétentions salariales" in str((keep.get("meta") or {}).get("keys", "")).lower(),
      "le titre du doublon devient un mot-clé du souvenir gardé (retrouvé sous ses deux formulations)", keep.get("meta"))
code, out = brain("q", "--no-files", "Salaire demandé")
check(keep.get("id", "?") in out, "`brain q` retrouve le souvenir gardé avec l'ancienne formulation", out)
check(node(other_dup["drop"]).get("status", "active") == "active", "les doublons non choisis ne sont pas fusionnés")
check(node(ids["o05"]).get("project") == "emploi", "le souvenir choisi est rattaché à son projet")
others = [i for i in att if i != ids["o05"]]
check(all(not node(i).get("project") for i in others), "les rattachements non choisis ne sont pas faits")
g = Brain.load()
made = [n for n in g.nodes.values() if (n.get("meta") or {}).get("fiche") == fiche.get("key")]
check(len(made) == 1 and made[0]["type"] == "reference", "la fiche est créée (une référence)", made)
if made:
    f = made[0]
    linked = {e["from"] for e in g.edges if e["to"] == f["id"] and e["rel"] == "part_of"}
    check(linked == set(fiche["ids"]), "chaque souvenir de la fiche lui est relié", (linked, fiche["ids"]))
    check(all(g.nodes[i].get("status", "active") == "active" for i in fiche["ids"]), "aucun souvenir de la fiche n'est "
          "archivé ni effacé")
    check(all(f"`{i}`" in f.get("body", "") for i in fiche["ids"]), "la fiche cite chacun de ses souvenirs par son id")
code, out = brain("regroupe", "--appliquer", chosen)
check(code == 1 and out.count("déjà appliqué") == 3, "réappliquer les mêmes numéros : rien de fait deux fois (code 1)",
      (code, out))

# ------------------------------------------------------------------------------------------ annuler
code, out = brain("restore", "1")
check(code == 0, "`brain restore 1` annule le regroupement", out)
check(node(d_salaire["drop"]).get("status", "active") == "active" and node(d_salaire["keep"]).get("hits") in (2, 3),
      "après restauration : le doublon est de nouveau actif, ses compteurs d'avant")
check(not node(ids["o05"]).get("project"), "après restauration : le souvenir est de nouveau sans projet")
check(not [n for n in Brain.load().nodes.values() if (n.get("meta") or {}).get("fiche")],
      "après restauration : la fiche a disparu")

# ------------------------------------------------------------------------------------------ souvenir changé, écarté
code, out = brain("regroupe")
items = plan()
d2 = next((it for it in items if it.get("kind") == "doublon"), None)
if d2:
    with Brain.edit() as b:
        b.update(d2["keep"], body=b.nodes[d2["keep"]]["body"] + " (précisé depuis)")
        b.nodes[d2["keep"]]["updated"] = "2099-01-01T00:00:00"
    code, out = brain("regroupe", "--appliquer", d2["n"])
    check(code == 1 and "a changé depuis la liste" in out, "un souvenir modifié depuis la liste : la proposition n'est "
          "pas appliquée (code 1)", (code, out))
    check(node(d2["drop"]).get("status", "active") == "active", "… et rien n'a été fusionné")
    code, out = brain("regroupe")
    items = plan()
    d3 = next((it for it in items if it.get("kind") == "doublon"), NONE)
    code, out = brain("regroupe", "--ecarter", d3["n"])
    check(code == 0 and "plus proposé" in out, "`--ecarter` : la proposition ne sera plus faite", (code, out))
    code, out = brain("regroupe")
    check(not [it for it in plan() if it.get("kind") == "doublon" and {it["keep"], it["drop"]} == {d3["keep"], d3["drop"]}],
          "la proposition écartée n'est plus dans la liste", out)
else:
    check(False, "une seconde liste de doublons pour les derniers essais", out)
(STATE_DIR / "regroupe.json").unlink(missing_ok=True)
code, out = brain("regroupe", "--appliquer", "1")
check(code == 1 and "lance d'abord `brain regroupe`" in out, "sans liste : « lance d'abord brain regroupe » (code 1)",
      (code, out))

# ------------------------------------------------------------------------------------------ consolidation (même fusion)
with Brain.edit() as b:
    x = b.add("fact", "Code wifi de l'atelier", "Le réseau de l'atelier s'appelle Etabli-5G.", project="youtube",
              source="claude")
    y = b.add("fact", "Code wifi de l'atelier", "Le réseau de l'atelier s'appelle Etabli-5G.", project="youtube",
              source="claude", nid="code-wifi-de-l-atelier-bis")
    x["hits"], y["hits"] = 1, 4
    xid, yid = x["id"], y["id"]
code, out = brain("consolidate")
gx, gy = node(xid), node(yid)
merged = [n for n in (gx, gy) if n.get("status") == "archived"]
kept = [n for n in (gx, gy) if n.get("status", "active") == "active"]
check(code == 0 and len(merged) == 1 and len(kept) == 1 and kept[0].get("hits") == 5,
      "`brain consolidate` fusionne toujours les copies exactes, compteurs additionnés (même fusion que regroupe)",
      (code, out, gx.get("hits"), gy.get("hits")))

if not remove_tree(TMP, wait=60):  # tâches de fond du cerveau testé : on attend qu'elles aient fini d'y écrire
    print(f"(dossier pas effacé : {TMP})")
print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
