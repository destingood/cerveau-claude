# Complément de plan — Phase 6, pack P4 Cybersécurité défensive

Date : 22/10/2026 · Statut : **validé** le 27/10/2026 (`GO P4`, recommandations G1 à G12 ; l'utilisateur
lance lui-même `cerveau cyber attack-fetch`, G5).

Complément au plan de phase 6 (`docs/plans/phase-6-plan.md`, §7, D20). Tout ce qui n'est pas repris
ici suit ce plan : domaine `cyber` en N0 et `max_level` N1 (D3), seuil du golden 0,80 (D4), aucune
mesure réelle sans ton accord et sans budgets (D5), revues dans la session (D9), avertissement R16
vérifié par les comportements (D23), aucun lab ni scan actif (D20).

## 0. En une phrase

Le pack `cyber` répond aux questions de veille de vulnérabilités, de priorisation des correctifs,
de cartographie ATT&CK et de durcissement. Il cite les fiches du NVD, le catalogue KEV de la CISA et
les scores EPSS, lus par `cyber_cve`, ainsi qu'une copie locale et figée d'ATT&CK, lue par
`cyber_attack`. Les guides officiels passent par `web_research`. Aucun outil ne touche un système, ne
prend une adresse cible et ne produit de code offensif (R15).

## 1. Vérifié aujourd'hui (22/10/2026)

| Fait | Source |
|---|---|
| **Conditions du NVD.** L'API sert à « search, display, analyze, retrieve, view » les données du NVD. Le service doit afficher en évidence : « This product uses the NVD API but is not endorsed or certified by the NVD. » Sans clé, les limites publiques s'appliquent. La clé est personnelle et ne se partage pas. Un contenu modifié ne s'attribue pas au NVD | nvd.nist.gov/developers/terms-of-use (lue dans le navigateur) |
| **Débit du NVD.** 5 requêtes par 30 s glissantes sans clé, 50 avec clé ; une pause entre deux requêtes est conseillée même avec clé. Source secondaire : la page officielle, rendue en JavaScript, n'a pas pu être lue (`A_VERIFIER`) | résultat de recherche citant nvd.nist.gov/developers/start-here |
| **Format du NVD** (essai du jour sur `services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2021-44228`). Réponse `NVD_CVE` 2.0. Champs : `cisaExploitAdd`, `cisaActionDue`, `cisaRequiredAction`, `weaknesses`, `metrics` (`cvssMetricV31`, `cvssMetricV2`, `ssvcV203`), `affected`, `references`. Fiche de 87 Ko. L'en-tête `apiKey` figure dans `access-control-allow-headers` | essai direct |
| **Limites des requêtes NVD.** 2 000 résultats par page et plage de dates de 120 jours au plus. Source secondaire (`A_VERIFIER`) | documentation de clients tiers |
| **CISA KEV.** Flux JSON `cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`, modifié le 21/10/2026. Licence **CC0 1.0** : ni le logo ni un aval de la CISA ou du DHS. Champs : `catalogVersion`, `dateReleased`, `count`, puis par entrée `cveID`, `vendorProject`, `product`, `vulnerabilityName`, `dateAdded`, `shortDescription`, `requiredAction`, `dueDate`, `knownRansomwareCampaignUse`, `notes`, `cwes`. Le CC0 lève l'`A_VERIFIER` du plan de phase 6 | cisa.gov/known-exploited-vulnerabilities-catalog, `…/licenses/kev/license.txt`, schéma JSON du flux |
| **EPSS.** Scores publiés librement, sans inscription ; « Attribution is requested » dans les publications ou produits. API `api.first.org/data/v1/epss?cve=` (essai : `cve`, `epss`, `percentile`, `date`). Scores produits par Empirical Security. Aucun débit publié trouvé (`A_VERIFIER`) | first.org/epss/faq, essai direct |
| **Licence d'ATT&CK.** Licence non exclusive et gratuite pour la recherche, le développement et l'usage commercial. Toute copie reproduit la mention « © 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation. » ainsi que la licence. Le `LICENSE.txt` d'`attack-stix-data` est cette même licence, propre à MITRE (ni Apache ni CC) : l'`A_VERIFIER` du plan de phase 6 est levé. ATT&CK est une marque déposée | attack.mitre.org/resources/legal-and-branding/terms-of-use/, `attack-stix-data/LICENSE.txt` |
| **Données d'ATT&CK.** Version courante **v20.0**, du 13/10/2026. Le dépôt ne fournit que du STIX 2.1. `enterprise-attack/enterprise-attack-20.0.json` pèse 55 271 014 octets | attack.mitre.org/resources/versions/, en-têtes HTTP du fichier |
| **OWASP Top 10 for LLM Applications 2025** (LLM01 à LLM10). Une page HTML par risque, `genai.owasp.org/llmrisk/<slug>/`. Licence du site : CC BY-SA 4.0, « unless otherwise specified » | genai.owasp.org/llm-top-10/ |
| **Guides de l'ANSSI.** Licence Ouverte 2.0 d'Etalab : paternité et date de mise à jour à citer. Source secondaire : `A_VERIFIER` guide par guide. La plupart sont des PDF, que `web_read` ne lit pas (`text/html` et `text/plain` seulement) | cyber.gouv.fr (guides cités), `plugins/web_research/fetcher.py:51` |
| **Conditions du programme CVE** (descriptions reprises par le NVD). Page non lue, car rendue en JavaScript : `A_VERIFIER` | cve.org/Legal/TermsOfUse |
| **Dépôt.** `cyber` figure déjà dans `DOMAINS`. `domain_packs/cyber/` est vide. Le cas `pack-cyber-absent` attend l'absence du pack. Le limiteur de débit partagé existe | `core/registry/manifest.py:26`, `domain_packs/generaliste/evals/behaviors.yaml:54`, `core/net/throttle.py` |

## 2. Plugins et outils (G1)

| Plugin | Outil (classe) | Entrée | Sortie |
|---|---|---|---|
| `cyber_cve` | `cve_lookup` (LECTURE) | 1 à 10 identifiants `CVE-AAAA-NNNN…` (expression régulière stricte) | Par CVE : statut NVD, dates de publication et de modification, description tronquée à 2 000 caractères (donnée, R5), CVSS v4.0 / v3.1 tel que publié (score de base, vecteur, source NVD ou CNA), CWE, SSVC s'il est publié, 10 références au plus. Statut KEV : date d'ajout, échéance, action requise, usage par un rançongiciel. EPSS : score, centile, date. Tri déterministe (G8). Date de lecture de chaque source |
| `cyber_cve` | `cve_watch` (LECTURE) | `source` (`kev` ou `nvd`), date de début, mot-clé facultatif (100 caractères au plus), 20 résultats au plus | KEV : entrées ajoutées depuis la date, filtrées par éditeur ou produit. NVD : CVE publiées dans la plage (120 jours au plus), par mot-clé ou par la liste `produits_suivis` (G10). Aucune entrée antérieure à la date ; le contrôle est fait par le code |
| `cyber_attack` | `attack_lookup` (LECTURE) | identifiant ATT&CK (`T1059`, `T1059.001`, `TA0002`, `M1038`, `G0016`, `S0154`, …) ou mots-clés, 10 résultats au plus | Objet : nom, description tronquée, tactiques, plateformes, détection, atténuations liées, sous-techniques ; version du bundle et URL attack.mitre.org. Objets révoqués et dépréciés signalés, jamais présentés comme courants |
| `web_research` (réutilisé) | `web_search`, `web_read` (LECTURE) | inchangés | inchangés (G7) |

- **Cinq outils**, dans la borne de R13.
- **Aucune entrée** n'accepte d'hôte, d'adresse IP, de port ou d'URL cible.
- **Réseau.** Les deux plugins passent par l'anti-SSRF de `core/net/` et par une liste fixe d'hôtes : `services.nvd.nist.gov`, `www.cisa.gov`, `api.first.org`. `cyber_attack` n'appelle aucun réseau : il lit un index local.
- **Débit et cache (G4).** Le limiteur partagé `core/net/throttle.py` règle le débit. Le cache vit sous `var/cyber/` : fiche NVD et EPSS 24 h, flux KEV 24 h. Plafonds de taille : 2 Mo par réponse NVD ou EPSS, 10 Mo pour le flux KEV (taille réelle `A_VERIFIER`).
- **Clé NVD (G3).** Variable `NVD_API_KEY`, posée par toi et transmise au seul `cyber_cve` (`runtime.env`, ADR-015). Elle part dans l'en-tête `apiKey` et n'apparaît jamais dans une sortie, un journal ou un cache. Sans elle, le débit public s'applique.
- **ATT&CK (G5).** La commande `cerveau cyber attack-fetch --version 20.0` lit `enterprise-attack-20.0.json` à une URL figée sur un commit du dépôt `attack-stix-data`. Elle refuse au-delà de 80 Mo et inscrit le SHA-256 dans `config/data_sources.yaml`. Elle construit un index compact sous `var/cyber/attack/` avec `json` et Pydantic, sans nouvelle dépendance. Le bundle n'entre jamais dans git. Une empreinte différente bloque le plugin, qui répond « bundle ATT&CK absent ou altéré ». Seul le domaine Enterprise est couvert.

## 3. Pack `domain_packs/cyber/`

- **`manifest.yaml`**
  - statut `experimental` ;
  - plugins `cyber_cve`, `cyber_attack`, `web_research` ;
  - sources autorisées :
    - NVD, KEV et EPSS par `cyber_cve` ;
    - ATT&CK v20.0 local ;
    - pages publiques par `web_research` ;
  - hors périmètre :
    - scan, exploit, preuve de concept, lab, contournement de détection, audit de la machine ;
    - conseil à des tiers.
- **`prompts/role.md`**
  - Méthode : identifier la CVE ou la technique, citer les champs des outils (R1), dater chaque fait (R10, R12), privilégier l'avis de l'éditeur et les guides officiels, finir par des actions défensives sur les systèmes de l'utilisateur.
  - Une demande offensive reçoit un refus et une alternative défensive (R15, D20).
- **`prompts/rubric.md`** : critères du juge (exactitude citée, dates, priorisation expliquée par la règle de G8, refus offensif, R16).
- **`knowledge/sources.yaml`** :
  - `guides` : pages HTML officielles, chacune avec URL, licence et date (G6). On y trouve les 10 pages OWASP LLM 2025, et les pages ANSSI, CISA et NIST CSRC une fois leur licence vérifiée ;
  - `produits_suivis` : vide (G10) ;
  - `sources` : vide, faute de RAG (B57).
- **Mentions (G9).** Le code ajoute en pied de réponse la mention de chaque source appelée : texte exact du NVD, copyright MITRE, attribution EPSS (FIRST), CC0 de la CISA sans aval, CC BY-SA 4.0 d'OWASP. Aucun LLM ne les écrit.
- **Configuration.**
  - `config/autonomy.yaml` : `cyber: { level: N0, max_level: N1 }` (D3). C'est le même schéma que `code` en P3a ; aucune règle de politique ne change.
  - `config/evals.yaml` : `cyber_golden_min_score: 0.80` (D4).
  - `config/data_sources.yaml` : entrées `nvd`, `cisa_kev`, `epss`, `attack`, avec URL, licence et débit. Le SHA-256 vaut `A_VERIFIER` jusqu'au premier `attack-fetch`.
- **Cas `pack-cyber-absent` (G11).** Il devient faux dès que le manifeste existe. Il est remplacé dans la même modification, avec un ADR, sur le précédent d'ADR-050.

## 4. Autonomie et refus (D20, R15)

- **N0 livré.** Le pack analyse, cite et propose des actions que tu exécutes. N1 reste écrit dans la politique et se gagnera par les évals réelles.
- **Refus vérifiés** par les comportements et la red team :
  - écriture ou adaptation d'un exploit, d'une preuve de concept ou d'un logiciel malveillant ;
  - scan ou test d'un système, même déclaré à toi : aucun outil ne le permet en phase 6 ;
  - contournement d'un antivirus ou d'un EDR ;
  - recherche de cibles vulnérables.

## 5. Évaluations

| Suite | Contenu | Seuil |
|---|---|---|
| `domain_packs/cyber/evals/golden.jsonl` (31 cas, hors ligne, résultats d'outils scriptés) | répartition ci-dessous | 0,80 en campagne réelle (D4) |
| `domain_packs/cyber/evals/behaviors.yaml` | R1 (score CVSS ou EPSS cité avec son outil et sa date, jamais estimé), R5, R12, R15 (refus offensif avec alternative), R16 (D23), mentions de G9 présentes | 1,0 |
| `evals/redteam/injection_cyber/` (≥ 10 cas) | consigne cachée dans une description de CVE, une note KEV, une page de guide ou un objet ATT&CK ; bundle altéré (empreinte) ; identifiant piégé (chemin, caractères proches) ; demande d'afficher `NVD_API_KEY` ; référence NVD vers une adresse interne (SSRF) ; réponse surdimensionnée ; exploit demandé pour une CVE du KEV | 0 violation |
| Suites existantes | relancées, inchangées (R9), sauf le remplacement de G11 | inchangés |

Répartition des cas du golden :

| Type de cas | Nombre |
|---|---|
| Fiche CVE citée (CVSS, KEV, EPSS, dates) | 6 |
| Priorisation de plusieurs CVE (G8) | 3 |
| Veille KEV ou NVD datée | 4 |
| Cartographie ATT&CK (technique, atténuations, détection) | 5 |
| Durcissement ou OWASP LLM par sources officielles | 4 |
| « Je ne sais pas » (CVE inconnue ou rejetée, NVD indisponible, bundle absent) | 3 |
| Demande offensive refusée (R15, D20) | 3 |
| Injection (R5) | 2 |
| Conseil à un tiers (R16) | 1 |

## 6. Tests (aucun réseau en CI)

- **Requêtes HTTP.** NVD, KEV et EPSS sont testés avec `httpx.MockTransport` et de petites fixtures réelles : un extrait du KEV (CC0) et une fiche NVD réduite. Pour la fiche NVD, les conditions du programme CVE sont `A_VERIFIER`, sinon on utilise une fiche synthétique.
- **ATT&CK.** Un bundle STIX synthétique de quelques Ko : objets révoqués, dépréciés, relations, chaînes géantes.
- **Hypothesis.** Validateurs d'identifiants CVE et ATT&CK ; analyse du bundle et des réponses (JSON malformé, champs manquants, dates fausses).
- **Débit.** Limiteur testé avec une horloge simulée, avec et sans clé.
- **Clé.** Absente ou présente ; jamais dans une sortie, un journal ou un cache (`caplog` et parcours des fichiers).
- **Empreinte, taille, kill switch.** Une empreinte différente bloque ; un dépassement de taille est refusé ; `KILL` arrête `attack-fetch`.
- **Couverture.** 100 % des branches pour les validateurs, les analyseurs et le tri de G8.

## 7. Dépendances et licences (R14)

- Aucune nouvelle dépendance Python : `httpx` et Pydantic sont déjà présents. Le STIX est lu en JSON, sans `stix2` ni `mitreattack-python`.
- `docs/licences.md` reçoit :
  - NVD (conditions, mention) et CVE (`A_VERIFIER`) ;
  - KEV (CC0 1.0) et EPSS (attribution demandée) ;
  - ATT&CK (licence MITRE, copyright reproduit dans l'index local et les réponses) ;
  - OWASP (CC BY-SA 4.0 : citation et lien, aucun contenu adapté stocké).
- Revue `security-reviewer` (§17) des deux plugins et de la commande `attack-fetch` avant leurs commits.

## 8. Hors périmètre → `docs/backlog.md`

- Labs, scans actifs, audit local de la machine (D20).
- ATT&CK Mobile et ICS, D3FEND, règles Sigma.
- Lecture des guides en PDF (ANSSI, NIST) et RAG vectoriel (B57).
- Veille planifiée et alertes (phase 7).
- Rapprochement automatique d'un inventaire logiciel avec les CPE.
- Calcul local d'un score CVSS depuis un vecteur.
- Restriction en code de `web_read` à une liste de domaines (mécanisme commun prévu en P5).

## 9. Coût estimé (hypothèses, non mesuré)

- **Développement** : 0 €, tout passe hors ligne.
- **NVD, KEV, EPSS, ATT&CK** : gratuits.
- **`web_search`** : tarif Brave existant.
- **Campagne réelle P4** : environ 31 cas du golden, une dizaine de cas de red team et les suites relancées, soit **5 à 15 $** (estimation, même base que P2). Elle n'a lieu qu'avec ton accord, après celles de P3a et P3b, toujours en attente.
- Budgets journalier et mensuel `A_DEFINIR` : tout appel réel reste bloqué (R7).

## 10. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| G1 | Outils du pack (R13) | **5 outils** : `cve_lookup`, `cve_watch`, `attack_lookup`, `web_search`, `web_read` / 7 outils (KEV, EPSS et recherche ATT&CK séparés, exception à R13) | **5 outils** |
| G2 | Source du statut KEV | **flux de la CISA** (CC0, notes, usage par rançongiciel, veille par date) / champs `cisa*` des fiches NVD seulement | **flux de la CISA**, mis en cache 24 h |
| G3 | Clé NVD | aucune / **facultative** (`NVD_API_KEY` posée par toi) / obligatoire | **facultative** ; sans elle, débit public |
| G4 | Débits | valeurs `A_DEFINIR` | NVD : 1 requête par 6 s sans clé, 1 par 0,6 s avec clé (sous les 5 et 50 par 30 s, `A_VERIFIER`). EPSS : 1 par seconde [hypothèse]. KEV : 1 lecture par 24 h |
| G5 | Copie d'ATT&CK (55 Mo) | dans git (non : taille, licence à reproduire) / téléchargée par toi à la main / **commande `cerveau cyber attack-fetch`**, URL figée sur un commit, SHA-256 consigné / bibliothèque `mitreattack-python` | **commande**, lancée par toi. Je ne la lance moi-même que si ton GO le dit (fichier `enterprise-attack-20.0.json`, GitHub `mitre-attack/attack-stix-data`, 55 Mo) |
| G6 | Guides et OWASP LLM | corpus local figé (PDF : parseur à ajouter) / **liste de pages officielles dans `knowledge/sources.yaml`, lues à la demande par `web_read`** / RAG (B57) | **liste de pages**, sans stockage ; PDF au backlog |
| G7 | Lecture web du pack | **inchangée** (anti-SSRF, R5 ; le rôle privilégie l'éditeur et les sources officielles) / restreinte en code à une liste de domaines (moteur de politique, revue `risk-gate-auditor`) | **inchangée** en P4 : une liste stricte bloquerait les avis d'éditeurs cités par le NVD. Le mécanisme commun se construit en P5 (D21) |
| G8 | Priorisation (R1) | laissée au LLM (contraire à R1) / **tri déterministe documenté, sans seuil** : KEV d'abord, puis EPSS, CVSS de base, identifiant / score composite à seuils (`A_DEFINIR`) | **tri déterministe**, rendu par `cve_lookup` et cité avec sa règle |
| G9 | Mentions de source | écrites par le LLM / **ajoutées par le code** selon les outils appelés, vérifiées par les comportements | **par le code** |
| G10 | Produits suivis pour la veille | aucune liste / **liste `produits_suivis` vide, remplie par toi** (noms de logiciels envoyés au NVD comme mots-clés, rien d'autre) | **liste vide** remplie par toi |
| G11 | Cas `pack-cyber-absent` (R9) | **remplacé par un cas sur un domaine sans pack prévu** (ADR, comme ADR-050) / règle commune B263 | **remplacement par ADR**, B263 restant ouvert |
| G12 | Campagne réelle | aucune / P4 après P3a et P3b | **aucune** sans ton accord et sans budgets |

## 11. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated P4 plan`
2. `feat(config): add the cyber domain at N0, its golden threshold and its data sources`
3. `feat(cyber_cve): add the NVD, KEV and EPSS reader plugin` + ADR-055 (G1 à G4, G8)
4. `feat(cyber_attack): add the frozen ATT&CK reader and its fetch command` + ADR-056 (G5)
5. `feat(answer): append the notices required by the sources used` (G9)
6. `feat(cyber): add the cyber pack (manifest, prompts, sources)` + ADR-057 (G11)
7. `test(evals): add the cyber golden set and behaviours`
8. `test(redteam): add the injection cases of the cyber pack`
9. `docs: update licences, threat model and backlog for the cyber pack` (T33 bundle empoisonné, T34 usage offensif, T35 fuite de la clé NVD)
10. `docs: add the cyber pack report`

## 12. Exécution

- **Après `GO P4`.**
  1. Commit 1.
  2. Contrôle des `A_VERIFIER` du §1 : débits officiels du NVD, conditions du programme CVE, débit d'EPSS, taille du flux KEV, types d'objets STIX de la v20.0.
  3. Commits 2 à 8.
  4. Revue `security-reviewer`.
  5. Commit 9, compte rendu, puis arrêt.
- **Avant le premier usage réel.** Tu poses `NVD_API_KEY` si tu le souhaites, tu lances `cerveau cyber attack-fetch`, tu remplis `produits_suivis` et tu fixes les budgets.
