# Complément de plan — Phase 6, pack P6 Business & commerce

Date : 29/10/2026 · Statut : **validé** le 29/10/2026 (`GO P6`, recommandations I1 à I12).

Complément au plan de phase 6 (`docs/plans/phase-6-plan.md`, §7, D22). Tout ce qui n'est pas repris
ici suit ce plan :
- domaine `business` en N0, `max_level` N1 (D3, plafond déjà inscrit dans `core/config/loader.py:419`) ;
- seuil du golden 0,80 (D4) ;
- aucune mesure réelle sans ton accord et sans budgets (D5) ;
- revues dans la session (D9) ;
- communications en brouillon seulement (D22) ;
- avertissement R16 vérifié par les comportements (D23).

P6 est le dernier pack de la phase : après lui viennent le compte rendu §18 de la phase 6 et l'arrêt
jusqu'à `GO PHASE 7`.

## 0. En une phrase

Le pack `business` aide à étudier un marché, fixer un prix, mesurer une rentabilité et rédiger des
textes commerciaux. Tous ses chiffres sortent d'un outil de calcul déterministe ou d'une source
publique citée (R1). Il lit les données légales des entreprises françaises et des statistiques de
l'INSEE. Il n'envoie rien : tout texte destiné à un tiers reste un brouillon que tu relis et
envoies toi-même.

## 1. Vérifié aujourd'hui (29/10/2026)

| Fait | Source |
|---|---|
| **API Recherche d'entreprises.** Base `https://recherche-entreprises.api.gouv.fr`, accès « ouvert », sans clé. Deux chemins `GET` : `/search` (texte, SIREN ou SIRET, filtres code postal, département, NAF, catégorie, état administratif, tranche d'effectif, chiffre d'affaires) et `/near_point` (rayon par défaut 5 km, 50 km au plus). Pagination `per_page` de 25 au plus. Champs : `siren`, `nom_complet`, `siege`, `activite_principale`, `categorie_entreprise`, `etat_administratif`, `date_creation`, `date_fermeture`, `tranche_effectif_salarie`, `finances`, `dirigeants`, `complements`, `date_mise_a_jour_insee`, `date_mise_a_jour_rne`, etc. | data.gouv.fr/dataservices/api-recherche-dentreprises ; `recherche-entreprises.api.gouv.fr/openapi.json` (OpenAPI 1.0.0) |
| **Débit.** 7 appels par seconde par adresse IP et 30 par seconde par ASN ; au-delà, HTTP 429 avec `Retry-After`. La spécification précise que ce sont des maximums, pas un débit garanti, et data.gouv.fr que l'administration peut les abaisser | mêmes sources |
| **Périmètre et licence.** Les entreprises non diffusibles et celles dont l'immatriculation au RCS a été refusée sont exclues ; l'API ne donne pas la base Sirene complète. La spécification OpenAPI porte la licence MIT (code de l'API) ; la licence des données renvoyées n'est pas écrite sur la page : Licence Ouverte 2.0 par la mention générale de data.gouv.fr, `A_VERIFIER` pour les données elles-mêmes (Sirene, RNE) | mêmes sources |
| **Données personnelles.** L'API expose les `dirigeants` (personnes physiques) et accepte une recherche par nom, prénoms et date de naissance d'une personne. Le nom d'un entrepreneur individuel est souvent le nom de l'entreprise | `openapi.json` |
| **INSEE Melodi.** Base `https://api.insee.fr/melodi/`, « ouvert avec compte », avec un mode anonyme limité à 30 appels par minute. Donne accès aux données du catalogue de l'INSEE, mises à disposition sous la Licence Ouverte. Schéma des réponses : `A_VERIFIER` sur la documentation du portail et sur un vrai appel | data.gouv.fr/dataservices/api-melodi ; insee.fr/fr/information/8184173 |
| **Eurostat.** API JSON-stat gratuite ; données réutilisables, y compris commercialement, en citant la source (CC BY 4.0 pour le contenu éditorial) ; exceptions pour les données de tiers et des pays hors UE et AELE | ec.europa.eu/eurostat (API introduction ; copyright notice) |
| **Taux de TVA français** (20 %, 10 %, 5,5 %, 2,1 %) : connus, mais non relus aujourd'hui dans le CGI. `A_VERIFIER` avant leur entrée en configuration, article par article, par Légifrance | CGI art. 278 et suivants (à relire) |
| **Dépôt.** `business` figure dans `DOMAINS` et `DOMAIN_MAX_LEVELS` (N1). `domain_packs/business/` est vide. Le cas `pack-business-absent` attend l'absence du pack. `COMMUNICATION_EXTERNE` vaut `refus` en N0 et `brouillon` en N1 ; aucun plugin ne sait envoyer un message. ADR-060 est le dernier ADR, B333 la dernière entrée du backlog, T39 et A16 les dernières menace et ressource | `core/registry/manifest.py:26`, `core/config/loader.py:419`, `domain_packs/generaliste/evals/behaviors.yaml:99`, `config/autonomy.yaml:12` |

## 2. Plugins et outils (I1)

| Plugin | Outil (classe) | Entrée | Sortie |
|---|---|---|---|
| `business_calc` | `biz_calc` (CALCUL) | opération parmi une liste fermée, paramètres numériques typés (Pydantic, `Decimal`) | résultat, formule, paramètres repris, arrondi, unité ; aucune hypothèse ajoutée |
| `entreprises` | `company_search` (LECTURE) | texte (100 caractères au plus) ou SIREN (9 chiffres, contrôle de Luhn) ; filtres code postal, département, code NAF, état administratif ; 10 résultats au plus | Par entreprise : SIREN, dénomination, NAF, catégorie, état, dates de création et de fermeture, commune du siège, tranche d'effectif, chiffre d'affaires et résultat publiés avec leur année, dates de mise à jour. **Aucun dirigeant, aucune personne** (I4) |
| `insee_stats` | `stats_series` (LECTURE) | identifiant de jeu de données Melodi (liste fermée dans `knowledge/sources.yaml`), filtres de dimensions, période | valeurs avec unité, période, date de publication, identifiant du jeu ; données (R5) |
| `web_research` (réutilisé) | `web_search`, `web_read` (LECTURE) | inchangés | sans liste fermée de domaines (I6) |

Opérations de `biz_calc`, toutes déterministes et testées :
- marge brute, taux de marge et taux de marque, coefficient multiplicateur ;
- prix de vente HT ou TTC depuis un coût et une marge cible, ou l'inverse ;
- TVA : HT → TTC et TTC → HT, à un taux de la liste de `config/business.yaml` (I7) ;
- seuil de rentabilité et point mort en jours, depuis charges fixes et taux de marge sur coûts variables ;
- coût d'acquisition client (CAC), valeur vie client (LTV) et rapport LTV/CAC, depuis des entrées fournies par toi ;
- variation en pourcentage et taux de croissance annuel composé.

Règles communes :
- **Cinq outils**, dans la borne de R13.
- **Réseau.** `entreprises` et `insee_stats` passent par l'anti-SSRF de `core/net/` avec une liste fixe d'hôtes (`recherche-entreprises.api.gouv.fr`, `api.insee.fr`) déclarée dans `config/data_sources.yaml`.
- **Débit et cache.** Limiteur partagé `core/net/throttle.py` : 2 requêtes par seconde pour `entreprises` et 20 par minute pour Melodi [hypothèses, sous les maximums publiés]. Un 429 respecte `Retry-After` une fois, puis « source indisponible ». Cache sous `var/business/` : fiche d'entreprise 24 h, série statistique 7 jours. Plafond de 2 Mo par réponse.
- **Point-in-time (R10).** Chaque chiffre lu porte son année ou sa période et sa date de mise à jour ; une donnée plus récente que la date de la question n'est pas utilisée pour un calcul daté.

## 3. Pack `domain_packs/business/`

- **`manifest.yaml`**
  - statut `experimental` ;
  - plugins `business_calc`, `entreprises`, `insee_stats`, `web_research` ;
  - hors périmètre :
    - envoi ou publication de quoi que ce soit (courriel, message, publication, annonce) : D22 ;
    - conseil fiscal, social ou comptable appliqué à ta situation (régime, cotisations, impôt) : renvoi vers le pack `juridique_fr` pour les textes et vers un professionnel pour le conseil ;
    - profilage de personnes, prospection nominative, collecte de coordonnées (RGPD, R15) ;
    - conseil à des tiers (R16).
- **`prompts/role.md`**
  - Méthode : qualifier la question (marché, prix, rentabilité, rédaction), lire les sources, calculer avec `biz_calc`, distinguer données publiées, hypothèses fournies par toi et estimations (R12), finir par les limites et ce qu'il faudrait mesurer.
  - Jamais de chiffre hors d'une sortie d'outil ou d'une citation datée (R1).
  - Une rédaction commerciale est rendue sous l'en-tête « Brouillon — non envoyé ».
- **`prompts/rubric.md`** : chiffres tracés jusqu'à leur outil, hypothèses séparées des données, sources datées, brouillon marqué, aucune promesse de résultat, R16.
- **`knowledge/sources.yaml`** : les deux API, leurs licences et dates de vérification, la liste fermée des jeux Melodi (quelques-uns : démographie des entreprises, prix à la consommation, population par commune ; identifiants `A_VERIFIER`).
- **Mentions (I8)**, ajoutées en pied de réponse par le code selon les outils appelés (mécanisme G9, `core/orchestrator/notices.py`) :
  - « Source : API Recherche d'entreprises (DINUM, données INSEE et INPI), mise à jour du … » ;
  - « Source : INSEE, Melodi, jeu …, publié le … » ;
  - « Brouillon : rien n'a été envoyé » quand la réponse contient une rédaction ;
  - l'avertissement R16 (D23).
- **Configuration.**
  - `config/autonomy.yaml` : `business: { level: N0, max_level: N1 }`. Aucune règle de politique ne change.
  - `config/evals.yaml` : `business_golden_min_score: 0.80` (D4).
  - `config/data_sources.yaml` : entrées `entreprises` et `insee_melodi` (hôtes, débit, licence, quotas).
  - `config/business.yaml` (nouveau, chargé et validé par `core/config/`) : taux de TVA avec article du CGI et date de vérification, arrondi ; toute valeur non relue reste `A_VERIFIER` et bloque l'opération TVA (R7).
- **Cas `pack-business-absent` (I11).** Remplacé dans la même modification, par ADR.

## 4. Brouillons (D22, I5)

- **N0 livré.** Le pack n'a aucun outil d'envoi. Une rédaction (courriel, fiche produit, publication, réponse à un client) est du texte dans la réponse, jamais une action.
- Le code marque la réponse « Brouillon — non envoyé » et l'audit enregistre qu'un brouillon a été produit (R11), sans son contenu.
- Un brouillon ne contient aucune donnée personnelle de tiers venue d'un outil.
- L'envoi réel reste `COMMUNICATION_EXTERNE` : refusé en N0, brouillon en N1, approbation à partir de N3. Aucun outil d'envoi n'est créé en phase 6.

## 5. Autonomie et refus (R1, R15, R16)

Refus vérifiés par les comportements et la red team :
- chiffre demandé sans données (« quel prix pour mon produit ? » sans coût) : demander les entrées ou rendre une fourchette tirée d'une source citée, jamais un chiffre inventé ;
- envoi, publication ou programmation d'un message ;
- recherche de personnes, de dirigeants ou de coordonnées ;
- faux avis, publicité trompeuse, contournement de règles de plateforme (R15) ;
- conseil fiscal ou social appliqué à un cas réel ;
- question pour un tiers (R16).

« Je ne sais pas » est valide (R12) : entreprise introuvable, série absente, API indisponible.

## 6. Évaluations

| Suite | Contenu | Seuil |
|---|---|---|
| `domain_packs/business/evals/golden.jsonl` (32 cas, hors ligne, résultats d'outils scriptés) | répartition ci-dessous | 0,80 en campagne réelle (D4) |
| `domain_packs/business/evals/behaviors.yaml` | R1 (chaque chiffre vient de `biz_calc` ou d'une source datée), R5, R10, R12, R16, brouillon marqué et jamais envoyé, aucune personne citée depuis `entreprises`, mentions présentes | 1,0 |
| `evals/redteam/injection_business/` (≥ 10 cas) | consigne cachée dans une page web, une dénomination d'entreprise ou un libellé de série ; demande d'envoyer le brouillon ; demande de lister les dirigeants ; faux avis ; prix « calculé » par le modèle ; réponse surdimensionnée ; série datée après la question | 0 violation |
| Suites existantes | relancées, inchangées (R9), sauf le remplacement de I11 | inchangés |

| Type de cas du golden | Nombre |
|---|---|
| Prix, marge, coefficient, TVA calculés par `biz_calc` | 8 |
| Seuil de rentabilité, CAC/LTV, croissance | 4 |
| Fiche d'entreprise et petite étude de concurrence (`company_search`) | 5 |
| Statistique publique datée (`stats_series`) | 3 |
| Rédaction commerciale rendue en brouillon | 4 |
| « Je ne sais pas » (données manquantes, entreprise introuvable, API indisponible) | 3 |
| Refus : envoi, personnes, faux avis, conseil fiscal ou pour un tiers | 3 |
| Injection (R5) | 2 |

## 7. Tests (aucun réseau en CI)

- **Calculs.** Hypothesis sur chaque opération : inverses (HT → TTC → HT), bornes (marge 0 et 100 %, charges nulles, division par zéro refusée), `Decimal` et arrondi déclaré ; valeurs de référence calculées à la main.
- **HTTP.** `httpx.MockTransport` et fixtures synthétiques au format de `openapi.json` ; 429 avec `Retry-After` ; réponse surdimensionnée ; hôte hors liste.
- **Personnes.** Les champs `dirigeants` et les paramètres de recherche de personne n'atteignent jamais la sortie ni le cache (test sur une fixture qui les contient).
- **SIREN.** Validateur (9 chiffres, clé de Luhn) sous Hypothesis.
- **Kill switch** : `KILL` arrête un appel en cours.
- **Couverture.** 100 % des branches pour `business_calc`, les validateurs et le filtrage des personnes ; ajoutés à `GATE_COVERAGE` dès le départ.

## 8. Dépendances et licences (R14)

- Aucune nouvelle dépendance Python : `httpx`, Pydantic et `decimal` suffisent.
- `docs/licences.md` reçoit l'API Recherche d'entreprises (code MIT ; données `A_VERIFIER`, Licence Ouverte 2.0 attendue) et Melodi (Licence Ouverte).
- Revue `security-reviewer` (§17) des plugins `entreprises` et `insee_stats` avant leurs commits ; `quant-reviewer` relit `business_calc` (formules et arrondis).

## 9. Hors périmètre → `docs/backlog.md`

- Envoi réel d'un brouillon (messagerie, réseaux sociaux, boutique) : outil `COMMUNICATION_EXTERNE` avec approbation, phase 7 ou suivante.
- Cotisations, régimes fiscaux et seuils de la micro-entreprise : outils déterministes sourcés, liés au pack `juridique_fr` (comme B329).
- Eurostat et données internationales (I3).
- Lecture des données de ta boutique (ventes, catalogue, statistiques de plateformes) : connecteur en lecture seule, avec son propre ADR.
- Annonces légales (BODACC) et comptes annuels détaillés (INPI).

## 10. Coût estimé (hypothèses, non mesuré)

- **Développement** : 0 €, tout passe hors ligne.
- **API Recherche d'entreprises et Melodi** : gratuites.
- **`web_search`** : tarif Brave existant.
- **Campagne réelle P6** : environ 32 cas du golden, une dizaine de cas de red team et les suites relancées, soit **5 à 15 $** (même base que P2 à P5). Elle n'a lieu qu'avec ton accord, après celles déjà en attente.
- Budgets journalier et mensuel `A_DEFINIR` : tout appel réel reste bloqué (R7).

## 11. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| I1 | Outils du pack (R13) | 4 outils sans statistiques / **5 outils** : `biz_calc`, `company_search`, `stats_series`, `web_search`, `web_read` | **5 outils** : une étude de marché sans statistique publique datée pousse le modèle à inventer des chiffres |
| I2 | `biz_calc` | un outil par opération / **un outil, opération dans une liste fermée** | **un outil** : la borne de R13 tient, chaque opération garde ses tests |
| I3 | Statistiques | **INSEE Melodi, mode anonyme** / Eurostat / les deux | **Melodi seul** ; Eurostat au backlog |
| I4 | Personnes dans les données d'entreprise | tout exposer / **aucun dirigeant, aucune recherche de personne, filtrés par le code** | **filtrés par le code** (RGPD, R15) ; la dénomination d'un entrepreneur individuel reste, puisque c'est le nom légal de l'entreprise |
| I5 | Rédaction (D22) | **texte dans la réponse marqué « Brouillon — non envoyé » par le code** / aucun marquage | **marqué par le code**, aucun outil d'envoi |
| I6 | Liste fermée de domaines pour `web_research` (ADR-058) | **aucune liste** / liste fermée | **aucune liste** : une étude de marché lit des sites de concurrents variés ; R5 et le lecteur sans outil d'action s'appliquent |
| I7 | Taux de TVA | en dur / **`config/business.yaml`, chaque taux avec son article du CGI relu dans Légifrance**, `A_VERIFIER` sinon | **configuration sourcée** (R7) |
| I8 | Mentions | écrites par le LLM / **ajoutées par le code** | **par le code**, comme G9 et H7 |
| I9 | Cache | aucun / **fiche 24 h, série 7 jours**, sous `var/business/` | **24 h et 7 jours** |
| I10 | Débit | maximums publiés / **2 par seconde et 20 par minute** [hypothèses] | **2/s et 20/min**, sous les maximums |
| I11 | Cas `pack-business-absent` (R9), dernier de sa série | **remplacé par `pack-cuisine-absent` par ADR, et B263 clos** puisqu'aucun pack n'est plus prévu / ADR seul, B263 ouvert | **remplacement par ADR et B263 clos** |
| I12 | Campagne réelle | aucune / P6 après les campagnes en attente | **aucune** sans ton accord et sans budgets |

## 12. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated P6 plan`
2. `feat(config): add the business domain at N0, its golden threshold, its sources and VAT rates`
3. `feat(business_calc): add the deterministic business calculator plugin` + ADR-061 (I1, I2, I7)
4. `feat(entreprises): add the company registry reader without personal data` + ADR-062 (I4, I9, I10)
5. `feat(insee_stats): add the INSEE Melodi statistics reader` (I3)
6. `feat(answer): append the business notices and the draft marker` (I5, I8)
7. `feat(business): add the business pack (manifest, prompts, sources)` + ADR-063 (I11)
8. `test(evals): add the business golden set and behaviours`
9. `test(redteam): add the injection cases of the business pack`
10. `docs: update licences, threat model and backlog for the business pack` (T40 personne exposée par les données d'entreprise ; T41 brouillon présenté comme envoyé ou envoyé ; T42 chiffre commercial inventé ; T43 injection par une dénomination ou un libellé)
11. `docs: add the business pack report and the phase 6 report` (§18)

## 13. Exécution

- **Après ta validation.**
  1. Commit 1.
  2. Contrôle des `A_VERIFIER` du §1 : licence des données de l'API, taux de TVA dans le CGI, jeux Melodi et leur schéma.
  3. Commits 2 à 9, avec les revues `quant-reviewer` et `security-reviewer`.
  4. Commit 10, compte rendu du pack, puis compte rendu §18 de la phase 6, et arrêt jusqu'à `GO PHASE 7`.
- **Avant le premier usage réel** : tu fixes les budgets ; aucune clé n'est nécessaire.
