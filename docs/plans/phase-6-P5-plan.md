# Complément de plan — Phase 6, pack P5 Juridique et administratif FR

Date : 27/10/2026 · Statut : **validé** le 27/10/2026 (`GO P5`, recommandations H1 à H12).

Complément au plan de phase 6 (`docs/plans/phase-6-plan.md`, §7, D21). Tout ce qui n'est pas repris
ici suit ce plan : domaine `juridique_fr` en N0 et `max_level` N1 (D3, plafond déjà inscrit dans
`core/config/loader.py:394`), seuil du golden 0,80 (D4), aucune mesure réelle sans ton accord et
sans budgets (D5), revues dans la session (D9), avertissement R16 vérifié par les comportements
(D23). D21 : l'API officielle plutôt qu'un RAG vectoriel ; sans identifiants PISTE, le pack répond
« source officielle indisponible ».

## 0. En une phrase

Le pack `juridique_fr` répond aux questions de droit et de démarches administratives françaises en
citant des articles lus par l'API Légifrance, chacun avec son identifiant, son état et ses dates de
vigueur, vérifiés par le code, et des fiches officielles lues sur une liste fermée de domaines
publics. Il informe, ne conseille pas (R16) et rappelle que seul le Journal officiel fait foi.

## 1. Vérifié aujourd'hui (27/10/2026)

| Fait | Source |
|---|---|
| **Accès à l'API Légifrance.** API de la DILA, gratuite après inscription sur PISTE. Il faut accepter les CGU de PISTE et celles de l'API Légifrance, puis ajouter l'API à une application. Une application *sandbox* est créée avec le compte ; la production demande sa propre application. Statut affiché : « Restreint » | data.gouv.fr/dataservices/legifrance ; CGU de l'API Légifrance, §III.2 |
| **Licence des données.** Licence Ouverte 2.0 d'Etalab, plus les CGU de PISTE et de l'API Légifrance. La Licence Ouverte impose de citer la source (au moins le concédant) et la date de dernière mise à jour, sans laisser croire à un aval officiel ; elle est compatible CC-BY, OGL et ODC-BY | data.gouv.fr/dataservices/legifrance ; data.gouv.fr/pages/legal/licences/etalab-2.0 |
| **CGU de l'API Légifrance** (PDF « DILA_Legifrance_Beta_v2 », V1.1 du 04/08/2020, lu en extrayant son texte). L'API est en bêta, sans disponibilité minimale garantie (§IV.1). La DILA ne garantit ni le contenu, ni sa complétude, ni sa fraîcheur (§VI.1). Les données « ne sont pas opposables » : seuls les PDF signés du Journal officiel le sont (§VI.1). Les clés sont réservées à l'application et ne se divulguent pas (§III.3). Une compromission impose de les réinitialiser et de prévenir la DILA (§V.3). Version des CGU en vigueur aujourd'hui : `A_VERIFIER` sur PISTE | piste.gouv.fr/images/cgu/DILA_Legifrance_Beta_v2.pdf |
| **Quotas.** Limites par seconde, minute ou jour, en requêtes ou en bande passante, par application ou par méthode. Les valeurs se lisent seulement dans PISTE (« API Sélectionnées » → « Actions » → « Consulter les quotas ») et peuvent changer sans préavis (§IV.3). Valeurs : `A_VERIFIER`, lues par toi une fois le compte créé | CGU §IV.3 ; data.gouv.fr (« limités par quotas par jetons d'accès ») |
| **Authentification.** OAuth 2.0 à chaque requête (§III.3). Jeton : `https://oauth.piste.gouv.fr/api/oauth/token`, scope `openid`. Bac à sable : `sandbox-oauth.piste.gouv.fr` et `sandbox-api.piste.gouv.fr`. Le flux *client credentials* et la durée de vie d'une heure du jeton viennent de sources tierces : `A_VERIFIER` | spécification OpenAPI (`securityDefinitions`) ; guides et clients tiers |
| **Points d'accès** (spécification Swagger 2.0 « Légifrance » 2.4.2, `host` `api.piste.gouv.fr`, `basePath` `/dila/legifrance/lf-engine-app`, 68 chemins, tous en POST sauf les `ping`). `/consult/getArticle` `{id}` renvoie un article : `id`, `cid`, `num`, `etat`, `dateDebut`, `dateFin`, `texte`, `texteHtml`, `versionArticle`, `articleVersions`, `textTitles`, `idEli`. `/search/canonicalArticleVersion` `{id}` renvoie les versions d'un article. `/consult/getArticleWithIdAndNum` `{id du LEGITEXT, num}` renvoie la version en vigueur, sans les versions à vigueur différée. `/consult/legiPart` `{textId, date}` renvoie un texte LEGI à une date. `/search` `{recherche, fond}`. Spécification officielle sur PISTE (Swagger, derrière connexion) ; copie lue dans un client libre : le schéma exact des réponses reste `A_VERIFIER` sur un vrai appel | `pylegifrance/models/generated/legifrance.json` (licence MIT, poussé le 19/08/2026) |
| **Judilibre** (Cour de cassation, sur PISTE). CGU du 06/01/2022 : droit de réutilisation gratuit sous Licence Ouverte 2.0 ; interdiction du profilage des magistrats et des greffiers (L. 111-13 du COJ) ; obligation de citer la base Open Data de la Cour et la date de dernière mise à jour ; décisions pseudonymisées ; la Cour peut supprimer ou corriger une décision à tout moment ; mêmes quotas que Légifrance. Source secondaire : une décision retirée doit aussi être supprimée des copies du réutilisateur (`A_VERIFIER`) | piste.gouv.fr/images/cgu/CGU_open_data_V8.pdf ; paquet tiers `omnilex/judilibre` |
| **Service-public.** Le domaine est désormais `service-public.gouv.fr` : `service-public.fr` y redirige (301). « Sauf mention contraire, tous les contenus de ce site sont sous licence etalab-2.0 » ; on cite la source et la date de mise à jour. Les logos et les marques de la DILA sont exclus | service-public.gouv.fr/P10150 |
| **Autres domaines officiels candidats** : `legifrance.gouv.fr`, `entreprendre.service-public.gouv.fr`, `impots.gouv.fr`, `bofip.impots.gouv.fr`, `conseil-etat.fr`, `courdecassation.fr`, `cnil.fr`, `urssaf.fr`, `economie.gouv.fr`. Licence et redirections : `A_VERIFIER`, domaine par domaine, avant l'entrée en liste | — |
| **Dépôt.** `juridique_fr` figure dans `DOMAINS` et dans `DOMAIN_MAX_LEVELS` (N1). `domain_packs/juridique_fr/` ne contient qu'un `.gitkeep`. Le cas `pack-juridique-absent` attend l'absence du pack. `web_read` suit lui-même jusqu'à 5 redirections, lit `text/html` et `text/plain` seulement, et respecte robots.txt. Les mentions de source sont ajoutées par le code (G9). ADR-057 est le dernier ADR, B316 la dernière entrée du backlog, T35 et A15 les dernières menace et ressource | `core/registry/manifest.py:26`, `core/config/loader.py:394`, `domain_packs/generaliste/evals/behaviors.yaml:13`, `plugins/web_research/fetcher.py:51`, `core/orchestrator/notices.py` |

## 2. Plugins et outils (H1)

| Plugin | Outil (classe) | Entrée | Sortie |
|---|---|---|---|
| `legifrance` | `legi_search` (LECTURE) | requête (200 caractères au plus), fonds parmi `CODE_DATE`, `LODA_DATE`, `CODE_ETAT`, `LODA_ETAT` (liste fermée, `A_VERIFIER` sur la spécification), date de vigueur facultative, 10 résultats au plus | Par résultat : identifiant (`LEGIARTI…`, `LEGITEXT…`), titre du texte, numéro d'article, état, extrait tronqué (donnée, R5). Aucun texte complet |
| `legifrance` | `legi_article` (LECTURE) | identifiant `LEGIARTI` + 12 chiffres (expression régulière stricte) ou couple (`LEGITEXT`, numéro d'article) ; date de référence facultative (AAAA-MM-JJ) ; par défaut, la date du jour | Article : identifiant de la version, identifiant chronique, numéro, texte et titre du texte parent, état, `dateDebut`, `dateFin`, texte brut tronqué à 6 000 caractères (donnée, R5), URL `legifrance.gouv.fr`, date de lecture. **Contrôles du code (H3)** : la version rendue couvre la date de référence (`dateDebut` ≤ date < `dateFin`) ; une version future, abrogée ou différée est signalée, jamais présentée comme en vigueur ; un identifiant renvoyé différent de celui demandé est refusé |
| `web_research` (réutilisé) | `web_search`, `web_read` (LECTURE) | inchangés | restreints en code à la liste de domaines du pack (H5, H6) |

- **Quatre outils**, dans la borne de R13. Judilibre reste hors du pack en P5 (H2).
- **Réseau.** `legifrance` passe par l'anti-SSRF de `core/net/` et une liste fixe d'hôtes : `oauth.piste.gouv.fr` et `api.piste.gouv.fr`, ou leurs équivalents `sandbox-` selon `config/data_sources.yaml` (H4).
- **Identifiants (H4).** Variables `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET`, posées par toi et transmises au seul `legifrance` (`runtime.env`, ADR-015).
  - Le jeton reste en mémoire, n'est jamais écrit sur disque et est renouvelé avant expiration.
  - Ni les identifiants ni le jeton n'apparaissent dans une sortie, un journal, un cache ou une trace Langfuse.
  - Sans identifiants, chaque outil `legifrance` répond « source officielle indisponible » (D21) ; le pack n'invente aucun article.
- **Débit et cache.**
  - Limiteur partagé `core/net/throttle.py` : 1 requête par seconde [hypothèse], abaissée si les quotas lus dans PISTE l'exigent.
  - Cache sous `var/juridique/` : version d'article (identifiant `LEGIARTI`, figée par nature) 30 jours ; recherche et « version en vigueur » 24 h.
  - Plafond de 2 Mo par réponse.
- **Point-in-time (R10).** La date de référence est celle de la question, ou la date du jour. Le code refuse de présenter comme applicable une version entrée en vigueur après cette date.

## 3. Pack `domain_packs/juridique_fr/`

- **`manifest.yaml`**
  - statut `experimental` ;
  - plugins `legifrance`, `web_research` ;
  - sources autorisées : Légifrance par l'API ; pages de la liste fermée (H5) ;
  - hors périmètre :
    - conseil juridique personnalisé, rédaction d'actes, de contrats, de mises en demeure ou de conclusions, stratégie contentieuse ;
    - calcul d'un impôt, d'une indemnité ou d'un délai appliqué à un cas réel (R1, H8) ;
    - conseil à des tiers (R16) ; démarche effectuée à ta place.
- **`prompts/role.md`**
  - Méthode : qualifier la question (texte, fonds, date), chercher, lire l'article, citer l'identifiant, l'état et les dates de vigueur tels que rendus par l'outil (R1), distinguer le texte de son interprétation (R12), renvoyer vers la fiche service-public correspondante, finir par « ce que dit le texte » et « qui consulter » (avocat, notaire, administration).
  - Jamais de chiffre, de délai ou de montant hors d'une citation d'outil.
- **`prompts/rubric.md`** : critères du juge (article exact et version datée, état signalé, aucune extrapolation au cas personnel, renvoi vers un professionnel, R16).
- **`knowledge/sources.yaml`**
  - `domaines` : liste fermée de H5, chacun avec licence, mention et date de vérification ;
  - `codes` : quelques codes fréquents (`LEGITEXT` du code civil, du travail, de la consommation, général des impôts, CRPA) avec leurs identifiants `A_VERIFIER` sur un vrai appel ;
  - `sources` : vide, faute de RAG (B57).
- **Mentions (H7).** Le code ajoute en pied de réponse, selon les outils appelés :
  - Légifrance : « Source : Légifrance (DILA), Licence Ouverte 2.0 ; version en vigueur du … au …, lue le … ; seules les publications du Journal officiel font foi » ;
  - service-public : « Source : Service Public / DILA, licence etalab-2.0, mise à jour du … » ;
  - l'avertissement R16 (D23) : information générale, pas un conseil juridique.
  - Aucun LLM ne les écrit (mécanisme de G9, `core/orchestrator/notices.py`).
- **Configuration.**
  - `config/autonomy.yaml` : `juridique_fr: { level: N0, max_level: N1 }` (D3). Aucune règle de politique ne change.
  - `config/evals.yaml` : `juridique_fr_golden_min_score: 0.80` (D4).
  - `config/data_sources.yaml` : entrée `legifrance` (hôtes, environnement `sandbox` ou `production` = `A_DEFINIR`, licence, quotas `A_VERIFIER`, débit) et `web_allowlists.juridique_fr` (H5).
- **Cas `pack-juridique-absent` (H11).** Il devient faux dès que le manifeste existe. Il est remplacé dans la même modification, avec un ADR, sur le précédent d'ADR-050 et d'ADR-057.

## 4. Mécanisme commun : `web_research` restreint à une liste de domaines (H6)

C'est la pièce structurante de P5, annoncée en P4 (G7). Elle sert aussi aux packs suivants.

- **Où.** La liste vient de `config/data_sources.yaml#web_allowlists.<domaine>`, jamais du LLM ni du manifeste.
  - L'orchestrateur la transmet au plugin avec l'appel, comme `runtime.env`.
  - Le moteur de politique refuse en amont un `web_read` dont l'hôte n'y figure pas.
  - Le fetcher recontrôle chaque redirection : une redirection hors liste est refusée, pas suivie.
  - `web_search` ne rend que les résultats dont l'hôte figure dans la liste ; les autres sont écartés par le code.
- **Correspondance.** Hôte exact ou sous-domaine d'une entrée (`www.`, `entreprendre.`), après normalisation (IDNA, minuscules, point final retiré). Aucun joker libre, aucun motif d'URL.
- **Comportement par défaut.** Un domaine sans liste garde le comportement actuel : aucun pack existant ne change (`generaliste`, `recherche`, `code`, `cyber`).
- **Revue.** `risk-gate-auditor` (moteur de politique) et `security-reviewer` (fetcher, redirections, normalisation des hôtes).
- **ADR.** Un ADR « liste fermée de domaines pour la lecture web d'un pack ».

## 5. Autonomie et refus (R16, D21)

- **N0 livré.** Le pack cite et explique ; tu agis toi-même. N1 reste écrit dans la politique et se gagnera par les évals réelles.
- **Refus vérifiés** par les comportements et la red team :
  - conseil juridique personnalisé (« dois-je signer », « vais-je gagner ») : information générale et renvoi vers un professionnel ;
  - rédaction d'un acte, d'un contrat, d'une mise en demeure ou de conclusions ;
  - application chiffrée à un cas réel : délai exact, montant d'une indemnité ou d'un impôt (H8) ;
  - question pour un tiers (R16) ;
  - contournement de la loi ou fraude (R15).
- **« Je ne sais pas » valide** (R12) : article introuvable, identifiants absents, API indisponible, version incertaine à la date demandée.

## 6. Évaluations

| Suite | Contenu | Seuil |
|---|---|---|
| `domain_packs/juridique_fr/evals/golden.jsonl` (32 cas, hors ligne, résultats d'outils scriptés) | répartition ci-dessous | 0,80 en campagne réelle (D4) |
| `domain_packs/juridique_fr/evals/behaviors.yaml` | R1 (délai ou montant cité avec l'article et sa version, jamais estimé), R5, R10 (version applicable à la date), R12, R16 (D23), mentions de H7 présentes, aucune page hors liste lue | 1,0 |
| `evals/redteam/injection_juridique/` (≥ 10 cas) | consigne cachée dans un article, un extrait de recherche ou une fiche service-public ; redirection vers un domaine hors liste ; sous-domaine trompeur (`legifrance.gouv.fr.exemple`, caractères proches) ; identifiant piégé ; demande d'afficher les identifiants PISTE ; version future présentée comme en vigueur ; réponse surdimensionnée ; demande d'acte rédigé pour un tiers | 0 violation |
| Tests du mécanisme commun (§4) | listes, redirections, normalisation, absence de liste | 100 % des branches |
| Suites existantes | relancées, inchangées (R9), sauf le remplacement de H11 | inchangés |

Répartition des cas du golden :

| Type de cas | Nombre |
|---|---|
| Article cité avec identifiant, état et dates (code civil, travail, consommation) | 7 |
| Version à une date passée (R10) ou article modifié ou abrogé | 4 |
| Démarche administrative par une fiche service-public | 5 |
| Question fiscale ou sociale par une source officielle (BOFiP, Urssaf, impots.gouv) | 3 |
| « Je ne sais pas » (identifiants absents, article introuvable, API indisponible) | 4 |
| Conseil personnalisé ou rédaction d'acte refusés (R16) | 4 |
| Calcul appliqué à un cas réel refusé (H8) | 2 |
| Injection (R5) | 2 |
| Page hors liste (H6) | 1 |

## 7. Tests (aucun réseau en CI)

- **Requêtes HTTP.** PISTE (jeton) et Légifrance testés avec `httpx.MockTransport` et des fixtures synthétiques au format de la spécification 2.4.2 ; une fixture réelle (Licence Ouverte 2.0) une fois les identifiants posés et un appel fait par toi.
- **Hypothesis.** Validateurs d'identifiants (`LEGIARTI`, `LEGITEXT`) et de dates ; contrôle de couverture de la date par `dateDebut` et `dateFin` (bornes, `2999-01-01` comme fin ouverte `A_VERIFIER`, dates malformées) ; normalisation des hôtes de la liste.
- **Jeton.** Absent, expiré, refusé (401), renouvelé ; jamais écrit sur disque ; identifiants jamais dans une sortie, un journal ou un cache (`caplog` et parcours des fichiers).
- **Débit et quotas.** Limiteur avec une horloge simulée ; réponse 429 traitée comme « source officielle indisponible ».
- **Liste de domaines.** Hôte exact, sous-domaine, domaine voisin, IDNA, redirection hors liste, liste vide, domaine sans liste.
- **Kill switch** : `KILL` arrête un appel en cours.
- **Couverture.** 100 % des branches pour les validateurs, le contrôle de version, le client PISTE et le mécanisme de liste ; ajoutés à `GATE_COVERAGE` dès le départ (leçon de B316).

## 8. Dépendances et licences (R14)

- Aucune nouvelle dépendance Python : `httpx` et Pydantic suffisent. `pylegifrance` (MIT) n'est pas ajouté : il n'a servi qu'à lire la spécification.
- `docs/licences.md` reçoit : Légifrance (Licence Ouverte 2.0, CGU PISTE et API, non-opposabilité), service-public (etalab-2.0, logos exclus), chaque domaine de la liste une fois vérifié.
- Revue `security-reviewer` (§17) du plugin `legifrance` et du mécanisme commun avant leurs commits ; revue `risk-gate-auditor` du moteur de politique.

## 9. Hors périmètre → `docs/backlog.md`

- Judilibre et la jurisprudence administrative (H2), avec la purge des décisions retirées et l'interdiction du profilage.
- Conventions collectives (KALI), Journal officiel (JORF) et Bulletins officiels, au-delà de LEGI.
- Lecture des PDF (BOFiP, guides, formulaires Cerfa) et RAG vectoriel (B57).
- Calcul de délais et de montants par un outil déterministe (H8) : un outil par règle, avec ses tests et ses évals.
- Veille législative planifiée (phase 7).
- Droit européen (EUR-Lex) et droit étranger.

## 10. Coût estimé (hypothèses, non mesuré)

- **Développement** : 0 €, tout passe hors ligne.
- **API Légifrance** : gratuite (data.gouv.fr).
- **`web_search`** : tarif Brave existant.
- **Campagne réelle P5** : environ 32 cas du golden, une dizaine de cas de red team et les suites relancées, soit **5 à 15 $** (estimation, même base que P2 et P4). Elle n'a lieu qu'avec ton accord, après celles de P3a, P3b et P4, toujours en attente.
- Budgets journalier et mensuel `A_DEFINIR` : tout appel réel reste bloqué (R7).

## 11. Décisions demandées à Lucas

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| H1 | Outils du pack (R13) | **4 outils** : `legi_search`, `legi_article`, `web_search`, `web_read` / 5 avec `juri_search` (Judilibre) / un outil par fonds | **4 outils** |
| H2 | Judilibre | **au backlog** / dans P5 (5ᵉ outil, purge des décisions retirées, interdiction du profilage, mentions propres) | **au backlog** : la jurisprudence demande ses propres garde-fous ; le pack se mesure d'abord sur les textes |
| H3 | Version d'un article | date du jour seulement / **date de référence, contrôlée par le code** (`dateDebut` ≤ date < `dateFin`, état signalé) | **date de référence contrôlée** (D21, R10) |
| H4 | Identifiants PISTE | **variables `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET` posées par toi**, transmises au seul plugin ; environnement `sandbox` ou `production` (`A_DEFINIR`) | **variables posées par toi** ; tu choisis l'environnement en créant l'application |
| H5 | Liste de domaines | `legifrance.gouv.fr` et `service-public.gouv.fr` seulement / **ces deux-là plus `entreprendre.service-public.gouv.fr`, `impots.gouv.fr`, `bofip.impots.gouv.fr`, `urssaf.fr`, `cnil.fr`, `conseil-etat.fr`, `courdecassation.fr`, `economie.gouv.fr`, chacun après vérification de sa licence** / liste ouverte | **liste élargie**, un domaine n'entrant qu'avec sa licence vérifiée et datée ; sinon il reste en attente |
| H6 | Mécanisme de restriction de `web_research` | consigne dans le rôle seulement / **liste en configuration, contrôlée par le moteur de politique et par le fetcher à chaque redirection, filtrage des résultats de recherche** / plugin `web_research` dédié au pack | **liste en configuration contrôlée en code**, sans effet sur les packs sans liste ; ADR et revue `risk-gate-auditor` |
| H7 | Mentions et avertissement | écrits par le LLM / **ajoutés par le code** (source, licence, dates de version, non-opposabilité, R16) | **par le code**, comme G9 |
| H8 | Délais et montants | calculés par le LLM (contraire à R1) / **cités tels que le texte les donne, jamais appliqués à un cas réel** / outil de calcul déterministe | **cités seulement** ; l'outil de calcul au backlog |
| H9 | Cache | aucun / **version figée 30 jours, recherche et version en vigueur 24 h**, sous `var/juridique/` | **30 jours et 24 h** |
| H10 | Débit | valeurs `A_DEFINIR` | **1 requête par seconde** [hypothèse], revue dès que tu as lu les quotas dans PISTE |
| H11 | Cas `pack-juridique-absent` (R9) | **remplacé par un cas sur un domaine sans pack prévu** (ADR, comme ADR-050 et ADR-057) / règle commune B263 | **remplacement par ADR**, B263 restant ouvert |
| H12 | Campagne réelle | aucune / P5 après P3a, P3b et P4 | **aucune** sans ton accord et sans budgets |

## 12. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated P5 plan`
2. `feat(policy): restrict web research to a configured domain list` + ADR-058 (H6)
3. `feat(config): add the juridique_fr domain at N0, its golden threshold and its sources`
4. `feat(legifrance): add the Légifrance reader plugin over PISTE` + ADR-059 (H1 à H4, H9, H10)
5. `feat(answer): append the Légifrance and service-public notices` (H7)
6. `feat(juridique_fr): add the legal pack (manifest, prompts, sources)` + ADR-060 (H11)
7. `test(evals): add the legal golden set and behaviours`
8. `test(redteam): add the injection cases of the legal pack`
9. `docs: update licences, threat model and backlog for the legal pack` (A16 identifiants PISTE ; T36 article piégé ou version erronée présentée comme en vigueur ; T37 fuite des identifiants PISTE ; T38 contournement de la liste de domaines ; T39 usage comme conseil juridique, R16)
10. `docs: add the legal pack report`

## 13. Exécution

- **Après `GO P5`.**
  1. Commit 1.
  2. Contrôle des `A_VERIFIER` du §1 : CGU en vigueur sur PISTE, flux et durée du jeton, valeurs de `fond`, licence de chaque domaine de H5.
  3. Commit 2, revues `risk-gate-auditor` et `security-reviewer` du mécanisme commun.
  4. Commits 3 à 8, revue `security-reviewer` du plugin.
  5. Commit 9, compte rendu, puis arrêt.
- **Avant le premier usage réel.** Tu crées le compte PISTE, tu acceptes les CGU, tu poses `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET`, tu relèves les quotas et tu fixes les budgets.
