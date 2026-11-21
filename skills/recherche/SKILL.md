---
name: recherche
description: "Recherche web approfondie et sourcée, rangée dans le wiki du cerveau (dossier, affirmations classées), ou recherche avec Perplexity : brancher le serveur, outils payants à l'appel. Pas pour une question simple ni pour le SEO."
metadata:
  triggers: >-
    « recherche à fond » « recherche approfondie » « fais un dossier sur » « creuse le sujet » « enquête sur »
    « trouve tout sur » « recherche et range dans le wiki » « état des lieux de » « deep research » « autoresearch »
    « perplexity » « avec perplexity » « recherche perplexity » « cherche sur perplexity » « demande à perplexity »
    « recherche approfondie perplexity » « perplexity research » « branche perplexity » « installe perplexity » Ne pas
    utiliser pour la « visibilité dans perplexity », une boutique « visible dans perplexity », « cité par perplexity »,
    le « référencement perplexity » ou un « audit geo » (c'est du SEO : cerveau e-commerce).
---

# Recherche — l'aiguillage vers la bonne fiche

Dossier de cette skill : `${CLAUDE_SKILL_DIR}` (le « Base directory » donné au chargement). Lire **seulement** la fiche
du besoin, puis la suivre ; ses chemins (`references/`, `scripts/`) partent du dossier de la fiche. Chaque fiche garde
la source et la licence de son outil (fichier `LICENSE` à côté quand il y en a un).

| Besoin | Fiche | D'après |
|---|---|---|
| Recherche à fond et sourcée, dossier rangé dans le wiki : boucle bornée, sources primaires, position contraire, chaque affirmation classée | [recherche](recherche/fiche.md) | d'après autoresearch de claude-obsidian, AgriciDaniel, MIT |
| Perplexity nommé, ou recherche filtrée par sites, langue, pays ou date : brancher le serveur MCP officiel, se connecter, s'en servir (payant à l'appel) | [perplexity](perplexity/fiche.md) | serveur officiel de Perplexity |

Ailleurs : une question simple → la recherche web intégrée (WebSearch) ; la visibilité d'une boutique dans les
assistants IA (GEO) → `cerveau:ecommerce`.
