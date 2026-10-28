# ADR-006 — Plugin `web_research` : Brave Search et lecteur web gardé

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
Le pack Généraliste doit sourcer ses réponses (critère « 100 % des réponses factuelles sourcées »).
Il faut chercher et lire des pages sans ouvrir de faille : R5 (contenu externe = données), R15
(CGU, `robots.txt`), SSRF (une page ou une question ne doit pas faire lire `localhost`, un réseau
privé ou les métadonnées cloud). Faits vérifiés le 2026-10-18 :
- Brave Search API : 5 $ / 1 000 requêtes, 5 $ de crédit gratuit par mois (la page d'accueil
  annonce aussi « jusqu'à 20 $ », non réconcilié), stockage des résultats seulement avec un plan
  qui l'autorise (brave.com/search/api) ;
- recherche web Anthropic : outil côté serveur, 10 $ / 1 000 recherches + tokens ; le modèle qui
  l'appelle voit les résultats bruts, ce qui contredit la séparation lecteur / acteur (ADR-008) ;
- SearXNG : agrège des moteurs dont les CGU interdisent souvent l'interrogation automatisée.

## Options
1. **Brave Search API derrière une interface fournisseur** : prix bas, résultats structurés.
2. **Recherche web Anthropic** : intégrée, mais deux fois plus chère et brute pour le planificateur.
3. **SearXNG auto-hébergé** : gratuit, mais risque CGU (R15) et maintenance.

## Décision
Option 1 (décision D1). Un serveur MCP stdio (SDK officiel `mcp` 2.3.0), classe `LECTURE`, deux
outils :
- `web_search(query, max_results ≤ 10)` via une interface `SearchProvider` (Brave en phase 1).
  Les résultats ne sont pas stockés au-delà de la requête ; les tests utilisent des résultats
  synthétiques.
- `web_read(url)` : httpx + trafilatura ; délai 15 s ; 2 Mo au plus (lecture en flux, coupure au
  dépassement) ; 5 redirections au plus, suivies à la main ; types `text/html` et `text/plain`
  seulement ; schémas `http` / `https` seulement ; `robots.txt` respecté (refus si interdit),
  gardé une heure par origine quand le site a répondu (phase 2, B22) ; extraction comprise dans
  le délai (phase 2, B72).
- Anti-SSRF : le nom est résolu, **toutes** les adresses doivent être publiques (refus de
  boucle locale, privé, lien local dont 169.254.x, multicast, réservé, IPv4 mappé en IPv6), puis la
  connexion se fait sur l'adresse validée (épinglage) avec le nom d'hôte gardé pour le SNI et le
  certificat. Le contrôle est refait à chaque redirection. Cela ferme la fenêtre de rebinding DNS.
  Ports 80 et 443 seulement (phase 2, B24). Les messages d'erreur ne montrent ni l'hôte ni
  l'adresse résolue (B67), et une valeur contrôlée par la page n'y paraît qu'en jeton court (B66).
- Provenance : `web_read` n'accepte qu'une URL issue des résultats de recherche de la requête ou
  de la question de Lucas (contrôle fait côté orchestrateur, qui détient la liste). Un résultat
  dont l'adresse a une formulation d'instruction est montré sans elle et ne peut pas être lu
  (phase 2, B68).

## Conséquences
- Plus simple : le fournisseur se remplace sans toucher au graphe.
- Plus difficile : une clé `BRAVE_SEARCH_API_KEY` à poser par Lucas ; les pages rendues en
  JavaScript ne sont pas lues (backlog : outil web fetch d'Anthropic ou navigateur headless).
- Les proxys HTTP de l'environnement sont ignorés (`trust_env=False`) pour que l'épinglage tienne.
- Réversible : oui.
