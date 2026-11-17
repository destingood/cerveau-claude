# ============================================================================
# boutique_vbucks.verse
# Vente d'objets en V-BUCKS (transactions dans l'île, API Marketplace d'Epic).
#
# Ce qu'on vend (simple, lisible, pas "pay-to-win" agressif) :
#   1. Sac de 1000 pièces      -> 100 V-Bucks  (consommable, achat d'entrée)
#   2. Pass VIP (pièces x2)     -> 400 V-Bucks  (permanent)
#   3. Pack de départ           -> 500 V-Bucks  (Pass VIP + 3 sacs : ~30 % d'économie)
#
# RÈGLES EPIC (vérifiées dans la doc officielle) :
#   - Prix entre 50 et 5000 V-Bucks, par multiples de 50.
#   - Nom <= 50 caractères, description <= 500, description courte <= 100.
#   - Ne JAMAIS utiliser le mot "XP" ni des termes de la boutique Fortnite.
#   - Si l'objet donne un avantage en jeu -> ConsequentialToGameplay = true.
#   - Déclare les achats intégrés dans le questionnaire IARC, sinon la
#     modération refuse l'île. (Pas prêt ? Mets ce fichier en commentaire.)
#   - La boutique ne s'ouvre QUE quand le joueur le choisit (bouton).
#
# AVANT DE COMPILER : importe 3 textures carrées (512x512 ou 1024x1024) à la
# racine du dossier Content de ton projet, nommées exactement :
#   T_IconePieces, T_IconeVIP, T_IconePack
# ============================================================================

using { /Fortnite.com/Devices }
using { /UnrealEngine.com/Marketplace }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /Verse.org/Assets }
using { /Verse.org/Simulation }

# --------------------------- Textes ---------------------------
InfoSacPieces<public> := module:
    Name<public><localizes> : message = "Sac de 1000 pièces"
    Description<public><localizes> : message = "Ajoute immédiatement 1000 pièces de l'île à ton compte. Les pièces servent uniquement dans cette île, pour acheter des objets dans la boutique."
    ShortDescription<public><localizes> : message = "+1000 pièces de l'île."

InfoPassVIP<public> := module:
    Name<public><localizes> : message = "Pass VIP"
    Description<public><localizes> : message = "Pour toujours dans cette île : tu gagnes 2 fois plus de pièces à chaque niveau et tu obtiens le badge VIP à côté de ton niveau."
    ShortDescription<public><localizes> : message = "Pièces x2 pour toujours + badge VIP."

InfoPackDepart<public> := module:
    Name<public><localizes> : message = "Pack de départ"
    Description<public><localizes> : message = "Le Pass VIP (pièces x2 pour toujours) + 3 sacs de 1000 pièces. Le meilleur moyen de bien démarrer dans l'île."
    ShortDescription<public><localizes> : message = "Pass VIP + 3000 pièces."

TitreBoutique<localizes> : message = "Boutique de l'île"

# --------------------------- Objets (entitlements) ---------------------------
# Classe de base commune à TOUS les objets vendus dans l'île.
entitlement_ile<public> := class<abstract><castable>(entitlement){}

sac_pieces<public> := class<concrete>(entitlement_ile):
    var Name<override> : message = InfoSacPieces.Name
    var Description<override> : message = InfoSacPieces.Description
    var ShortDescription<override> : message = InfoSacPieces.ShortDescription
    var Icon<override> : texture = T_IconePieces
    var Consumable<override> : logic = true
    var MaxCount<override> : int = 100
    # Les pièces font avancer plus vite -> avantage en jeu, on le déclare.
    var ConsequentialToGameplay<override> : logic = true

pass_vip<public> := class<concrete>(entitlement_ile):
    var Name<override> : message = InfoPassVIP.Name
    var Description<override> : message = InfoPassVIP.Description
    var ShortDescription<override> : message = InfoPassVIP.ShortDescription
    var Icon<override> : texture = T_IconeVIP
    var ConsequentialToGameplay<override> : logic = true

# --------------------------- Offres (prix) ---------------------------
offre_sac_pieces<public> := class(entitlement_offer):
    var Name<override> : message = InfoSacPieces.Name
    var Description<override> : message = InfoSacPieces.Description
    var ShortDescription<override> : message = InfoSacPieces.ShortDescription
    var Icon<override> : texture = T_IconePieces
    var EntitlementType<override> : concrete_subtype(entitlement) = sac_pieces
    var Price<override> : price_dimension = MakePriceVBucks(100.0)

offre_pass_vip<public> := class(entitlement_offer):
    var Name<override> : message = InfoPassVIP.Name
    var Description<override> : message = InfoPassVIP.Description
    var ShortDescription<override> : message = InfoPassVIP.ShortDescription
    var Icon<override> : texture = T_IconeVIP
    var EntitlementType<override> : concrete_subtype(entitlement) = pass_vip
    var Price<override> : price_dimension = MakePriceVBucks(400.0)

offre_pack_depart<public> := class(bundle_offer):
    var Name<override> : message = InfoPackDepart.Name
    var Description<override> : message = InfoPackDepart.Description
    var ShortDescription<override> : message = InfoPackDepart.ShortDescription
    var Icon<override> : texture = T_IconePack
    var Offers<override> : []tuple(offer, int) = array:
        (offre_pass_vip{}, 1)
        (offre_sac_pieces{}, 3)
    var Price<override> : price_dimension = MakePriceVBucks(500.0)

# --------------------------- Appareil boutique ---------------------------
boutique_vbucks := class(creative_device):

    # Glisse ici l'appareil progression_ile placé dans ton île.
    @editable
    Progression : progression_ile = progression_ile{}

    # Bouton(s) qui ouvrent la boutique (ex. : un PNJ ou un comptoir au spawn).
    @editable
    BoutonsBoutique : []button_device = array{}

    # Pièces données par sac acheté.
    @editable
    PiecesParSac : int = 1000

    OnBegin<override>()<suspends> : void =
        for (Bouton : BoutonsBoutique):
            Bouton.SetInteractionText(TexteEcran("Boutique de l'île"))
            Bouton.InteractedWithEvent().Subscribe(QuandBoutonPresse)
        for (Joueur : GetPlayspace().GetPlayers()):
            QuandJoueurArrive(Joueur)
        GetPlayspace().PlayerAddedEvent().Subscribe(QuandJoueurArrive)

    QuandBoutonPresse(Agent : agent) : void =
        if (Joueur := player[Agent]):
            spawn{ OuvrirBoutique(Joueur) }

    OuvrirBoutique(Joueur : player)<suspends> : void =
        Offres : []offer = array{offre_pack_depart{}, offre_pass_vip{}, offre_sac_pieces{}}
        ShowOffersDialog(Joueur, Offres, TitreBoutique)

    QuandJoueurArrive(Joueur : player) : void =
        spawn{ SuivreAchats(Joueur) }

    # Vérifie les achats à l'arrivée (achats passés, remboursements), puis
    # à CHAQUE changement signalé par Epic. Epic recommande de passer par
    # l'événement de changement plutôt que par le résultat de l'achat.
    SuivreAchats(Joueur : player)<suspends> : void =
        Synchroniser(Joueur)
        loop:
            GetEntitlementsChangedEvent(Joueur, entitlement_ile).Await()
            if (not Joueur.IsActive[]):
                break
            Synchroniser(Joueur)

    Synchroniser(Joueur : player)<suspends> : void =
        # 1) Pass VIP : actif tant que le joueur le possède (gère les remboursements).
        AchatsVIP := GetPurchasedEntitlements(Joueur, pass_vip)
        var NombreVIP : int = 0
        if (Ligne := AchatsVIP[0]):
            set NombreVIP = Ligne(1)
        Progression.DefinirVIP(Joueur, if (NombreVIP > 0) then true else false)

        # 2) Sacs de pièces : on "consomme" les sacs achetés et on crédite les pièces.
        AchatsSacs := GetPurchasedEntitlements(Joueur, sac_pieces)
        var NombreSacs : int = 0
        if (Ligne := AchatsSacs[0]):
            set NombreSacs = Ligne(1)
        if (NombreSacs > 0):
            Consomme := ConsumeEntitlement(Joueur, sac_pieces, ?Count := NombreSacs)
            if (Consomme?):
                Progression.AjouterPieces(Joueur, NombreSacs * PiecesParSac)
                Progression.AfficherInfo(Joueur, "Merci ! +{NombreSacs * PiecesParSac} pièces")
            else:
                Print("boutique_vbucks : échec ConsumeEntitlement sac_pieces x{NombreSacs}")
