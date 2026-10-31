# ADR-058 — Liste fermée de sites pour la lecture web d'un domaine

- Statut : **proposé** (à valider par l'utilisateur au compte rendu de P5)
- Date : 2026-10-27
- Phase : 6 (P5, décision H6)

## Contexte
Le pack Juridique FR (P5) doit répondre depuis des sources officielles ou institutionnelles
identifiées (Légifrance, Service Public, BOFiP, CNIL, Conseil d'État…), chacune avec sa licence
vérifiée (R14, H5). Le plugin `web_research` lit aujourd'hui toute page publique : une page
trouvée par la recherche, ou une redirection, peut mener à un blog, un forum ou un site piégé
(R5, R12). Une consigne dans le rôle du pack ne suffit pas : le LLM peut l'ignorer ou être
manipulé par le contenu lu. Le contrôle doit être fait par le code, sur une liste que ni le LLM,
ni une page, ni un manifeste ne peut modifier. Le mécanisme sert aussi aux packs suivants (G7 de
P4). Aucun pack existant ne doit changer de comportement.

## Options
1. **Consigne dans le rôle du pack.** Gratuit ; aucun contrôle effectif (R5).
2. **Plugin `web_research` dédié au pack, avec sa liste en dur.** Contrôle effectif ; duplication
   du code de lecture, une liste par plugin, valeur sensible en dur (R7).
3. **Liste en configuration, contrôlée en code à trois endroits** (retenue) : la liste vient de
   `config/data_sources.yaml#web_allowlists.<domaine>` ; l'adaptateur MCP refuse avant l'appel un
   `web_read` hors liste ; le fetcher recontrôle chaque saut, redirections comprises ; le serveur
   écarte les résultats de `web_search` hors liste. Aucune dépendance nouvelle.

## Décision
Option 3, avec ces règles :
- **Correspondance** : hôte exact ou sous-domaine d'une entrée, après normalisation (IDNA 2008
  comme httpx, minuscules, point final retiré). Aucun joker, aucun motif d'URL ; une adresse IP,
  un identifiant dans l'URL ou un port autre que celui du schéma ne correspond jamais. Module pur
  `core/net/allowlist.py`, couvert à 100 % des branches avec des tests de propriétés. Un seul
  point final est retiré ; une dernière étiquette numérique (décimale ou `0x…`) est refusée.
  L'adaptateur et le fetcher appliquent la même règle (`url_allowed`), port compris, sur l'URL
  telle qu'elle est envoyée.
- **Configuration** : une entrée invalide, une liste vide ou un domaine inconnu arrêtent le
  chargement de la configuration. Un domaine sans liste garde le web ouvert.
- **Transmission** : l'orchestrateur met la liste du domaine routé dans `RequestScope`, et la
  passe au serveur dans `CERVEAU_WEB_ALLOWLIST`, que seul un manifeste qui la déclare dans
  `runtime.env` reçoit. Une valeur héritée de l'environnement est toujours retirée : seule la
  configuration la décide. Une valeur posée mais vide n'autorise rien.
- **Refus** : un `web_read` hors liste est journalisé (`status: hors_liste`), n'est ni envoyé ni
  compté dans le budget. Une redirection hors liste est refusée, pas suivie.
- **Recherche** : avec une liste, le serveur demande 10 résultats à Brave, puis rend au plus
  `max_results` résultats de la liste.

## Conséquences
- Plus simple : un pack se restreint en ajoutant une liste en configuration, sans code.
- Plus difficile : une liste courte peut vider les résultats de recherche ; les opérateurs
  `site:` de Brave ne sont pas utilisés tant que leur comportement n'est pas vérifié (backlog).
- Le contrôle porte sur l'hôte, pas sur le chemin : une page d'un site autorisé reste du contenu
  externe non fiable (R5), lue avec les mêmes garde-fous (anti-SSRF, robots.txt, extraits
  vérifiés).
- Périmètre : seul `web_read` (et la recherche de `web_research`) est restreint. Les plugins qui
  font leurs propres appels réseau (`feeds`, `scholarly`, `cyber_cve`, `code_ci`, `legifrance`)
  restent bornés par leur propre code ; un pack restreint ne doit pas en recevoir un qui lit une
  URL libre.
- Une entrée trop large (`co.uk`, `local`, `internal`, `arpa`) n'est pas refusée par le code :
  la liste est tenue par l'utilisateur, relue à chaque modification (backlog B318).
- Réversible : retirer la liste d'un domaine rend le comportement antérieur.
- Revues demandées : `risk-gate-auditor` (refus en amont) et `security-reviewer` (fetcher,
  redirections, normalisation des hôtes).
