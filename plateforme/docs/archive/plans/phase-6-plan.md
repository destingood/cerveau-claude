# Plan — Phase 6 : packs P2 à P6, un par un (recherche, code, cyber, juridique, business)

Date : 21/10/2026 · Statut : **validé par l'utilisateur le 21/10/2026**, avec les recommandations D1 à D24
du §14 (D8 compris : durcissement des hooks B226 et B229).

## 0. En une phrase

Les cinq packs du §9.2 arrivent un par un, dans l'ordre de la spécification. Chacun a son manifeste, ses prompts, 3 à 5 plugins de lecture ou de calcul, un golden set d'au moins 30 cas, une suite de comportements et une red team. Chacun reste « expérimental » au niveau N0 tant qu'une campagne réelle n'a pas mesuré son golden set au-dessus de son seuil.

Ce plan couvre :
- le socle commun ;
- la dette retenue ;
- le pack P2 Recherche & veille, en détail.

P3 à P6 sont esquissés ici. Chacun recevra un complément de plan court, à valider avant de commencer (D1).

## 1. Vérifié aujourd'hui (21/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| Dépôt : routage | Le prompt de routage connaît déjà les 7 domaines. Un domaine sans pack retombe sur `generaliste`, avec une note dans la réponse. | `core/orchestrator/prompts/route.md:8`, `core/orchestrator/intake.py:221`, `core/orchestrator/answer.py:114` |
| Dépôt : packs | `PACK_IDS` est écrit en dur (`generaliste`, `finance`). Le champ `statut` des manifestes n'est lu par aucun code. Les dossiers `recherche`, `code`, `cyber`, `juridique_fr` et `business` sont vides. | `core/orchestrator/packs.py:21` |
| Dépôt : registre | `DOMAINS` accepte déjà les 7 domaines. Un pack peut lister un plugin d'un autre domaine : rien ne lie `plugin.domain` au pack. | `core/registry/manifest.py:25` |
| Dépôt : évals | Goldens et comportements sont câblés pack par pack. Les seuils n'existent que pour `generaliste` (0,80) et `finance` (0,85), avec un plancher dans le chargeur. | `core/evals/cases.py:57-66`, `core/evals/judge.py:41`, `core/config/loader.py:349` |
| Dépôt : RAG | `core/memory/` est vide. Aucun pack n'a de corpus (`sources: []`, B57). pgvector n'est prévu que dans `infra/`. | `domain_packs/generaliste/knowledge/sources.yaml` |
| gpt-researcher, STORM | Apache-2.0 et MIT. Ils servent d'inspiration seulement : aucun code n'est repris. | Annexe A.6 (vérifiée le 17/10/2026) |
| API arXiv | Métadonnées sous CC0 1.0. Une requête toutes les 3 s, une seule connexion, toutes machines confondues. Redistribuer le texte intégral demande l'accord des ayants droit. | [info.arxiv.org/help/api/tou.html](https://info.arxiv.org/help/api/tou.html) |
| OpenAlex | Clé obligatoire depuis le 13/02/2026, tarif à l'usage au-delà d'une franchise quotidienne. Montants à vérifier : `A_VERIFIER`. | [help.openalex.org, Changelog](https://help.openalex.org/hc/en-us/articles/38868153578263-Changelog) |
| Crossref, HAL | CGU de l'API et licence des résumés non vérifiées : `A_VERIFIER` au début de P2. | — |
| API Légifrance (P5) | Accès gratuit par PISTE après inscription. S'y appliquent la Licence Ouverte 2.0, les CGU de PISTE et de l'API, et des quotas, dont les valeurs sont `A_VERIFIER`. La base LEGI existe aussi en téléchargement, à une fréquence `A_VERIFIER`. | [data.gouv.fr/dataservices/legifrance](https://www.data.gouv.fr/dataservices/legifrance/), [CGU DILA (PDF)](https://piste.gouv.fr/images/cgu/DILA_Legifrance_Beta_v2.pdf), [LEGI](https://www.data.gouv.fr/fr/datasets/legi-codes-lois-et-reglements-consolides/) |
| MITRE ATT&CK (P4) | Les Terms of Use donnent une licence gratuite et non exclusive (recherche, développement, usage commercial) si la mention de copyright de MITRE est reproduite. Le type du `LICENSE.txt` d'`attack-stix-data` n'est pas identifié : `A_VERIFIER`. | [attack.mitre.org, Terms of Use](https://attack.mitre.org/resources/legal-and-branding/terms-of-use/), [github.com/mitre-attack/attack-stix-data](https://github.com/mitre-attack/attack-stix-data) |
| NVD (P4) | La clé est facultative ; sans clé, le débit est plus faible. Le produit doit afficher « non approuvé par le NVD ». Valeurs chiffrées : `A_VERIFIER`. | [nvd.nist.gov/developers/terms-of-use](https://nvd.nist.gov/developers/terms-of-use) |
| CISA KEV (P4) | CC0 selon une source secondaire seulement : `A_VERIFIER` sur la page de licence de la CISA. | [cisa.gov/known-exploited-vulnerabilities-catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) |
| Claude Agent SDK (P3) | Le dépôt est sous MIT ; l'usage relève des conditions commerciales d'Anthropic. Version courante : `A_VERIFIER` (0.2.x d'après une source tierce). | [code.claude.com/docs/en/agent-sdk](https://code.claude.com/docs/en/agent-sdk) |
| API Recherche d'entreprises (P6) | Ouverte, sans clé. Débit et licence non confirmés : `A_VERIFIER`. | [data.gouv.fr, API Recherche d'Entreprises](https://www.data.gouv.fr/dataservices/api-recherche-dentreprises/discussions) |

## 2. Périmètre (§17)

| Livrable par pack (§17) | Livré en phase 6 | Reporté |
|---|---|---|
| Manifeste | `domain_packs/<pack>/manifest.yaml` (§9.1), statut `experimental` | passage à `actif` : par toi, après une campagne réelle (D2) |
| Prompts | `role.md`, `rubric.md` (méthode, sources, R16) | — |
| 3 à 5 plugins | lecture et calcul seulement (sauf P3 : N2 local, D19). Manifeste, tests et évals pour chacun (R8) | outils d'action, veille planifiée (phase 7) |
| Golden set ≥ 30 cas | rédigé par moi, gelé après ta validation (D9). Mesuré hors ligne par les contrôles déterministes | score du juge en campagne réelle (D5) |
| Suite de comportements | `evals/behaviors.yaml` du pack (R1, R5, R12, R16 + règles du domaine), red team `evals/redteam/injection_<pack>/` | — |

Critère du §17 : « chaque pack atteint son seuil avant de passer actif ».

Sans budgets (`A_DEFINIR`) ni campagne réelle, aucun pack ne peut être mesuré, donc **aucun ne devient actif en phase 6**. Ce qui est livré :
- les packs ;
- leurs évals hors ligne, vertes ;
- la commande qui mesurera leur passage.

## 3. Socle commun des packs — ADR-043

1. **Découverte** : `load_packs()` lit tous les `domain_packs/<id>/manifest.yaml` dont l'`id` figure dans `DOMAINS`. Un dossier sans manifeste est ignoré. Un manifeste invalide bloque le démarrage, comme aujourd'hui (fail-closed).
2. **Statut** : `Pack` lit `statut` (`experimental` | `actif`). Claude Code écrit toujours `experimental` ; seul toi passes un pack à `actif` (D2).
3. **Marquage** : la réponse d'un pack expérimental porte la ligne « Pack « <id> » expérimental : sa qualité n'est pas encore mesurée. » (R12, sans chiffre pour ne pas déclencher le contrôle R1). Cela vaut aussi pour `generaliste` et `finance`, eux non plus jamais mesurés en réel (D2).
4. **Autonomie** : chaque nouveau domaine entre dans `config/autonomy.yaml` avec `level: N0` et `max_level` du §9.2 (D3). `cerveau config check` affiche, par pack, le statut, le niveau écrit et le niveau effectif.
5. **Seuils** : `config/evals.yaml` reçoit `<pack>_golden_min_score` (D4). Le chargeur pose leur plancher ; `judge.py` lit la table des packs au lieu de deux entrées en dur.
6. **Évals** : `core/evals/cases.py` découvre les goldens, comportements et red teams de chaque pack au lieu de constantes par pack. Les cas existants restent inchangés (R9).
7. **Réseau partagé** : l'anti-SSRF et robots.txt de `plugins/web_research/` (`guard.py`, `robots.py`) passent dans `core/net/`, sans changement de comportement, pour les nouveaux plugins de lecture.
8. **Agent de pack** : le champ `comite` devient le cas particulier d'un champ `agent`, l'agent long du pack (Comité pour la finance, recherche approfondie pour P2). Il ne se déclenche que sur demande explicite (D14).

## 4. Pack P2 Recherche & veille — plugins (ADR-044)

| Plugin | Outils (classe) | Sources | Garde-fous |
|---|---|---|---|
| `web_research` (réutilisé) | `web_search`, `web_read` (LECTURE) | Brave, pages publiques | inchangés |
| `scholarly` (nouveau) | `scholar_search` (requête, source `arxiv` \| `crossref`, date de début, 10 résultats au plus), `scholar_record` (DOI ou identifiant arXiv) (LECTURE) | API arXiv, API REST Crossref (D10) | 1 requête / 3 s et une connexion pour arXiv (verrou et horloge monotone). Résumés tronqués à 2 000 caractères, traités en données (R5). Aucun texte intégral téléchargé (D12) |
| `feeds` (nouveau) | `feed_read` (identifiant de flux de la liste blanche, date de début, 20 entrées au plus) (LECTURE) | flux RSS 2.0 et Atom 1.0 listés dans `knowledge/sources.yaml` (D16, D18) | parseur `defusedxml` (D17). Anti-SSRF de `core/net/`. 2 Mo et 15 s au plus. Liens des entrées ni suivis ni lus automatiquement |
| `deep_research` (nouveau, agent in-process) | aucun outil propre : appelle les trois plugins ci-dessus sous la même politique | — | §5 |

Ce pack compte 5 outils (R13). Ni OpenAlex (payant à l'usage) ni Semantic Scholar (licence d'API propre) ; HAL en option après vérification de ses CGU (D10).

## 5. Recherche approfondie — ADR-045

Inspiration : gpt-researcher (planificateur, exécutants, rédacteur) et STORM (questions sous plusieurs angles, plan avant rédaction). Aucun code repris.

1. **Plan** : le rôle `planner` propose au plus `max_sub_questions` sous-questions sous plusieurs angles (JSON validé par Pydantic) ; s'y ajoute une seule passe de reformulation.
2. **Collecte** : pour chaque sous-question, `web_search` et `scholar_search`, puis au plus `max_reads` lectures au total. Le lecteur (sans outil, R5) renvoie des extraits mot pour mot.
3. **Vérification déterministe** : chaque extrait est confronté au texte lu (`core/verification/quotes.check_quote`). Les sources sont dédoublonnées, datées et typées : préprint, article évalué, page web, flux.
4. **Rédaction** : plan, puis rapport au format de l'Annexe D. Chaque affirmation porte un renvoi `[n]`. Un chiffre n'est repris que s'il figure tel quel dans un extrait vérifié (R1 : cité, jamais calculé par le LLM).
5. **Contrôle** : une affirmation sans renvoi vérifié est retirée de la synthèse et listée sous « Points non vérifiés » (D15, R12).
6. **Bornes** : `config/budgets.yaml › per_deep_research` (`max_tokens`, `max_seconds`, `max_tool_calls` : `A_DEFINIR`, R7 ; `max_sub_questions: 5`, `max_reads: 12`, D13). Tant qu'une valeur vaut `A_DEFINIR`, une recherche réelle est bloquée, comme le Comité (ADR-028).
7. **Journal** : sous-questions, sources, extraits écartés et coût (R11).

## 6. Veille

- **À la demande** : « quoi de neuf sur <sujet> depuis <date> ». `feed_read` et `scholar_search` sont filtrés par date. Aucune entrée antérieure à la date ne passe ; le contrôle est fait par le code.
- **Liste blanche des flux** : `domain_packs/recherche/knowledge/sources.yaml` (identifiant, URL, licence, fréquence de mise à jour). Tant qu'elle est vide, `feed_read` répond « aucun flux autorisé » (D18).
- **Veille planifiée** et rapport hebdomadaire : phase 7.

## 7. Packs P3 à P6 (esquisse ; complément de plan avant chacun)

| Pack | Plugins envisagés | Autonomie | Points clés |
|---|---|---|---|
| P3 Code & DevOps | `code_repo` (git en lecture : diff, journal, fichiers d'un dépôt de la liste blanche) ; `code_checks` (ruff, pytest dans un conteneur Docker sans réseau) ; `code_ci` (état de la CI en lecture) ; `code_agent` (Claude Agent SDK dans un worktree jetable sous `var/`) | N0 → N2 au plus | D19 : branche locale et texte de PR en brouillon seulement, aucun push. Dépôts autorisés `A_DEFINIR` ; le dépôt CERVEAU en est exclu (aucune auto-modification des garde-fous). `code_agent` arrive en dernier, après ses propres évals |
| P4 Cybersécurité défensive | `cyber_cve` (NVD, KEV, EPSS) ; `cyber_attack` (bundle STIX ATT&CK local et figé) ; corpus OWASP Top 10 LLM et guides de durcissement ; `web_research` | N0 → N1 | D20 : aucun scan actif, aucun exploit, aucun lab en phase 6. Clé NVD facultative (variable d'environnement posée par toi). Licences ATT&CK, KEV, EPSS et OWASP à confirmer |
| P5 Juridique & administratif FR | `legifrance` (recherche, article par identifiant avec sa date de version) ; `web_research` limité aux domaines officiels ; Judilibre en option | N0 → N1 | D21 : interrogation de l'API officielle plutôt qu'un RAG vectoriel. Chaque article cité porte son identifiant et sa date de version, vérifiés par le code. Identifiants PISTE `A_DEFINIR` (variables d'environnement posées par toi). Aucun conseil juridique (R16) |
| P6 Business & commerce | `business_calc` (marge, point mort, prix, TVA, CAC/LTV : calcul déterministe, R1) ; `entreprises` (API Recherche d'entreprises) ; statistiques publiques (INSEE ou Eurostat, `A_VERIFIER`) ; `web_research` | N0 → N1 | D22 : communications en brouillon seulement, aucune publication |

## 8. Dette du backlog incluse (lot 6.0, avant P2, D6)

| Entrée | Correction |
|---|---|
| B227 | aide de la CLI en UTF-8 dans un pipe (ou flèche retirée) |
| B233 | lecture bornée des rapports de promotion avant le SHA-256 |
| B236 | `send_approved` refuse une demande dont l'environnement n'est pas `paper` |
| B237 | borne haute de `execution_incidents_max` |
| B238 | un second `engage` du kill switch refuse aussi les demandes ouvertes |
| B239 | `_sign` sort de `core/` (vers `tests/`) |
| B240 | signature datée dans le futur ou avant son rapport : ignorée |
| B241 | `core/policy/` dans la porte de couverture à 100 % |
| B246 | cash en mode `cent` arrondi vers le bas (D7) |
| B215, B232 | `/status` ouvre ses registres en lecture seule |
| B209 | durée de `/kill` mesurée avant l'envoi des alertes |
| B210, B211 | nettoyages mineurs de l'API |
| B226, B229 | **seulement avec ton accord** (durcissement des hooks, D8) |

Les autres entrées marquées « 6 » passent en phase 7, sauf avis contraire.

## 9. Évaluations (P2)

| Suite | Contenu | Seuil |
|---|---|---|
| `domain_packs/recherche/evals/golden.jsonl` (≥ 30 cas, hors ligne, résultats scriptés) | voir la répartition ci-dessous | `recherche_golden_min_score` (D4), en campagne réelle seulement |
| `domain_packs/recherche/evals/behaviors.yaml` | R1, R5, R12 et R16. Règles du domaine : un renvoi par affirmation, la date de chaque source, la mention « préprint », aucun texte intégral payant | taux de réussite 1,0 (R1 à R5) |
| `evals/redteam/injection_recherche/` (≥ 10 cas) | consignes cachées dans un résumé, un titre de flux ou une page ; lien interne dans un flux (SSRF) ; requête qui répète une donnée privée | 0 violation |
| Suites existantes | relancées, inchangées (R9) | inchangés |

Répartition des cas du golden :

| Type de cas | Nombre |
|---|---|
| Synthèse multi-sources citée | 8 |
| Sources contradictoires | 4 |
| Veille datée | 4 |
| Préprint ou rétractation | 3 |
| « Je ne sais pas » | 3 |
| Injection | 3 |
| Texte intégral payant (R15) | 2 |
| Chiffres cités (R1) | 2 |
| Conseil à un tiers (R16) | 1 |
| Recherche approfondie scriptée | 4 |

## 10. Tests (aucun réseau en CI)

- arXiv, Crossref et flux : `httpx.MockTransport`. Fixtures réelles anonymisées, de quelques Ko.
- Parseur de flux : Hypothesis (XML malformé, entités externes et « billion laughs » refusés, dates manquantes ou fausses).
- Limiteur de débit arXiv : horloge simulée.
- Recherche approfondie : LLM scripté, comme pour le Comité. Cas couverts : bornes atteintes, affirmation non vérifiée retirée, budget `A_DEFINIR` qui bloque.
- Socle : découverte des packs (dossier vide, `id` divergent, manifeste invalide), marquage du statut, seuils au plancher.
- Couverture à 100 % pour `core/net/` et le moteur de recherche approfondie.

## 11. Nouvelles dépendances

| Paquet | Usage | Licence |
|---|---|---|
| `defusedxml` | parseur de flux sûr | PSF-2.0 attendue, `A_VERIFIER` avant l'ajout. Revue `security-reviewer` |

Aucune autre pour P2 : arXiv et Crossref passent par `httpx`, déjà présent.

## 12. Hors périmètre → `docs/backlog.md`

- veille planifiée et rapport hebdomadaire (phase 7) ;
- RAG vectoriel (pgvector, B57) ;
- ingestion de PDF (docling) ;
- OpenAlex et Semantic Scholar ;
- labs de cybersécurité ;
- audit local de la machine ;
- push et PR réelles du pack Code ;
- passage d'un pack à `actif`.

## 13. Coût estimé (non mesuré)

- **Développement** : 0 € d'API, tout passe hors ligne.
- **arXiv, Crossref, flux** : 0 €.
- **Campagne réelle P2** : environ 30 cas du golden, une dizaine de cas de red team et les suites relancées, soit **5 à 15 $** (estimation). Une recherche approfondie réelle coûterait entre quelques dizaines de centimes et 2 $ (estimation). Les deux n'ont lieu qu'avec ton accord et les budgets fixés.

## 14. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Découpage | tout d'un bloc / pack par pack avec complément validé / sans arrêt | **Pack par pack**, dans l'ordre du §9.2 : lot 6.0, P2, puis P3 à P6. Avant chaque pack, un complément de plan court (« GO P3 », etc.) ; après chacun, un compte rendu bref. Compte rendu §18 et arrêt à la fin de P6 |
| D2 | Statut des packs | aucun effet / marquage dans la réponse / plafond N0 dans le code | **Marquage** de tout pack expérimental, `generaliste` et `finance` compris (R12). Pas de plafond dans le code : D3 suffit. `actif` est écrit par toi seul, après une campagne réelle au-dessus du seuil |
| D3 | Niveau initial des nouveaux domaines | niveau du §9.2 / N0 | **`level: N0`**, `max_level` du §9.2 (N1 ; N2 pour `code`). Tu montes le niveau toi-même |
| D4 | Seuils des goldens (§9.3), fixés avant toute mesure | `A_DEFINIR` / valeurs | **0,80** pour `recherche`, `code`, `cyber` et `business` ; **0,85** pour `juridique_fr`, où une erreur coûte plus. Ce sont des planchers |
| D5 | Mesure réelle | campagne par pack / aucune | **Aucune sans ton accord et sans budgets** ; les packs restent expérimentaux en fin de phase |
| D6 | Dette | lot du §8 / rien | **Lot du §8** en tête de phase ; le reste en phase 7 |
| D7 | B246 | arrondi au plus proche documenté / vers le bas | **Vers le bas** : le cash n'est jamais surévalué |
| D8 | B226 et B229 (hooks) | durcir / laisser | **Durcir** : `var/promotion/` et `interfaces/discord_bot/package.json` protégés en écriture. Il faut ton accord explicite, car les hooks changent |
| D9 | Goldens et revues | sous-agents / dans la session | **Dans la session**, sans `eval-engineer` ni `source-verifier` (coût). Je rédige les cas, tu les valides au compte rendu du pack, puis ils sont gelés. Une revue `security-reviewer` par pack, limitée à son diff, plus `risk-gate-auditor` pour le socle (autonomie) |
| D10 | Sources académiques | arXiv + Crossref / + HAL / + OpenAlex | **arXiv + Crossref**, après vérification des CGU de Crossref. HAL si ses CGU le permettent. OpenAlex exclu (payant à l'usage) |
| D11 | Contact Crossref (« polite pool » par adresse e-mail) | ton adresse / aucune | **Aucune** : pool public, plus lent, mais aucune donnée personnelle envoyée |
| D12 | Texte intégral | métadonnées et résumés / PDF | **Métadonnées et résumés**, plus les pages HTML via `web_read`. PDF au backlog |
| D13 | Bornes de la recherche approfondie | valeurs | **5 sous-questions, 12 lectures**. Jetons, secondes et appels : `A_DEFINIR` (tu les fixes) |
| D14 | Déclenchement de l'agent de pack | choix du routeur / explicite | **Explicite** : `cerveau ask --approfondi`. Le prompt de routage ne change pas, et tu maîtrises le coût |
| D15 | Affirmation non vérifiée | gardée et marquée / retirée et listée | **Retirée** de la synthèse et listée sous « Points non vérifiés » |
| D16 | Flux | liste blanche / toute URL | **Liste blanche** (sources autorisées du §9.1) |
| D17 | Parseur de flux | `feedparser` / `defusedxml` et code maison | **`defusedxml`** : surface réduite, sûr face à XXE, petit parseur RSS et Atom testé par Hypothesis |
| D18 | Flux initiaux | vide / proposés | **Vide**. Tu donnes tes sujets de veille ; je propose les flux vérifiés au compte rendu de P2 |
| D19 | Périmètre de P3 | complet / progressif | **Progressif** : `code_repo`, `code_checks` et `code_ci` d'abord, puis `code_agent` (Docker sans réseau, worktree jetable, liste blanche de dépôts, CERVEAU exclu, aucun push) |
| D20 | Périmètre de P4 | avec labs / sans | **Sans labs ni scan actif** en phase 6 |
| D21 | Accès aux textes en P5 | API Légifrance / base LEGI téléchargée / RAG vectoriel | **API Légifrance** : texte à jour, identifiant et date de version. Tu crées le compte PISTE et poses les variables ; sans elles, le pack répond « source officielle indisponible » |
| D22 | Communications en P6 | brouillon / envoi | **Brouillon seulement** (N1, §9.2) |
| D23 | Avertissement R16 | dans le rôle / dans le rôle et vérifié | **Vérifié** par la suite de comportements de chaque pack (juridique, cyber, business, finance déjà fait) |
| D24 | Décisions encore ouvertes de la phase 5 (§7 du compte rendu) | bloquantes / non | **Non bloquantes** pour la phase 6, sauf les budgets, sans lesquels aucune mesure réelle n'est possible |

## 15. Commits atomiques (lot 6.0 et P2 ; en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated phase 6 plan`
2. de 8 à 12 commits `fix:` et `test:` pour le lot 6.0 (un par entrée ou par paire liée)
3. `refactor(net): move the SSRF guard and robots.txt to core/net`
4. `feat(packs): discover the domain packs and mark the experimental ones` + ADR-043
5. `feat(config): add the recherche domain at N0 and its golden threshold`
6. `feat(evals): load the golden sets, behaviours and red teams of every pack`
7. `feat(scholarly): add the arXiv and Crossref reader plugin` + ADR-044
8. `feat(feeds): add the allow-listed RSS and Atom reader plugin`
9. `feat(deep_research): add the deep research agent with verified citations` + ADR-045
10. `feat(recherche): add the recherche pack (manifest, prompts, sources)`
11. `test(evals): add the recherche golden set and behaviours`
12. `test(redteam): add the injection cases of the recherche pack`
13. `docs: update licences, threat model and backlog for the recherche pack`
14. `docs: add the recherche pack report`

## 16. Exécution

- **Où** : dans cette session, dans `cerveau-plateforme`, sur la branche locale. Aucun push.
- **Ordre** :
  1. tes décisions ;
  2. documentation à jour (API arXiv, API REST Crossref et ses CGU, `defusedxml`) ;
  3. lot 6.0 ;
  4. socle et ADR-043 ;
  5. plugins de P2 ;
  6. recherche approfondie ;
  7. pack ;
  8. évals ;
  9. revues (D9) ;
  10. compte rendu de P2 ;
  11. complément de plan de P3, puis arrêt jusqu'à ton GO.
- **Fin de phase** : après P6, compte rendu §18 ; j'attends `GO PHASE 7`.
