# =============================================================================
#  ARÈNE PRESTIGE — Données sauvegardées, règles du pass et arsenal
# -----------------------------------------------------------------------------
#  Ce fichier ne contient PAS de device. Il définit :
#    1. la sauvegarde persistante du joueur (gardée entre les parties) ;
#    2. les règles du pass (coût des paliers, titres, bonus) ;
#    3. les « armes signature » (nom + effet original + arme de base).
#  Le device principal est dans arene_prestige.verse.
#
#  ⚠️ RÈGLE D'OR DE LA SAUVEGARDE : une fois l'île PUBLIÉE, ne supprime et ne
#  renomme JAMAIS un champ de « sauvegarde_joueur ». Tu peux seulement en
#  AJOUTER (avec une valeur par défaut). Sinon les progressions des joueurs
#  peuvent être perdues.
# =============================================================================

using { /Fortnite.com/Devices }
using { /Verse.org/Simulation }

# Transforme un texte en « message » (obligatoire pour l'afficher dans l'interface).
Txt<localizes>(S:string):message = "{S}"

# Message spécial qui affiche le NOM du joueur (Verse ne donne pas le pseudo en texte).
AnnonceVictoire<localizes>(Gagnant:agent):message = ">>> {Gagnant} remporte la manche ! <<<"

# -----------------------------------------------------------------------------
# 1. SAUVEGARDE PERSISTANTE
# -----------------------------------------------------------------------------
sauvegarde_joueur := class<final><persistable>:
    Version : int = 1
    PassXP : int = 0                       # XP accumulée dans le pass actuel
    Prestige : int = 0                     # 0 à PrestigeMax
    EliminationsTotales : int = 0
    VictoiresTotales : int = 0
    MeilleureSerie : int = 0
    DernierJour : int = 0                  # jour (depuis 1970) de la dernière connexion
    JoursConsecutifs : int = 0
    DernierJourPremiereVictoire : int = 0

# Une entrée par joueur, conservée par Fortnite entre les parties.
var SauvegardesJoueurs : weak_map(player, sauvegarde_joueur) = map{}

# -----------------------------------------------------------------------------
# 2. RÈGLES DU PASS
# -----------------------------------------------------------------------------
PaliersMax : int = 30
PrestigeMax : int = 10

# Coût pour passer du palier N au palier N+1 : 100, 125, 150 ... 825 XP.
# Premier palier en ~3 min de jeu (récompense dès la 1re manche = meilleure rétention J1).
CoutPalier(Palier:int):int = 100 + 25 * Palier

infos_palier := struct:
    Palier : int = 0
    XPDansPalier : int = 0
    CoutProchain : int = 0

CalculerPalier(XPTotal:int):infos_palier =
    var Reste : int = XPTotal
    var Palier : int = 0
    loop:
        if (Palier >= PaliersMax):
            break
        Cout := CoutPalier(Palier)
        if (Reste < Cout):
            break
        set Reste = Reste - Cout
        set Palier = Palier + 1
    infos_palier{Palier := Palier, XPDansPalier := Reste, CoutProchain := CoutPalier(Palier)}

XPPassComplet():int =
    var Total : int = 0
    for (P := 0..PaliersMax - 1):
        set Total = Total + CoutPalier(P)
    Total

# Chaque prestige donne +5 % d'XP pour toujours (les prestiges suivants vont plus vite).
AppliquerBoostPrestige(Gain:int, Prestige:int):int =
    if (Bonus := Quotient[Gain * 5 * Prestige, 100]):
        Gain + Bonus
    else:
        Gain

# Titre affiché dans le HUD — un nouveau tous les 5 paliers.
TitrePourPalier(Palier:int):string =
    if (Palier >= 30):
        "Légende de l'Arène"
    else if (Palier >= 25):
        "Maître d'Armes"
    else if (Palier >= 20):
        "Prédateur"
    else if (Palier >= 15):
        "Vétéran"
    else if (Palier >= 10):
        "Duelliste"
    else if (Palier >= 5):
        "Combattant"
    else:
        "Recrue"

# Ce que le joueur gagne en atteignant un palier (affiché à l'écran).
RecompensePalier(Palier:int):string =
    if (Palier >= PaliersMax):
        "PASS TERMINÉ ! Va au bouton PRESTIGE."
    else if (Mod[Palier, 10] = 0):
        "Bouclier de départ amélioré !"
    else if (Mod[Palier, 5] = 0):
        "Nouveau titre : {TitrePourPalier(Palier)}"
    else:
        "Continue, le prochain titre approche."

# Bouclier donné à chaque apparition. Volontairement plafonné à 50 :
# un nouveau joueur doit toujours pouvoir gagner (sinon il quitte la map).
BouclierDeDepart(Palier:int, Prestige:int):float =
    var B : float = 0.0
    if (Palier >= 10):
        set B = 15.0
    if (Palier >= 20):
        set B = 30.0
    if (Palier >= 30):
        set B = 45.0
    if (Prestige > 0):
        for (I := 1..Prestige):
            set B = B + 5.0
        if (B < 25.0):
            set B = 25.0   # un joueur prestige ne repart jamais de zéro
    Min(B, 50.0)

Etoiles(N:int):string =
    var S : string = ""
    for (I := 1..N):
        set S = S + "*"
    S

# Numéro du jour réel (sert à la série de connexions et à la 1re victoire du jour).
# Si UEFN signale une erreur sur GetSecondsSinceEpoch, remplace le corps par « 0 » :
# les bonus quotidiens seront désactivés mais tout le reste fonctionnera.
JourActuel():int =
    if (J := Floor[GetSecondsSinceEpoch() / 86400.0]):
        J
    else:
        0

# -----------------------------------------------------------------------------
# 3. ARSENAL — LES ARMES SIGNATURE
# -----------------------------------------------------------------------------
# Chaque arme = une arme Fortnite de base (choisie dans l'Item Granter)
#             + un nom original + un EFFET SIGNATURE déclenché à chaque élimination.
effet_signature := enum:
    Aucun        # arme « pure »
    Vampire      # +30 PV à chaque élimination
    Surcharge    # +25 bouclier à chaque élimination
    Elan         # coup de vitesse à chaque élimination (Movement Modulator)
    Butin        # XP d'élimination doublée

arme_signature := class<concrete>:
    @editable Nom : string = "Arme"
    @editable Donneur : item_granter_device = item_granter_device{}
    @editable Effet : effet_signature = effet_signature.Aucun
