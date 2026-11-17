# ============================================================================
# boutique_pieces.verse
# Boutique avec la monnaie GRATUITE de l'île (pièces gagnées en jouant).
#
# Pourquoi : les pièces donnent un BUT au joueur (« encore 40 pièces pour
# l'arme dorée ») -> il joue plus longtemps et revient. C'est aussi la
# vitrine qui donne envie d'acheter le pack en V-Bucks (boutique_vbucks).
#
# Chaque article = 1 Bouton (button_device) + 1 Donneur d'objet
# (item_granter_device) placés dans ton île.
# ============================================================================

using { /Fortnite.com/Devices }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /Verse.org/Simulation }

article_boutique := class<concrete>:
    @editable
    Nom : string = "Arme dorée"
    @editable
    Prix : int = 100
    # Le bouton sur lequel le joueur interagit pour acheter.
    @editable
    Bouton : button_device = button_device{}
    # Le Donneur d'objet qui donne l'objet acheté.
    @editable
    Donneur : item_granter_device = item_granter_device{}
    # Niveau minimum pour acheter (0 = aucun). Crée de l'envie de progresser.
    @editable
    NiveauMinimum : int = 0

acheteur := class:
    Article : article_boutique
    Progression : progression_ile

    Acheter(Agent : agent) : void =
        if (Joueur := player[Agent]):
            D := Progression.LireDonnees(Joueur)
            if (D.Niveau < Article.NiveauMinimum):
                Progression.AfficherInfo(Joueur, "{Article.Nom} : niveau {Article.NiveauMinimum} requis")
            else if (Progression.DepenserPieces(Joueur, Article.Prix)?):
                Article.Donneur.GrantItem(Joueur)
                Progression.AfficherInfo(Joueur, "Acheté : {Article.Nom} !")
            else:
                Manque := Article.Prix - D.Pieces
                Progression.AfficherInfo(Joueur, "Il te manque {Manque} pièces pour {Article.Nom}")

boutique_pieces := class(creative_device):

    # Glisse ici l'appareil progression_ile placé dans ton île.
    @editable
    Progression : progression_ile = progression_ile{}

    @editable
    Articles : []article_boutique = array{}

    OnBegin<override>()<suspends> : void =
        for (Article : Articles):
            Article.Bouton.SetInteractionText(TexteEcran("Acheter {Article.Nom} : {Article.Prix} pièces"))
            Gestion := acheteur{Article := Article, Progression := Progression}
            Article.Bouton.InteractedWithEvent().Subscribe(Gestion.Acheter)
