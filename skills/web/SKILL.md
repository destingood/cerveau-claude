---
name: web
description: "Quand il faut agir sur un site : piloter un navigateur (tests, captures, bugs, vitesse), extraire ses données en JSON, lire un réseau social ou faire un client de l'API cachée d'un site."
metadata:
  triggers: >-
    « agent-browser » « agent browser » « installe agent-browser » « cherche les bugs de mon site »
    « teste mon appli à fond » « vitesse de chargement de la page » « web vitals » « extrais les données de la page »
    « ouvre ce site et » « navigue sur le site » « playwright » « playwright-cli » « installe playwright »
    « teste mon site dans le navigateur » « teste le parcours » « teste mon formulaire » « capture d'écran de la page »
    « automatise le navigateur » « scrapegraph » « installe scrapegraph » « scrape ce site » « scrape cette page »
    « aspire les données de » « récupère tous les produits et les prix de » « liste les prix des concurrents »
    « extrais en JSON » « agent-reach » « agent reach » « installe agent-reach » « lis ce tweet » « lis ce fil reddit »
    « sous-titres de cette vidéo YouTube » « résume cette vidéo » « transcris cette vidéo » « reverse api »
    « reverse-api-engineer » « installe reverse api » « transforme ce site en API » « l'API cachée de ce site »
    « ce site n'a pas d'API » « fais-moi un client API pour ce site » « récupère les données de ce site par son API »
    « capture les requêtes du site » « rejoue l'API du site » Ne pas utiliser pour « l'API payante ScrapeGraph »
---

# Web — l'aiguillage vers la bonne fiche

Dossier de cette skill : `${CLAUDE_SKILL_DIR}` (le « Base directory » donné au chargement). Lire **seulement** la fiche
du besoin, puis la suivre ; ses chemins (`references/`, `scripts/`) partent du dossier de la fiche. Chaque fiche garde
la source et la licence de son outil (fichier `LICENSE` à côté quand il y en a un).

| Besoin | Fiche | D'après |
|---|---|---|
| Naviguer, cliquer, extraire une page, chercher les bugs d'une appli, web vitals, appli Electron, plusieurs sessions | [agent-browser](agent-browser/fiche.md) | agent-browser de Vercel Labs, Apache-2.0 |
| Tester un site, un parcours ou un formulaire, captures d'écran, générer des tests Playwright | [playwright](playwright/fiche.md) | playwright-cli de Microsoft, Apache-2.0 |
| Extraire en JSON les données d'une ou de plusieurs pages, ou d'une recherche web, avec un modèle local gratuit | [scrapegraph](scrapegraph/fiche.md) | Scrapegraph-ai de ScrapeGraphAI, MIT ; script `scrapegraph/scripts/sgai.py` |
| Lire en lecture seule X/Twitter, Reddit, sous-titres YouTube, LinkedIn… que la lecture web rate | [agent-reach](agent-reach/fiche.md) | Agent Reach de Panniantong, MIT |
| Faire d'un site sans API publique un client d'API typé (capture des vraies requêtes) | [reverse-api-engineer](reverse-api-engineer/fiche.md) | reverse-api-engineer de Kalil, MIT |

Ailleurs : lire une seule page → la lecture web intégrée ; une API publique gratuite → `cerveau:public-apis` ; une
recherche sourcée → `cerveau:recherche` ; décompiler une appli → `/cerveau:rea`.
