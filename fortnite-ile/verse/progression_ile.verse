# ============================================================================
# progression_ile.verse
# Progression SAUVEGARDÉE + HUD (niveau / pièces / objectif) + accueil
# des nouveaux joueurs + bonus de retour.
#
# Pourquoi : Discover pousse les îles où les joueurs RESTENT et REVIENNENT.
# Une progression sauvegardée est le levier n°1 de la rétention J1/J7.
#
# Mot "Points" utilisé volontairement à la place de "XP" : Epic interdit
# de confondre la progression de l'île avec l'XP Fortnite.
#
# Installation : voir fortnite-ile/README.md, section "Installer le code".
# ============================================================================

using { /Fortnite.com/Devices }
using { /Fortnite.com/UI }
using { /UnrealEngine.com/Temporary/UI }
using { /UnrealEngine.com/Temporary/SpatialMath }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /Verse.org/Simulation }
using { /Verse.org/Colors }

# ---------------------------------------------------------------------------
# Données sauvegardées entre les sessions (persistance Verse).
# ATTENTION : une fois l'île publiée, n'enlève JAMAIS un champ et ne change
# pas son type. Tu peux seulement en AJOUTER (avec une valeur par défaut).
# ---------------------------------------------------------------------------
donnees_joueur := class<final><persistable>:
    Version : int = 1
    Niveau : int = 1
    Points : int = 0       # progression vers le niveau suivant
    Pieces : int = 0       # monnaie GRATUITE de l'île (gagnée en jouant)
    Sessions : int = 0     # nombre de fois où le joueur est venu
    AccueilFini : logic = false
    VIP : logic = false    # mis à jour par boutique_vbucks.verse

# Variable sauvegardée par Fortnite pour chaque joueur.
var SauvegardeJoueurs : weak_map(player, donnees_joueur) = map{}

# Convertit un texte en "message" affichable à l'écran.
TexteEcran<localizes>(Texte : string) : message = "{Texte}"

# Un déclencheur qui donne des points quand il est activé
# (ex. : fin d'une manche, boss tué, checkpoint atteint).
source_points := class<concrete>:
    @editable
    Declencheur : trigger_device = trigger_device{}
    @editable
    Points : int = 25

# Petit objet qui relie un déclencheur à un montant de points
# (Verse n'a pas de fonctions anonymes, on passe par une classe).
relais_points := class:
    Progression : progression_ile
    Montant : int

    QuandDeclenche(MaybeAgent : ?agent) : void =
        if (Agent := MaybeAgent?, Joueur := player[Agent]):
            Progression.DonnerPoints(Joueur, Montant)

progression_ile := class(creative_device):

    # ---------------- Réglages modifiables dans UEFN ----------------
    # Ce que le joueur doit faire. Affiché en permanence sous le niveau.
    @editable
    ObjectifPrincipal : string = "Objectif : atteins le niveau 5 pour débloquer la zone secrète !"

    # Message d'accueil affiché à la toute première venue.
    @editable
    MessageBienvenue : string = "Bienvenue ! Joue pour gagner des points et monter de niveau."

    # Points nécessaires par niveau (niveau 1 -> 100, niveau 2 -> 200, ...).
    @editable
    PointsParNiveau : int = 100

    # Pièces gratuites données à chaque niveau gagné.
    @editable
    PiecesParNiveau : int = 50

    # Points donnés automatiquement toutes les X secondes de jeu actif.
    @editable
    PointsDePresence : int = 10
    @editable
    IntervallePresence : float = 60.0

    # Bonus de pièces quand un joueur revient (2e session et plus).
    @editable
    BonusDeRetour : int = 30

    # Multiplicateur de pièces pour les joueurs VIP (achat V-Bucks).
    @editable
    MultiplicateurVIP : int = 2

    # Déclencheurs qui donnent des points (fin de manche, kill, etc.).
    @editable
    SourcesDePoints : []source_points = array{}

    # Optionnel : Accolades device pour donner l'XP Fortnite officielle
    # quand le joueur monte de niveau (si ton île y est éligible).
    @editable
    Accolade : accolades_device = accolades_device{}

    # Optionnel : déclencheur activé à chaque montée de niveau
    # (relie-le à un son, des VFX, un feu d'artifice...).
    @editable
    EffetMonteeNiveau : trigger_device = trigger_device{}

    # ---------------- État en mémoire (pas sauvegardé) ----------------
    var TextesNiveau : [player]text_block = map{}
    var TextesObjectif : [player]text_block = map{}
    var TextesInfo : [player]text_block = map{}

    OnBegin<override>()<suspends> : void =
        for (Joueur : GetPlayspace().GetPlayers()):
            AjouterJoueur(Joueur)
        GetPlayspace().PlayerAddedEvent().Subscribe(AjouterJoueur)

        for (Source : SourcesDePoints):
            Relais := relais_points{Progression := Self, Montant := Source.Points}
            Source.Declencheur.TriggeredEvent().Subscribe(Relais.QuandDeclenche)

        # Points de présence : récompense régulière = le joueur voit qu'il avance.
        loop:
            Sleep(IntervallePresence)
            for (Joueur : GetPlayspace().GetPlayers()):
                DonnerPoints(Joueur, PointsDePresence)

    # ======================= API PUBLIQUE =======================
    # Utilisable depuis tes autres scripts Verse.

    LireDonnees(Joueur : player) : donnees_joueur =
        if (Donnees := SauvegardeJoueurs[Joueur]):
            Donnees
        else:
            donnees_joueur{}

    DonnerPoints(Joueur : player, Montant : int) : void =
        D := LireDonnees(Joueur)
        var Niveau : int = D.Niveau
        var Points : int = D.Points + Montant
        var Pieces : int = D.Pieces
        var NiveauxGagnes : int = 0

        loop:
            Requis := PointsRequis(Niveau)
            if (Points < Requis):
                break
            set Points -= Requis
            set Niveau += 1
            set Pieces += PiecesGagnees(D, PiecesParNiveau)
            set NiveauxGagnes += 1

        Sauver(Joueur, donnees_joueur:
            Version := D.Version
            Niveau := Niveau
            Points := Points
            Pieces := Pieces
            Sessions := D.Sessions
            AccueilFini := D.AccueilFini
            VIP := D.VIP)

        if (NiveauxGagnes > 0):
            Accolade.Award(Joueur)
            EffetMonteeNiveau.Trigger(Joueur)
            AfficherInfo(Joueur, "NIVEAU {Niveau} ! +{PiecesParNiveau} pièces")
        MettreAJourHUD(Joueur)

    AjouterPieces(Joueur : player, Montant : int) : void =
        D := LireDonnees(Joueur)
        Sauver(Joueur, CopieAvecPieces(D, D.Pieces + Montant))
        MettreAJourHUD(Joueur)

    # Renvoie true si le joueur avait assez de pièces (et les retire).
    DepenserPieces(Joueur : player, Montant : int) : logic =
        D := LireDonnees(Joueur)
        if (D.Pieces >= Montant):
            Sauver(Joueur, CopieAvecPieces(D, D.Pieces - Montant))
            MettreAJourHUD(Joueur)
            return true
        return false

    DefinirVIP(Joueur : player, EstVIP : logic) : void =
        D := LireDonnees(Joueur)
        Sauver(Joueur, donnees_joueur:
            Version := D.Version
            Niveau := D.Niveau
            Points := D.Points
            Pieces := D.Pieces
            Sessions := D.Sessions
            AccueilFini := D.AccueilFini
            VIP := EstVIP)
        MettreAJourHUD(Joueur)

    AfficherInfo(Joueur : player, Texte : string) : void =
        if (Info := TextesInfo[Joueur]):
            Info.SetText(TexteEcran(Texte))
            spawn{ EffacerInfoPlusTard(Info) }

    # ======================= INTERNE =======================

    PointsRequis(Niveau : int) : int = Niveau * PointsParNiveau

    PiecesGagnees(D : donnees_joueur, Base : int) : int =
        if (D.VIP?):
            Base * MultiplicateurVIP
        else:
            Base

    CopieAvecPieces(D : donnees_joueur, NouvellesPieces : int) : donnees_joueur =
        donnees_joueur:
            Version := D.Version
            Niveau := D.Niveau
            Points := D.Points
            Pieces := NouvellesPieces
            Sessions := D.Sessions
            AccueilFini := D.AccueilFini
            VIP := D.VIP

    Sauver(Joueur : player, D : donnees_joueur) : void =
        if (set SauvegardeJoueurs[Joueur] = D) {}

    AjouterJoueur(Joueur : player) : void =
        D := LireDonnees(Joueur)
        NouvelleSession := D.Sessions + 1
        PremiereVenue := if (D.AccueilFini?) then false else true

        var Pieces : int = D.Pieces
        if (not PremiereVenue?):
            set Pieces += BonusDeRetour

        Sauver(Joueur, donnees_joueur:
            Version := D.Version
            Niveau := D.Niveau
            Points := D.Points
            Pieces := Pieces
            Sessions := NouvelleSession
            AccueilFini := true
            VIP := D.VIP)

        CreerHUD(Joueur)
        MettreAJourHUD(Joueur)

        if (PremiereVenue?):
            AfficherInfo(Joueur, MessageBienvenue)
        else:
            AfficherInfo(Joueur, "Content de te revoir ! Bonus de retour : +{BonusDeRetour} pièces")

    CreerHUD(Joueur : player) : void =
        if (InterfaceJoueur := GetPlayerUI[Joueur]):
            TexteNiveau := text_block{DefaultTextColor := NamedColors.White}
            TexteObjectif := text_block{DefaultTextColor := NamedColors.Yellow}
            TexteInfo := text_block{DefaultTextColor := NamedColors.Cyan}

            Colonne := stack_box:
                Orientation := orientation.Vertical
                Slots := array:
                    stack_box_slot:
                        Widget := TexteNiveau
                        HorizontalAlignment := horizontal_alignment.Left
                    stack_box_slot:
                        Widget := TexteObjectif
                        HorizontalAlignment := horizontal_alignment.Left
                    stack_box_slot:
                        Widget := TexteInfo
                        HorizontalAlignment := horizontal_alignment.Left

            # Haut-gauche de l'écran, sous la mini-carte. Ajuste X/Y si ça
            # chevauche ton interface (0.0 = gauche/haut, 1.0 = droite/bas).
            Ecran := canvas:
                Slots := array:
                    canvas_slot:
                        Anchors := anchors{Minimum := vector2{X := 0.02, Y := 0.30}, Maximum := vector2{X := 0.02, Y := 0.30}}
                        Offsets := margin{Top := 0.0, Left := 0.0, Right := 0.0, Bottom := 0.0}
                        Alignment := vector2{X := 0.0, Y := 0.0}
                        SizeToContent := true
                        Widget := Colonne

            InterfaceJoueur.AddWidget(Ecran)
            if (set TextesNiveau[Joueur] = TexteNiveau) {}
            if (set TextesObjectif[Joueur] = TexteObjectif) {}
            if (set TextesInfo[Joueur] = TexteInfo) {}

    MettreAJourHUD(Joueur : player) : void =
        D := LireDonnees(Joueur)
        Requis := PointsRequis(D.Niveau)
        BadgeVIP := if (D.VIP?) then "  [VIP]" else ""
        if (TexteNiveau := TextesNiveau[Joueur]):
            TexteNiveau.SetText(TexteEcran("Niveau {D.Niveau}  |  {D.Points}/{Requis} points  |  {D.Pieces} pièces{BadgeVIP}"))
        if (TexteObjectif := TextesObjectif[Joueur]):
            TexteObjectif.SetText(TexteEcran(ObjectifPrincipal))

    EffacerInfoPlusTard(Info : text_block)<suspends> : void =
        Sleep(5.0)
        Info.SetText(TexteEcran(""))
