# =============================================================================
#  ARÈNE PRESTIGE — Device principal (Gun Game FFA sans construction)
# -----------------------------------------------------------------------------
#  Boucle de jeu :
#   • Chaque élimination te fait passer à l'arme suivante de l'arsenal.
#   • Le premier qui fait une élimination avec la DERNIÈRE arme gagne la manche.
#   • Si personne n'a fini au bout du temps limite, le plus avancé gagne.
#   • Pause de quelques secondes, puis nouvelle manche SANS retour au lobby
#     (les joueurs restent dans la map = plus de temps de jeu par session).
#
#  Progression (sauvegardée entre les parties) :
#   • XP pour éliminations, séries, prime sur le leader, victoire, participation.
#   • Bonus : 1re victoire du jour, connexion quotidienne (jusqu'à 7 jours),
#     « bon retour » après 3 jours d'absence.
#   • Pass de 30 paliers → titres + bouclier de départ.
#   • Prestige (bouton dans la map) jusqu'à 10 : remet le pass à zéro,
#     donne une étoile, +5 % d'XP et un bouclier minimum.
# =============================================================================

using { /Fortnite.com/Devices }
using { /Fortnite.com/Characters }
using { /Fortnite.com/UI }
using { /Verse.org/Simulation }
using { /Verse.org/Colors }
using { /UnrealEngine.com/Temporary/UI }
using { /UnrealEngine.com/Temporary/SpatialMath }

# État d'un joueur pendant la session (copie de sa sauvegarde + infos de manche).
etat_joueur := class:
    # --- sauvegardé ---
    var PassXP : int = 0
    var Prestige : int = 0
    var EliminationsTotales : int = 0
    var VictoiresTotales : int = 0
    var MeilleureSerie : int = 0
    var DernierJour : int = 0
    var JoursConsecutifs : int = 0
    var DernierJourPremiereVictoire : int = 0
    # --- manche en cours (non sauvegardé) ---
    var NiveauArme : int = 0
    var Serie : int = 0
    var ElimsManche : int = 0
    # --- interface ---
    var TexteInfo : ?text_block = false
    var TexteNotif : ?text_block = false
    var NotifId : int = 0

arene_prestige_device := class(creative_device):

    # ---------------- RÉGLAGES MODIFIABLES DANS UEFN ----------------
    # Relie chaque « Donneur » à un Item Granter dans le panneau Détails.
    @editable Arsenal : []arme_signature = array{
        arme_signature{Nom := "Étincelle", Effet := effet_signature.Aucun},
        arme_signature{Nom := "Croc de Givre", Effet := effet_signature.Elan},
        arme_signature{Nom := "Rafale Solaire", Effet := effet_signature.Surcharge},
        arme_signature{Nom := "Marteau d'Orage", Effet := effet_signature.Vampire},
        arme_signature{Nom := "Écho", Effet := effet_signature.Butin},
        arme_signature{Nom := "Nova", Effet := effet_signature.Surcharge},
        arme_signature{Nom := "Faucheuse", Effet := effet_signature.Vampire},
        arme_signature{Nom := "Aiguille", Effet := effet_signature.Butin},
        arme_signature{Nom := "Tempête", Effet := effet_signature.Elan},
        arme_signature{Nom := "Dernier Mot", Effet := effet_signature.Aucun}}

    @editable PointsApparition : []player_spawner_device = array{}
    @editable ModulateurVitesse : movement_modulator_device = movement_modulator_device{}
    @editable BoutonPrestige : button_device = button_device{}
    @editable DureeMancheSecondes : float = 420.0
    @editable PauseEntreManchesSecondes : float = 8.0

    # ---------------- ÉCONOMIE D'XP (testée avec outils/simulateur_progression.py) ----------------
    XPElimination : int = 25
    XPVictoire : int = 150
    XPParticipation : int = 40          # seulement si au moins 1 élimination (anti-AFK)
    XPPrimeLeader : int = 50
    XPPremiereVictoireDuJour : int = 300
    XPBonRetour : int = 200

    # ---------------- ÉTAT INTERNE ----------------
    var Etats : [player]etat_joueur = map{}
    var MancheEnCours : logic = false
    var Gagnant : ?player = false
    FinManche : event() = event(){}

    OnBegin<override>()<suspends>:void =
        for (Joueur : GetPlayspace().GetPlayers()):
            SurArriveeJoueur(Joueur)
        GetPlayspace().PlayerAddedEvent().Subscribe(SurArriveeJoueur)
        for (Point : PointsApparition):
            Point.SpawnedEvent.Subscribe(SurApparition)
        BoutonPrestige.InteractedWithEvent.Subscribe(SurBoutonPrestige)

        loop:
            DemarrerManche()
            race:
                Sleep(DureeMancheSecondes)
                FinManche.Await()
            TerminerManche()
            Sleep(PauseEntreManchesSecondes)

    # =====================================================================
    #  ARRIVÉE D'UN JOUEUR
    # =====================================================================
    SurArriveeJoueur(Joueur:player):void =
        Etat := ChargerEtat(Joueur)
        if (set Etats[Joueur] = Etat) {}
        spawn{ PreparerJoueur(Joueur, Etat) }

    # Attend que le personnage existe, puis branche l'interface et les éliminations.
    PreparerJoueur(Joueur:player, Etat:etat_joueur)<suspends>:void =
        var Essais : int = 0
        loop:
            if (Perso := Joueur.GetFortCharacter[]):
                Perso.EliminatedEvent().Subscribe(SurElimination)
                CreerInterface(Joueur, Etat)
                AppliquerConnexionDuJour(Joueur, Etat)
                MettreAJourInterface(Etat)
                break
            set Essais = Essais + 1
            if (Essais > 120):
                break                    # le joueur est parti avant d'apparaître
            Sleep(0.5)

    # =====================================================================
    #  MANCHES
    # =====================================================================
    DemarrerManche():void =
        set Gagnant = false
        for (Joueur : GetPlayspace().GetPlayers(), Etat := Etats[Joueur]):
            set Etat.NiveauArme = 0
            set Etat.ElimsManche = 0
            set Etat.Serie = 0
            DonnerArmeActuelle(Joueur, Etat)
            Notifier(Etat, "NOUVELLE MANCHE ! Le premier à finir les {Arsenal.Length} armes gagne.")
            MettreAJourInterface(Etat)
        set MancheEnCours = true

    TerminerManche()<suspends>:void =
        set MancheEnCours = false
        var Vainqueur : ?player = Gagnant
        if (not Vainqueur?):
            set Vainqueur = MeilleurJoueur()

        # 1) Annonce du vainqueur à tout le monde
        if (V := Vainqueur?):
            for (Joueur : GetPlayspace().GetPlayers(), Etat := Etats[Joueur]):
                NotifierMessage(Etat, AnnonceVictoire(V))
        Sleep(3.0)

        # 2) Récompenses
        Jour := JourActuel()
        for (Joueur : GetPlayspace().GetPlayers(), Etat := Etats[Joueur]):
            if (V := Vainqueur?, V = Joueur):
                set Etat.VictoiresTotales = Etat.VictoiresTotales + 1
                var Gain : int = XPVictoire
                var Raison : string = "VICTOIRE !"
                if (Jour > 0, Etat.DernierJourPremiereVictoire < Jour):
                    set Etat.DernierJourPremiereVictoire = Jour
                    set Gain = Gain + XPPremiereVictoireDuJour
                    set Raison = "1re VICTOIRE DU JOUR ! Bonus x3"
                AjouterXP(Joueur, Etat, AppliquerBoostPrestige(Gain, Etat.Prestige), Raison)
            else if (Etat.ElimsManche > 0):
                AjouterXP(Joueur, Etat, AppliquerBoostPrestige(XPParticipation, Etat.Prestige), "Manche terminée")
            else:
                Notifier(Etat, "Fais au moins 1 élimination pour gagner l'XP de manche.")

    # Utilisé si le temps est écoulé : arme la plus avancée, puis plus d'éliminations.
    MeilleurJoueur():?player =
        var Meilleur : ?player = false
        var MeilleurNiveau : int = -1
        var MeilleursElims : int = -1
        for (Joueur : GetPlayspace().GetPlayers(), Etat := Etats[Joueur]):
            if (Etat.NiveauArme > MeilleurNiveau or (Etat.NiveauArme = MeilleurNiveau and Etat.ElimsManche > MeilleursElims)):
                set Meilleur = option{Joueur}
                set MeilleurNiveau = Etat.NiveauArme
                set MeilleursElims = Etat.ElimsManche
        if (MeilleursElims > 0):
            Meilleur
        else:
            false                        # personne n'a rien fait : pas de vainqueur

    NiveauMaxActuel():int =
        var Max : int = 0
        for (Joueur : GetPlayspace().GetPlayers(), Etat := Etats[Joueur]):
            if (Etat.NiveauArme > Max):
                set Max = Etat.NiveauArme
        Max

    # =====================================================================
    #  ÉLIMINATIONS
    # =====================================================================
    SurElimination(Resultat:elimination_result):void =
        Victime := Resultat.EliminatedCharacter
        NiveauMax := NiveauMaxActuel()

        # La victime perd sa série.
        var VictimeEtaitLeader : logic = false
        if (AgentVictime := Victime.GetAgent[], JoueurVictime := player[AgentVictime], EtatVictime := Etats[JoueurVictime]):
            if (EtatVictime.NiveauArme >= 3, EtatVictime.NiveauArme >= NiveauMax):
                set VictimeEtaitLeader = true
            set EtatVictime.Serie = 0
            MettreAJourInterface(EtatVictime)

        if:
            MancheEnCours?
            PersoTueur := Resultat.EliminatingCharacter?
            AgentTueur := PersoTueur.GetAgent[]
            JoueurTueur := player[AgentTueur]
            AgentVictime := Victime.GetAgent[]
            AgentTueur <> AgentVictime
            EtatTueur := Etats[JoueurTueur]
        then:
            CompterElimination(JoueurTueur, PersoTueur, EtatTueur, VictimeEtaitLeader)

    CompterElimination(Joueur:player, Perso:fort_character, Etat:etat_joueur, PrimeLeader:logic):void =
        set Etat.Serie = Etat.Serie + 1
        set Etat.ElimsManche = Etat.ElimsManche + 1
        set Etat.EliminationsTotales = Etat.EliminationsTotales + 1
        if (Etat.Serie > Etat.MeilleureSerie):
            set Etat.MeilleureSerie = Etat.Serie

        var Gain : int = XPElimination
        var Raison : string = "Élimination"

        # --- Effet signature de l'arme utilisée ---
        if (Arme := Arsenal[Etat.NiveauArme]):
            if (Arme.Effet = effet_signature.Vampire):
                Perso.Heal(30.0)
                set Raison = "{Arme.Nom} : +30 PV"
            else if (Arme.Effet = effet_signature.Surcharge):
                Perso.SetShield(Perso.GetShield() + 25.0)
                set Raison = "{Arme.Nom} : +25 bouclier"
            else if (Arme.Effet = effet_signature.Elan):
                ModulateurVitesse.Activate(Joueur)
                set Raison = "{Arme.Nom} : ÉLAN !"
            else if (Arme.Effet = effet_signature.Butin):
                set Gain = Gain * 2
                set Raison = "{Arme.Nom} : XP x2"

        # --- Séries ---
        if (Etat.Serie = 3):
            set Gain = Gain + 25
            set Raison = "SÉRIE x3 !"
        else if (Etat.Serie = 5):
            set Gain = Gain + 50
            set Raison = "SÉRIE x5 — IMPARABLE !"
        else if (Etat.Serie = 10):
            set Gain = Gain + 100
            set Raison = "SÉRIE x10 — LÉGENDAIRE !"

        # --- Prime sur le leader (aide ceux qui sont derrière à revenir) ---
        if (PrimeLeader?):
            set Gain = Gain + XPPrimeLeader
            set Raison = "LEADER ABATTU ! Prime"

        AjouterXP(Joueur, Etat, AppliquerBoostPrestige(Gain, Etat.Prestige), Raison)

        # --- Arme suivante ou victoire ---
        set Etat.NiveauArme = Etat.NiveauArme + 1
        if (Etat.NiveauArme >= Arsenal.Length):
            if (MancheEnCours?):
                set MancheEnCours = false
                set Gagnant = option{Joueur}
                FinManche.Signal()
        else:
            DonnerArmeActuelle(Joueur, Etat)
        MettreAJourInterface(Etat)

    # =====================================================================
    #  APPARITION / ARMES
    # =====================================================================
    SurApparition(Agent:agent):void =
        if (Joueur := player[Agent], Etat := Etats[Joueur]):
            set Etat.Serie = 0
            DonnerArmeActuelle(Joueur, Etat)
            if (Perso := Joueur.GetFortCharacter[]):
                P := CalculerPalier(Etat.PassXP)
                Bouclier := BouclierDeDepart(P.Palier, Etat.Prestige)
                if (Bouclier > 0.0):
                    Perso.SetShield(Bouclier)
            MettreAJourInterface(Etat)

    DonnerArmeActuelle(Joueur:player, Etat:etat_joueur):void =
        if (Arme := Arsenal[Etat.NiveauArme]):
            Arme.Donneur.GrantItem(Joueur)

    NomArmeActuelle(Etat:etat_joueur):string =
        if (Arme := Arsenal[Etat.NiveauArme]):
            Arme.Nom
        else:
            "—"

    # =====================================================================
    #  XP, PASS, PRESTIGE
    # =====================================================================
    AjouterXP(Joueur:player, Etat:etat_joueur, Gain:int, Raison:string):void =
        Avant := CalculerPalier(Etat.PassXP)
        if (Avant.Palier >= PaliersMax):
            if (Etat.Prestige < PrestigeMax):
                Notifier(Etat, "PASS TERMINÉ ! Va au bouton PRESTIGE pour ton étoile.")
        else:
            set Etat.PassXP = Min(Etat.PassXP + Gain, XPPassComplet())
            Apres := CalculerPalier(Etat.PassXP)
            if (Apres.Palier > Avant.Palier):
                Notifier(Etat, "PALIER {Apres.Palier} DÉBLOQUÉ ! {RecompensePalier(Apres.Palier)}")
            else if (Raison.Length > 0):
                Notifier(Etat, "{Raison}  +{Gain} XP")
        Sauvegarder(Joueur, Etat)
        MettreAJourInterface(Etat)

    SurBoutonPrestige(Agent:agent):void =
        if (Joueur := player[Agent], Etat := Etats[Joueur]):
            P := CalculerPalier(Etat.PassXP)
            if (Etat.Prestige >= PrestigeMax):
                Notifier(Etat, "Prestige maximum atteint. Respect.")
            else if (P.Palier < PaliersMax):
                Notifier(Etat, "Atteins le palier {PaliersMax} pour passer Prestige ({P.Palier}/{PaliersMax}).")
            else:
                set Etat.Prestige = Etat.Prestige + 1
                set Etat.PassXP = 0
                Notifier(Etat, "PRESTIGE {Etat.Prestige} ! +5 % d'XP pour toujours et bouclier bonus.")
                Sauvegarder(Joueur, Etat)
                MettreAJourInterface(Etat)

    # Série de connexions quotidiennes + bonus de retour (rétention J1 / J7).
    AppliquerConnexionDuJour(Joueur:player, Etat:etat_joueur):void =
        Jour := JourActuel()
        if (Jour > 0, Jour > Etat.DernierJour):
            Absence := Jour - Etat.DernierJour
            if (Etat.DernierJour > 0, Absence = 1):
                set Etat.JoursConsecutifs = Etat.JoursConsecutifs + 1
            else:
                set Etat.JoursConsecutifs = 1
            JoursBonus := Min(Etat.JoursConsecutifs, 7)
            var Gain : int = 50 * JoursBonus
            var Raison : string = "Connexion jour {JoursBonus}/7"
            if (Etat.DernierJour > 0, Absence >= 3):
                set Gain = Gain + XPBonRetour
                set Raison = "BON RETOUR ! Bonus"
            set Etat.DernierJour = Jour
            AjouterXP(Joueur, Etat, Gain, Raison)

    # =====================================================================
    #  SAUVEGARDE
    # =====================================================================
    ChargerEtat(Joueur:player):etat_joueur =
        Etat := etat_joueur{}
        if (S := SauvegardesJoueurs[Joueur]):
            set Etat.PassXP = S.PassXP
            set Etat.Prestige = S.Prestige
            set Etat.EliminationsTotales = S.EliminationsTotales
            set Etat.VictoiresTotales = S.VictoiresTotales
            set Etat.MeilleureSerie = S.MeilleureSerie
            set Etat.DernierJour = S.DernierJour
            set Etat.JoursConsecutifs = S.JoursConsecutifs
            set Etat.DernierJourPremiereVictoire = S.DernierJourPremiereVictoire
        Etat

    Sauvegarder(Joueur:player, Etat:etat_joueur):void =
        Nouvelle := sauvegarde_joueur:
            Version := 1
            PassXP := Etat.PassXP
            Prestige := Etat.Prestige
            EliminationsTotales := Etat.EliminationsTotales
            VictoiresTotales := Etat.VictoiresTotales
            MeilleureSerie := Etat.MeilleureSerie
            DernierJour := Etat.DernierJour
            JoursConsecutifs := Etat.JoursConsecutifs
            DernierJourPremiereVictoire := Etat.DernierJourPremiereVictoire
        if (set SauvegardesJoueurs[Joueur] = Nouvelle) {}

    # =====================================================================
    #  INTERFACE (HUD à gauche de l'écran)
    # =====================================================================
    CreerInterface(Joueur:player, Etat:etat_joueur):void =
        if (Etat.TexteInfo?):
            return                       # déjà créée
        if (UI := GetPlayerUI[Joueur]):
            Info := text_block{DefaultTextColor := NamedColors.White}
            Notif := text_block{DefaultTextColor := NamedColors.Yellow}
            Pile := stack_box:
                Orientation := orientation.Vertical
                Slots := array:
                    stack_box_slot:
                        Widget := Info
                        HorizontalAlignment := horizontal_alignment.Left
                    stack_box_slot:
                        Widget := Notif
                        HorizontalAlignment := horizontal_alignment.Left
            Cadre := canvas:
                Slots := array:
                    canvas_slot:
                        Anchors := anchors{Minimum := vector2{X := 0.02, Y := 0.30}, Maximum := vector2{X := 0.02, Y := 0.30}}
                        SizeToContent := true
                        Widget := Pile
            UI.AddWidget(Cadre)
            set Etat.TexteInfo = option{Info}
            set Etat.TexteNotif = option{Notif}

    MettreAJourInterface(Etat:etat_joueur):void =
        if (Info := Etat.TexteInfo?):
            P := CalculerPalier(Etat.PassXP)
            LignePrestige := if (Etat.Prestige > 0) then "{Etoiles(Etat.Prestige)} PRESTIGE {Etat.Prestige}" else "Sans prestige"
            LignePass := if (P.Palier >= PaliersMax) then "PASS COMPLET — bouton PRESTIGE !" else "PASS  Palier {P.Palier}/{PaliersMax}   {P.XPDansPalier}/{P.CoutProchain} XP"
            Info.SetText(Txt("{LignePrestige}  |  {TitrePourPalier(P.Palier)}\n{LignePass}\nARME {Etat.NiveauArme + 1}/{Arsenal.Length} : {NomArmeActuelle(Etat)}\nSérie : {Etat.Serie}   Record : {Etat.MeilleureSerie}"))

    Notifier(Etat:etat_joueur, Texte:string):void =
        NotifierMessage(Etat, Txt(Texte))

    NotifierMessage(Etat:etat_joueur, Msg:message):void =
        if (Notif := Etat.TexteNotif?):
            Notif.SetText(Msg)
            set Etat.NotifId = Etat.NotifId + 1
            spawn{ EffacerNotif(Etat, Etat.NotifId) }

    EffacerNotif(Etat:etat_joueur, Id:int)<suspends>:void =
        Sleep(4.0)
        if (Etat.NotifId = Id, Notif := Etat.TexteNotif?):
            Notif.SetText(Txt(""))
