# ADR-062 — Plugin `entreprises` : lecteur du registre des entreprises, sans personne

- Statut : **proposé** (à valider par Lucas au compte rendu de P6)
- Date : 2026-10-29
- Phase : 6 (P6, décisions I4, I9, I10)

## Contexte
Le pack Business & commerce a besoin des données légales d'une entreprise française : identité,
activité, état, siège, comptes publiés. L'API Recherche d'entreprises (DINUM, données INSEE et
INPI) les donne sans compte ni clé (`https://recherche-entreprises.api.gouv.fr`, OpenAPI 1.0.0 lue
le 2026-10-29 ; plafond publié de 7 requêtes par seconde et par IP). Ses réponses contiennent
aussi les `dirigeants` (nom, prénoms, mois et année de naissance) et l'adresse du siège, souvent
le domicile d'un entrepreneur individuel ; et son texte `q` cherche aussi dans les dirigeants, les
élus et l'adresse (OpenAPI : « dénomination et/ou adresse, dirigeants, élus »). Règles en jeu : R1 (chiffres), R4 (kill switch), R5
(libellés externes), R7 (source en configuration), R13, R15 et le RGPD (I4). La licence des
données renvoyées n'est pas écrite sur la page de l'API : `A_VERIFIER` (Licence Ouverte 2.0
attendue) ; la spécification est sous licence MIT.

## Options
1. **Rendre la réponse de l'API telle quelle** : simple ; expose des personnes et laisse le
   modèle trier (contraire à I4).
2. **Ne pas demander les dirigeants** (`minimal=true&include=siege,finances`) et faire confiance
   à l'API : moins de données transférées, mais un changement de l'API ferait réapparaître les
   personnes.
3. **Ne pas les demander et filtrer par une liste fermée de champs dans le code**, avant le cache
   et la sortie (retenue).

## Décision
Option 3.
- **Un outil, `company_search` (LECTURE).** Texte de 3 à 100 caractères, sans caractère de
  contrôle ni de format, ou SIREN de 9 chiffres ASCII dont la clé de Luhn est juste ; un numéro à
  9 chiffres donné comme texte est refusé (il va dans `siren`). Une seule forme d'entrée. Filtres
  facultatifs : code postal (5 chiffres), département (01 à 95 sauf 20, 2A, 2B, 971 à 974, 976),
  code NAF (`47.91B`), état administratif (`A` ou `C`). Aucun paramètre de personne n'existe, et
  un argument inconnu n'est jamais transmis.
- **Pas de recherche par personne ni par adresse.** Une recherche textuelle ne garde que les
  résultats dont la dénomination, la raison sociale ou le sigle contient chaque mot du texte
  (minuscules, sans accents) ; son total compte ces seuls résultats, car celui de l'API dirait
  combien d'entreprises une personne dirige.
- **Sortie fermée.** 10 entreprises au plus : SIREN, dénomination (200 caractères), sigle, NAF,
  catégorie, état, dates de création et de fermeture, commune, code postal et département du
  siège (pas de rue), tranche d'effectif, comptes des 5 derniers exercices, dates de mise à jour.
  Le siège d'une personne physique (catégorie juridique 1xxx, ou catégorie illisible) est omis :
  c'est souvent un domicile.
  Chaque montant et le total sont des `Figure` (R1) ; une année reste du texte. Un champ mal formé
  est omis, jamais deviné.
- **Réseau.** Hôte unique en HTTPS, égal à l'URL de `config/data_sources.yaml` relue à chaque
  appel ; garde anti-SSRF de `core/net` (adresse publique, connexion épinglée), sans redirection
  ni proxy d'environnement ; 15 s par essai, 2 Mo par réponse.
- **Débit (I10).** 2 requêtes par seconde partagées sous `var/net/` ; un 429 avec `Retry-After`
  de 5 s au plus est retenté une fois, sinon « source indisponible ».
- **Cache (I9).** 24 h sous `var/business/cache/entreprises/`, de la seule sortie filtrée : la
  réponse brute n'atteint jamais le disque. Une copie illisible demande de relancer.
- **Kill switch (R4).** Vérifié avant la lecture du cache, avant chaque requête (retentative
  comprise) et avant chaque bloc lu.

## Conséquences
- Aucune personne ne sort du code, même si l'API change ; une dénomination d'entrepreneur
  individuel reste, car c'est le nom légal de l'entreprise, mais sans commune ni code postal (I4).
  Choix par défaut le plus protecteur, que Lucas peut revoir (autre option : exclure ces
  entreprises des recherches textuelles).
- Risque accepté : le nom d'un fichier du cache est l'empreinte SHA-256, sans sel, de la requête ;
  le texte cherché peut donc être retrouvé par dictionnaire sur le disque local (`var/`, ignoré
  par git). Une empreinte HMAC à clé locale va au backlog.
- Ni `/near_point`, ni pagination, ni SIRET, ni filtres d'effectif ou de chiffre d'affaires :
  au backlog si les évals les justifient (R13).
- Tests hors ligne (fausse API, faux DNS), couverture de branches à 100 % dans la porte de la CI ;
  golden set refusé avant tout appel.
- `A_VERIFIER` : licence des données (`docs/licences.md`), plafond de débit réel ;
  `A_DEFINIR` : `slo.p95_latency_ms`.
