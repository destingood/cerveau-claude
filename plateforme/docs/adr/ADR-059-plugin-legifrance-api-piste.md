# ADR-059 — Plugin `legifrance` : lecture du droit français par l'API officielle PISTE

- Statut : **proposé** (à valider par l'utilisateur au compte rendu de P5)
- Date : 2026-10-27
- Phase : 6 (P5, décisions H1, H3, H4, H9, H10)

## Contexte
Le pack Juridique FR doit citer le texte exact d'un article, dans la version applicable à une
date, avec sa source (R12). Une page web lue par `web_read` ne dit pas de façon fiable quelle
version est affichée ni ses dates de vigueur. La DILA publie Légifrance par une API officielle,
servie par la plateforme PISTE (OAuth 2 `client_credentials`, scope `openid`) ; données sous
Licence Ouverte 2.0, CGU PISTE V1.1 : seules les publications du Journal officiel font foi
(vérifié lors du plan P5 ; Swagger 2.4.2 de l'API). Contraintes : R5 (le texte lu est une donnée),
R6 (identifiants PISTE), R7 (environnement non choisi), R10 (version à la date), R16.

## Options
1. **Lecture des pages de legifrance.gouv.fr par `web_read`.** Rien à ajouter ; pas de dates de
   version structurées, extraction HTML fragile, aucune garantie sur la version affichée.
2. **Copie locale du fonds LEGI (dumps XML de la DILA).** Hors ligne et complète ; plusieurs Go,
   mise à jour quotidienne à maintenir, hors du périmètre de P5.
3. **Plugin MCP de lecture sur l'API PISTE** (retenue) : deux outils de LECTURE, `legi_search`
   et `legi_article`. Aucune dépendance nouvelle (httpx, mcp, Pydantic déjà présents).

## Décision
Option 3 :
- **Entrées fermées** : aucun hôte, URL ou adresse en argument ; identifiants `LEGIARTI`/`LEGITEXT`
  suivis de 12 chiffres, numéro d'article de 30 caractères au plus, date calendaire réelle,
  fonds parmi `CODE_ETAT`, `CODE_DATE`, `LODA_ETAT`, `LODA_DATE`, requête de 200 caractères au
  plus sans caractère de contrôle ni de format. Tout refus est décidé avant la configuration et
  avant toute requête (golden hors ligne du plugin).
- **Version à la date (H3)** : le code décide si la version couvre la date (`début ≤ date < fin`,
  une fin en 2999 vaut « ouverte ») ; une version future, terminée, différée ou abrogée est
  signalée ; en lecture par texte et numéro, si une autre version listée couvre la date, elle est
  lue à la place. Une réponse qui porte sur un autre article que celui demandé est refusée.
- **Bornes** : 10 résultats, extraits courts, texte tronqué à 6 000 caractères, réponse de 2 Mo
  au plus, 20 s par requête, une requête par seconde partagée sous `var/net/` (H10).
- **Identifiants (H4)** : `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET` arrivent par `runtime.env`,
  ne partent que dans la demande de jeton ; le jeton reste en mémoire (renouvelé 60 s avant son
  expiration, effacé sur un 401). Ni identifiant ni jeton dans un journal, un cache, une erreur,
  ni dans une exception chaînée au message d'erreur. Sans eux (ou mal formés), ou en cas de quota
  (429), de 5xx ou de délai : « source officielle indisponible ».
- **Environnement (R7)** : `config/data_sources.yaml › sources.legifrance.url` vaut `A_DEFINIR` ;
  seules les adresses de production et du bac à sable sont acceptées, relues à chaque appel.
- **Cache (H9)** sous `var/juridique/cache/` : 30 jours pour une version `LEGIARTI`, 24 h pour la
  recherche et la version en vigueur ; seule une réponse lisible est gardée, avec son empreinte.
- **Réseau** : https seulement, hôtes PISTE seulement, garde anti-SSRF de `core/net`, pas de
  redirection, pas de proxy de l'environnement. Chaque étape vérifie son propre hôte : le secret
  ne part que vers l'hôte OAuth, le jeton que vers l'hôte API, du même environnement. Le garde
  commun n'accepte que GET, et POST pour cette API (les lecteurs n'ont aucune autre méthode, R5).
- **Cache** : il garde l'empreinte de la requête, jamais les mots cherchés.

## Conséquences
- Plus simple : une citation porte un identifiant de version, ses dates et la date de lecture.
- Plus difficile : l'utilisateur doit créer une application PISTE et choisir l'environnement ; tant que ce
  n'est pas fait, le pack répond « source officielle indisponible » pour Légifrance.
- Points `A_VERIFIER` au premier appel réel (backlog B319 à B323) : valeur `PERTINENCE` du tri,
  forme des URL `article_lc`, fuseau des dates en millisecondes, facette de date de la recherche.
- Un article modifié pendant les 30 jours de cache d'une version reste juste (une version
  `LEGIARTI` ne change pas de texte), mais sa date de fin peut être apprise en retard (B324).
- Le serveur MCP est lancé pour une requête CERVEAU : le jeton n'est réutilisé qu'au sein d'une
  même requête, et le secret part à chaque requête (effet sur les quotas PISTE `A_VERIFIER`).
- Les mêmes variables servent au bac à sable et à la production : changer `url` sans changer de
  variables envoie les identifiants de l'un à l'hôte OAuth de l'autre (même opérateur, risque
  faible). Le jeton et le cache restent séparés par environnement.
- L'empreinte du cache n'est pas authentifiée : qui peut écrire dans `var/juridique/` peut
  fabriquer une citation « lue sur Légifrance ». L'écriture locale est hors du modèle de menace
  (`docs/threat-model.md`) ; un HMAC et un plafond total du cache vont au backlog (B325).
- Réversible : retirer le plugin du pack ; aucun autre composant n'en dépend.
- Couverture : `plugins/legifrance` entre dans `GATE_COVERAGE` (100 % des branches).
- Revue demandée : `security-reviewer` (identifiants, réseau, cache, injection).
