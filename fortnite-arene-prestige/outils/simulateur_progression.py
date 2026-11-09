"""Simulateur de rythme du pass « Arène Prestige ».

Reproduit EXACTEMENT les règles du code Verse (verse/arene_donnees.verse et verse/arene_prestige.verse)
pour répondre à une question simple : combien de temps faut-il à un joueur pour atteindre chaque palier ?

Lancement : python3 outils/simulateur_progression.py
Modifie les hypothèses en haut du fichier pour tester un autre rythme.
"""

# --- Règles (identiques au Verse) -------------------------------------------
PALIERS_MAX = 30
PRESTIGE_MAX = 10
XP_ELIMINATION = 25
XP_VICTOIRE = 150
XP_PARTICIPATION = 40
XP_PREMIERE_VICTOIRE_JOUR = 300
NB_ARMES = 10


def cout_palier(palier: int) -> int:
    return 100 + 25 * palier


def boost_prestige(gain: int, prestige: int) -> int:
    return gain + (gain * 5 * prestige) // 100


def bonus_streak(serie: int) -> int:
    return {3: 25, 5: 50, 10: 100}.get(serie, 0)


# --- Hypothèses sur un joueur « moyen » (à ajuster avec tes vraies stats) ----
JOUEURS_PAR_PARTIE = 10
DUREE_MANCHE_MIN = 6.5          # une manche se termine en général avant la limite de 7 min
PAUSE_MIN = 8 / 60
ELIMS_PAR_MANCHE = 4            # joueur moyen dans un lobby de 10
TAUX_VICTOIRE = 1 / JOUEURS_PAR_PARTIE
MANCHES_PAR_SESSION = 4         # ~30 min de jeu
BONUS_CONNEXION_MOYEN = 150     # entre 50 (jour 1) et 350 (jour 7+)


def xp_par_manche(prestige: int) -> float:
    # éliminations (série de 3 atteinte environ une manche sur trois -> +25/3)
    elims = ELIMS_PAR_MANCHE * XP_ELIMINATION + 25 / 3
    fin = TAUX_VICTOIRE * XP_VICTOIRE + (1 - TAUX_VICTOIRE) * XP_PARTICIPATION
    return boost_prestige(int(elims + fin), prestige)


def main() -> None:
    total_pass = sum(cout_palier(p) for p in range(PALIERS_MAX))
    print(f"XP pour finir le pass : {total_pass}")
    print(f"Coût palier 1 : {cout_palier(0)} XP   |   coût palier 30 : {cout_palier(29)} XP\n")

    for prestige in (0, 5, 9):
        xpm = xp_par_manche(prestige)
        # par session : manches + bonus connexion + 1re victoire du jour une fois sur ~2 sessions
        xp_session = xpm * MANCHES_PAR_SESSION + BONUS_CONNEXION_MOYEN + XP_PREMIERE_VICTOIRE_JOUR * 0.25
        minutes_par_xp = (MANCHES_PAR_SESSION * (DUREE_MANCHE_MIN + PAUSE_MIN)) / xp_session
        print(f"--- Prestige {prestige} : ~{xpm:.0f} XP/manche, ~{xp_session:.0f} XP/session de 30 min")
        cumul = 0
        for palier in (1, 2, 3, 5, 10, 20, 30):
            cumul = sum(cout_palier(p) for p in range(palier))
            minutes = cumul * minutes_par_xp
            print(f"  palier {palier:>2} : {cumul:>6} XP  ≈ {minutes/60:5.1f} h de jeu ({minutes:5.0f} min)")
        print()

    # temps total jusqu'au prestige max
    heures = 0.0
    for prestige in range(PRESTIGE_MAX):
        xpm = xp_par_manche(prestige)
        xp_session = xpm * MANCHES_PAR_SESSION + BONUS_CONNEXION_MOYEN + XP_PREMIERE_VICTOIRE_JOUR * 0.25
        heures += total_pass / xp_session * 0.5
    print(f"Temps estimé pour atteindre Prestige {PRESTIGE_MAX} : ~{heures:.0f} h de jeu")


if __name__ == "__main__":
    main()
