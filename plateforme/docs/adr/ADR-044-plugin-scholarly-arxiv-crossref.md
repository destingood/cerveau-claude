# ADR-044 — Plugins de lecture `scholarly` (arXiv, Crossref) et `feeds` (RSS, Atom)

- Statut : proposé (sources, adresse e-mail et périmètre validés par D10 à D12 le 21/10/2026 ;
  détails d'implémentation ci-dessous à valider par Lucas)
- Date : 2026-10-22
- Phase : 6

## Contexte
Le pack `recherche` (P2) doit citer des publications vérifiables. D10 retient arXiv et Crossref,
exclut OpenAlex et ne prend HAL que si ses conditions le permettent ; D11 interdit d'envoyer une
adresse e-mail à Crossref ; D12 limite la lecture aux métadonnées et résumés, sans PDF. Règles
concernées : R5 (contenu externe = données), R6, R13 (2 outils), R14, R15 (CGU).

Faits vérifiés à la source le 2026-10-21 (requêtes réelles et documentation) :
- arXiv ([conditions de l'API](https://info.arxiv.org/help/api/tou.html)) : une requête toutes
  les 3 s et une seule connexion pour toutes les machines d'un utilisateur ; métadonnées CC0 ;
  réponses Atom (`application/atom+xml`), erreur = HTTP 400 et entrée `arxiv.org/api/errors#`.
- Crossref ([accès](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/),
  [licence](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-metadata-license-information/)) :
  pool public sans `mailto` ; en-têtes observés `x-rate-limit-limit: 1`, `x-rate-limit-interval:
  1s`, `x-concurrency-limit: 1` (la documentation du 2025-10-16 annonçait 5 par seconde) ; 429 =
  débit dépassé, 403 = blocage ; métadonnées libres, **résumés sous droit d'auteur**.
- HAL : aucune condition d'utilisation propre à `api.archives-ouvertes.fr` trouvée → non intégré.

## Options
1. **Plugin maison `scholarly`, `httpx` + `defusedxml`** : deux outils de LECTURE, hôtes fixes,
   limiteur partagé. Aucune nouvelle dépendance transitive ; defusedxml 0.7.1 (PSF-2.0) déjà au
   verrou. Coût : environ 900 lignes et leurs tests.
2. **Bibliothèques clientes (`arxiv`, `habanero`)** : moins de code, mais deux dépendances de plus,
   un débit et des en-têtes qu'on ne maîtrise pas, un parseur XML non durci.
3. **Lecture par `web_read`** des pages arXiv et doi.org : rien à écrire, mais HTML instable,
   pas de date ni de rétractation structurées, robots.txt et CGU du HTML à respecter.

## Décision
Option 1. Choix d'implémentation :
- **Hôtes fixes** (`export.arxiv.org`, `api.crossref.org`) : aucune URL ne vient du planificateur,
  donc pas d'épinglage DNS ; redirections refusées, proxys ignorés, 15 s et 2 Mo par réponse.
- **Débit partagé** `core/net/throttle.py` : verrou de fichier OS (`msvcrt` ou `fcntl`) et date de
  fin de la dernière requête dans `var/net/<api>.*` sous la racine du projet (quel que soit le
  dossier de lancement), pour que tous les processus du plugin
  (`LazyPlugin` en lance un par requête) respectent 3 s (arXiv) et 1 s (Crossref) ; attente du
  verrou bornée à 30 s, puis erreur claire. Les deux branches OS sont exclues de la couverture et
  testées par la matrice CI Windows et Linux.
- **Anti-injection de syntaxe arXiv** : les mots du planificateur deviennent des termes `all:`
  (lettres et chiffres, minuscules, 12 au plus) joints par `AND`.
- **XML** : `defusedxml` avec DTD refusées (ni entité, ni référence externe).
- **Textes** : caractères de contrôle et invisibles retirés, balises ôtées, coupe marquée par « … »
  dans `core/net/text.py`, réutilisable par les autres plugins de lecture.
- **Résumés** : arXiv coupé à 2 000 caractères (CC0) ; Crossref coupé à 1 000, jamais stocké ni
  mis en cache ; le fichier de recherche n'en garde que l'empreinte des citations (ADR-045).
  Rétractations et corrections exposées (`updated_by`, `update_to`).
- **Dates** : partielles acceptées (`2024`, `2024-02`) ; avec `since`, une notice n'est gardée que
  si sa date la plus précoce possible est postérieure ou égale (prudence).
- **DOI** : motif recommandé par Crossref pour les DOI modernes, sans segment « . » ni « .. »
  (une fois dans l'adresse, il viserait un autre chemin de l'API) ; les anciens SICI avec `<>`
  sont hors périmètre.

## Conséquences
- Plus simple : citations vérifiables (DOI, identifiant arXiv) pour l'agent `deep_research`
  (ADR-045) ; aucun secret, aucune clé, aucune donnée personnelle envoyée.
- Plus difficile : 1 requête par seconde côté Crossref ; une recherche approfondie de 12 lectures
  dure au moins une dizaine de secondes.
- Réversible : plugin isolé, retirable sans toucher au reste.
- Backlog : cache disque des réponses arXiv (conseillé par arXiv) ; HAL si ses conditions d'API
  sont publiées (`A_VERIFIER`) ; sens exact de `updated-by` à confirmer sur de vraies
  rétractations (`A_VERIFIER`) ; `slo.p95_latency_ms` à `A_DEFINIR`.

## Complément : plugin `feeds` (RSS 2.0 et Atom 1.0)
Un outil de LECTURE, `feed_read`, pour la veille du pack (D16 à D18). Options écartées :
`feedparser` (dépendance de plus, parseur permissif qui suit les DTD selon le moteur XML) et
`web_read` (pas de structure d'entrée ni de date). Retenu : `defusedxml` et un parseur maison
(environ 500 lignes et leurs tests, dont des tests de propriétés Hypothesis). Choix :
- **Liste blanche** `flux` de `domain_packs/recherche/knowledge/sources.yaml`, relue à chaque appel
  et livrée vide (D18) : le planificateur donne un identifiant, jamais une URL. Seul Lucas ajoute un
  flux, après contrôle des CGU et de la licence du site ; elle tient lieu de robots.txt (R15).
- **`A_VERIFIER` ou `A_DEFINIR` bloque** : un flux listé dont un champ n'est pas tranché n'est pas lu
  (R7). URL en https seulement.
- **Réseau** : garde anti-SSRF de `core/net` (adresses publiques, requête épinglée, ports 80 et
  443), car un nom public peut un jour pointer vers l'intérieur ; aucune redirection (le flux
  déplacé se corrige dans la liste) ; types XML seulement ; 15 s et 2 Mo.
- **Entrées** : titre, lien (affiché, jamais suivi), date en UTC, résumé coupé à 1 000 caractères ;
  contenus complets ignorés (D12) ; 20 entrées au plus. Avec `since`, une entrée sans date est
  écartée, comme dans `scholarly`.
- Backlog : questions d'éval sur le contenu des flux une fois la liste remplie ; requêtes
  conditionnelles (`ETag`, `If-Modified-Since`) pour ménager les sites ; `slo.p95_latency_ms` à
  `A_DEFINIR`.
