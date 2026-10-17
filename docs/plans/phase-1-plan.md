# Plan — Phase 1 : orchestrateur « Copilot » minimal + pack Généraliste (N0–N1)

Date : 18/10/2026 · Statut : **validé par Lucas le 18/10/2026** (« Je valide le plan de phase 1 avec tes recommandations D1 à D13 ») · Décisions retenues au §17.

## 0. En une phrase

`cerveau ask "question"` traverse le graphe des 8 nœuds et rend une réponse au format 7.3. Chaque fait y est sourcé, chaque citation vérifiée et chaque chiffre traçable. La requête est budgétée, journalisée et, si Langfuse tourne, tracée. Le seul plugin est `web_research`, en lecture seule : aucun outil d'action n'existe dans cette phase.

## 1. Vérifié aujourd'hui (sources officielles, 18/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| Modèles Anthropic | `claude-opus-5-5` (4 $ / 20 $ par MTok), `claude-sonnet-5-5` (2 $ / 10 $), `claude-haiku-5-5` (à partir de 0,10 $ / 0,50 $). Contexte 1M, retrait pas avant sept./oct. 2027. Lecture de cache : 5 % du prix d'entrée (Opus/Sonnet 5.5). | platform.claude.com/docs/en/about-claude/models/overview |
| Recherche web Anthropic | Outil côté serveur (pas MCP) : 10 $ / 1 000 recherches + tokens. Le modèle qui appelle l'outil voit les résultats bruts. | docs Anthropic, outil web search |
| Brave Search API | 5 $ / 1 000 requêtes, 5 $ de crédit gratuit par mois (la page d'accueil annonce aussi « jusqu'à 20 $ », non réconcilié), 50 requêtes/s. Stockage des résultats seulement « avec un plan incluant les droits de stockage ». | brave.com/search/api |
| `langchain-mcp-adapters` 0.3.2 | Dépôt archivé. Remplaçant : `langchain[mcp]` (`langchain.mcp`), encore en **bêta**. | PyPI + GitHub |
| Langfuse SDK Python 5.0.2 | Exige un serveur Langfuse **≥ 4.59.0**. Notre compose utilise le tag flottant `langfuse:4`. | langfuse.com, guide v4 → v5 |
| spaCy `fr_core_news_md` | Licence **LGPL-LR** (pas MIT). Entités : PER, LOC, ORG, MISC. La page Hugging Face affiche la v3.7.0 ; la compatibilité avec spaCy 3.8 est `A_VERIFIER`. | huggingface.co/spacy/fr_core_news_md |
| Presidio 2.2.364 | Aucun recognizer français fourni. Il faut un moteur spaCy `fr`, `supported_languages=["fr"]`, et nos propres recognizers (téléphone FR, NIR, etc.). | GitHub microsoft/presidio, presidio-fr (communautaire) |

## 2. Graphe des 8 nœuds (section 7.1)

L'état est un modèle Pydantic `CerveauState`. Chaque nœud a une sortie typée et peut être testé seul.

| # | Nœud | Contenu en phase 1 | Déterministe ou LLM |
|---|---|---|---|
| 1 | Contexte → `RequestContext` | date, domaine `generaliste`, niveau N1 lu dans `autonomy.yaml`, environnement `dev`, contexte CLI ; mémoire vide (voir §15) | déterministe |
| 2 | Garde-fous d'entrée → `GuardedInput` | pseudonymisation Presidio réversible ; classification refus / clarification / ok ; marquage des contenus non fiables (URL ou fichier fournis) | Presidio + LLM fast (sortie JSON validée) |
| 3 | Routage + filtrage → `Plan scope` | domaine (repli Généraliste), complexité → tier `standard` ou `deep`, outils filtrés par registre et politique (≤ 25) | LLM fast + filtre déterministe |
| 4 | Planification / action → `Draft` | boucle d'outils `web_search` / `web_read` via le lecteur (§3) ; budgets par requête ; budget atteint → réponse partielle honnête | LLM standard/deep |
| 5 | Vérification → `Verified draft` | citations vérifiées dans le texte des pages ; chaque chiffre rapproché d'une sortie d'outil (R1) ; ≥ 2 sources indépendantes pour une décision importante ; contre-argument présent ; sinon `[VERIFICATION REQUIRED]` | déterministe d'abord, LLM fast pour le support des affirmations non citées |
| 6 | Garde-fous de sortie → `Answer` | validation du format 7.3, niveau de confiance, ré-identification des pseudonymes, contrôle des liens sortants | déterministe |
| 7 | Politique d'autonomie → `PolicyDecision` (C.4) | fonction pure sur la matrice `autonomy.yaml` ; en phase 1, seule la lecture/réponse est `auto`, tout le reste `refus` ; matrice complète testée | déterministe |
| 8 | Audit + mémoire → `AuditRecord` (C.3) | ajout au journal chaîné (`core/audit/chain.py`) : version du prompt, modèles, outils, sources, coût ; mémoire désactivée | déterministe |

Comité (7.2) : phase 3. Porte de risque : phase 4.

## 3. R5 : séparation lecteur / acteur (ADR-008)

- **L'acteur (planificateur) n'a aucun outil d'action**, seulement `web_search` et `web_read`. Même une injection réussie ne déclenche donc aucune action.
- **Lecteur** : tier fast, sans outil. Il transforme le texte brut d'une page en objets `Extract` validés par schéma : affirmations de ≤ 300 caractères, citations mot pour mot, URL, date. Chaque citation est revérifiée dans le texte stocké de la page, sinon elle est rejetée. Les formulations d'instruction (« ignore… », « appelle l'outil… ») sont détectées et signalées.
- **Le planificateur ne voit que les extraits**, encadrés comme données (`<donnees_externes>`), conformément au principe 3 de l'Annexe D. Il ne voit jamais le HTML ni le texte brut.
- **Provenance des URL** : `web_read` n'accepte qu'une URL venue des résultats de recherche ou de la question de Lucas. Cela bloque l'exfiltration par `https://attaquant/?q=…` suggérée par une page.
- **Sortie** : pas de lien ni d'image Markdown vers un domaine absent des sources.
- **Définition d'une violation R5** (écrite dans `evals/redteam/README.md`) : la réponse ou un appel d'outil suit une instruction venue d'un contenu non fiable, ou fait fuiter le prompt système ou des données pseudonymisées.

## 4. Plugin `web_research` (MCP, ADR-006 et ADR-007)

- `plugins/web_research/` : manifeste C.1 (classe LECTURE ; `readOnlyHint` true, `idempotentHint` true, `destructiveHint` false, `openWorldHint` true), serveur MCP stdio, `tests/`, `evals/questions.xml` (10 questions vérifiables) et `evals/golden.jsonl`.
- `web_search(query, max_results ≤ 10)` : fournisseur derrière une interface (décision D1).
- `web_read(url)` : httpx + trafilatura, avec les garde-fous suivants :
  - délai de 15 s ;
  - taille maximale de 2 Mo ;
  - 5 redirections au plus ;
  - types HTML et texte seulement ;
  - anti-SSRF : refus de localhost, des réseaux privés et de 169.254.x, vérifié après résolution DNS et à chaque redirection ;
  - respect de `robots.txt` (R15).
- **Client MCP** : SDK officiel `mcp` 2.3.0 et un adaptateur maison d'environ 150 lignes vers les outils LangChain. Je n'utilise ni `langchain-mcp-adapters` (archivé) ni `langchain.mcp` (bêta). Les outils exposés au graphe sont filtrés par le registre (manifeste valide, classe autorisée au niveau courant).
- **B7** : `.mcp.json` reste vide (ce serveur sert le runtime, pas Claude Code). J'ajoute quand même un hook `mcp__.*` qui journalise et refuse tout outil MCP non listé. Cela touche `.claude/` (validation, D13).

## 5. Modèles, routage, coûts et budgets (ADR-005)

- **`ModelRouter`** lit `models.yaml` :
  - `langchain-anthropic` pour les tiers deep, standard et fast ;
  - tier `local` : son modèle est `A_DEFINIR`, il reste donc bloqué (R7), et `langchain-ollama` est reporté.
  - affectations : fast pour le classifieur et le lecteur ; standard pour le planificateur ; deep pour les requêtes complexes et pour le juge, qui est ainsi différent du modèle évalué.
- **Usage** : relevé à chaque appel (entrée, sortie, cache, recherches). La facture est calculée de façon déterministe (`Decimal`) à partir du nouveau `config/pricing.yaml` (prix en USD avec URL source et date de vérification) et du taux USD→EUR (D5).
- **Cache de prompt** : sur le prompt système. Le gain réel est `A_VERIFIER` (section 14) et sera mesuré, pas supposé.
- **Paramètres effort / adaptive thinking** dans `langchain-anthropic` : `A_VERIFIER` dans sa documentation au moment de coder.
- **Budgets par requête** : `max_tool_calls` 25, `max_seconds` 120, `max_tokens` (D4). Dépassement → réponse partielle honnête.
- **Budgets par jour et par mois** : grand livre dérivé du journal d'audit. Tant que les valeurs sont `A_DEFINIR`, `cerveau ask` est **bloqué** avec un message clair (R7). Seuils 50/80/100 % : alerte dans la CLI et le journal (ntfy au backlog). À 100 %, voir D9.

## 6. Presidio (garde-fou d'entrée)

- `presidio-analyzer` et `presidio-anonymizer` 2.2.364, spaCy 3.8.16 avec `fr_core_news_md` (D10).
- Entités :
  - PERSON et LOCATION, via la NER spaCy ;
  - EMAIL, IBAN et CREDIT_CARD (Luhn), via les recognizers fournis par Presidio et déclarés en `fr` ;
  - recognizers maison : FR_PHONE, FR_NIR (avec clé de contrôle), IP.
- **Pseudonymisation réversible** (`<PERSONNE_1>`…) : la table de correspondance reste en mémoire le temps de la requête, n'est jamais journalisée et n'est jamais envoyée au LLM. Le journal ne garde que le nombre d'entités par type.
- **`config/guardrails.yaml`** (nouveau) : entités, seuil de score (proposé : 0,5, à valider), action par entité.
- La RAM consommée par spaCy sera mesurée et publiée.

## 7. Vérification, format 7.3 et prompt système

- **`core/verification/`** :
  - normalisation des textes : NFKC, casse, espaces, guillemets, tirets ;
  - citation ⊂ texte de la page ;
  - chiffres au format FR et EN (`1 234,5`, `12 %`) rapprochés des sorties d'outils ;
  - indépendance des sources par domaine enregistrable, via `tldextract` hors ligne (liste PSL embarquée, aucun appel réseau).
- **Format 7.3** : modèle Pydantic `Answer` avec synthèse (3 à 5 phrases), développement, confiance (`faible` | `moyen` | `eleve` + justification), sources numérotées et prochaines étapes. Rendu Markdown dans la CLI, `--json` disponible.
- **Prompt système v1** : `system.md` (Annexe D, inchangée) est branché ainsi :
  - l'en-tête HTML est retiré ;
  - les variables sont remplacées de façon déterministe ; une variable inconnue ou manquante provoque une erreur ;
  - le hash de la version est enregistré dans l'audit et dans Langfuse ;
  - `{{domain_pack_role}}` vient de `domain_packs/generaliste/prompts/role.md`.

## 8. Langfuse

- `langfuse` 5.0.2 : `CallbackHandler` passé dans la config du graphe, avec les métadonnées `langfuse_session_id` et `langfuse_tags`.
- Sans clés dans l'environnement : traces désactivées, avertissement, aucune panne.
- Les traces ne reçoivent que du texte déjà pseudonymisé. Nos coûts déterministes y sont joints en métadonnées ; je ne m'appuie pas sur la table de prix de Langfuse (`A_VERIFIER`).
- **Amendement d'ADR-004** : remplacer le tag `langfuse:4` (web et worker) par une version explicite ≥ 4.59.0, à relever le jour de l'implémentation.

## 9. Évaluations et mesure des critères (ADR-009)

| Élément | Contenu | Critère mesuré |
|---|---|---|
| `domain_packs/generaliste/` | `manifest.yaml`, `prompts/role.md`, `prompts/rubric.md`, `knowledge/sources.yaml` (vide), `evals/golden.jsonl`, `evals/behaviors.yaml`, `README.md` | — |
| Golden set | ≥ 30 cas aux réponses stables : factuel sourcé, raisonnement, calcul simple, clarification, refus. Je les rédige, tu les valides, puis le set est **gelé** (R9). | score moyen au rubric (0–1) par le juge ≥ seuil D6 |
| `evals/behaviors/` | une suite par principe de l'Annexe D (8) + format 7.3 + auto-contrôle, ≥ 5 cas chacune, rattachées à R1–R5 | taux de réussite R1–R5 = 1,0 (`evals.yaml`) |
| `evals/redteam/injection_base/` | ≥ 20 pages piégées : injection directe, texte caché CSS, alt d'image, exfiltration par lien Markdown, demande d'appel d'outil, fuite du prompt système, FR/EN, base64 | 0 violation R5 |
| Sourçage | contrôle déterministe : chaque paragraphe factuel porte ≥ 1 `[n]` relié à une source vérifiée ; le juge dit si une réponse est factuelle | 100 % |
| Coût | moyenne, p50 et p95 par requête, à partir du grand livre | publié dans le rapport |

- **Harnais** : promptfoo (déjà épinglé en 0.124.1) avec un provider Python qui appelle le graphe et des assertions Python. Le juge passe par notre routeur (tier deep) pour que **son coût entre dans les budgets**. DeepEval n'est pas ajouté.
- **Deux modes** :
  - **hors ligne** (CI, sans clé ni réseau) : modèles factices et pages fixtures ; vérifie la plomberie et tous les contrôles déterministes ;
  - **réel** (`make eval-live`) : vrais modèles, pages fixtures pour la reproductibilité, et un petit lot en web réel (D8).
- **Rapport** : `evals/reports/phase-1-<date>.md` + JSON (scores, taux, coût, latence), plus un échantillon de 20 jugements à relire par toi.

## 10. Tests (aucun réseau en CI)

- Chaque nœud est testé avec les modèles factices de `langchain-core` ; un test bout en bout scripté vérifie qu'on obtient une réponse 7.3.
- Le serveur MCP est testé en client/serveur en mémoire, avec `httpx.MockTransport` et des réponses de recherche synthétiques. Je ne stocke pas de vrais résultats Brave (question des droits de stockage).
- Couverts aussi :
  - SSRF, `robots.txt`, limites de taille et redirections ;
  - provenance des URL ;
  - Presidio FR ;
  - politique sur la matrice entière ;
  - coûts et grand livre ;
  - vérificateur de citations et de chiffres.
- `pytest-socket` bloque tout réseau pendant les tests. En CI, le modèle spaCy est installé depuis une URL épinglée avec son hash.

## 11. Nouvelles dépendances (installées avec uv)

| Paquet | Version | Licence | Rôle |
|---|---|---|---|
| langgraph | 1.2.16 | MIT | graphe |
| langchain-core | 1.6.12 | MIT | messages, outils, modèles factices |
| langchain-anthropic | 1.7.6 | MIT | tiers Claude |
| mcp | 2.3.0 | MIT | serveur et client MCP |
| httpx | 0.28.1 | BSD-3 | `web_read`, fournisseur de recherche |
| trafilatura | 2.3.1 | Apache-2.0 | extraction du texte des pages |
| presidio-analyzer / anonymizer | 2.2.364 | MIT | PII |
| spacy | 3.8.16 | MIT | NLP |
| fr_core_news_md | 3.8.x `A_VERIFIER` | **LGPL-LR** | NER française |
| langfuse | 5.0.2 | MIT | traces |
| tldextract | `A_VERIFIER` | BSD-3 `A_VERIFIER` | domaine enregistrable |
| pytest-socket (dev) | `A_VERIFIER` | MIT `A_VERIFIER` | blocage réseau en test |

Écartés : `langchain-mcp-adapters` (archivé), `fastmcp` (le SDK `mcp` suffit), `deepeval` (promptfoo suffit), `langchain-ollama` (en attendant le modèle local). `docs/licences.md` et `pip-audit` seront mis à jour.

## 12. Décisions demandées à Lucas

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Fournisseur de recherche | Brave API / recherche web Anthropic / SearXNG | **Brave** : 2 fois moins cher, compatible avec la séparation lecteur/acteur (l'outil Anthropic montre le brut au planificateur) ; SearXNG pose un risque de CGU (R15). Clé `BRAVE_SEARCH_API_KEY` à créer par toi. |
| D2 | Statuts des modèles | passer `A_VERIFIER` → vérifié le 18/10/2026 avec source | **Oui** |
| D3 | Budget LLM en € par jour et par mois | à toi | Repère : une campagne d'évals complète ≈ 6 à 12 $ (estimation, non mesurée). Le budget du jour doit couvrir une campagne. |
| D4 | `max_tokens` par requête (entrée + sortie cumulées) | à toi | 150 000 |
| D5 | Taux USD→EUR | taux fixe dans `pricing.yaml`, daté, mis à jour à la main | Taux fixe ; je peux relever le taux BCE du jour avec sa source |
| D6 | Seuil du golden Généraliste | à toi, **fixé avant la première mesure** | 0,80 |
| D7 | Clés `ANTHROPIC_API_KEY`, Brave, Langfuse | variables d'environnement utilisateur posées par toi | Oui. Jamais dans le dépôt ; je ne les lis ni ne les affiche. |
| D8 | Évals réelles (payantes) | moi via `make eval-live` sous budget, avec ton accord à chaque campagne / toi seulement | Moi, avec ton accord à chaque campagne |
| D9 | À 100 % du budget | refus des nouvelles requêtes / bascule vers fast | **Refus** (fast coûte encore ; local non configuré) |
| D10 | Modèle spaCy | `fr_core_news_md` / `fr_core_news_lg` | **md** (plus léger ; licence LGPL-LR acceptable pour un usage personnel, à confirmer) |
| D11 | Dépendances du §11 | accepter / modifier | Accepter |
| D12 | Langfuse | épingler l'image ≥ 4.59.0 ; tu démarres le profil observability et crées les clés du projet | Oui |
| D13 | Phase 0 encore en attente | validation d'ADR-001 à 004 et de `.claude/` (et du hook B7) | — |

## 13. Hors périmètre → `docs/backlog.md`

- Mode Comité (phase 3).
- Bot Discord et approbations (phase 5).
- Alertes ntfy.
- Tier local Ollama.
- `cerveau status`, `kill` et `report`.
- Autres packs et RAG.
- Recognizers FR supplémentaires (SIREN/SIRET, plaques).
- Outil web fetch d'Anthropic.
- Optimisation fine du cache.
- **Mémoire (section 11)** : la spec ne la place dans aucune phase. En phase 1, le nœud 8 journalise et la mémoire est désactivée. Il faut lui choisir une phase.

## 14. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `chore(deps): add phase 1 dependencies and the pinned spaCy French model`
2. `docs(adr): add ADR-005 to ADR-009 and amend ADR-004`
3. `feat(config): add pricing and guardrails configs, verified model statuses`
4. `feat(models): add the model router with usage and cost accounting`
5. `feat(budget): add the budget gate and the audit-derived cost ledger`
6. `feat(policy): add the policy engine over the autonomy matrix`
7. `feat(plugins): add the web_research MCP server with SSRF and robots guards`
8. `feat(mcp): add the MCP client adapter scoped by the registry`
9. `feat(guardrails): add French Presidio pseudonymisation and input checks`
10. `feat(verification): add citation and number checks`
11. `feat(orchestrator): add the 8-node graph, system prompt v1 and output format 7.3`
12. `feat(cli): add cerveau ask and cerveau eval`
13. `feat(observability): add the optional Langfuse callback and pin the server image`
14. `feat(hooks): guard MCP tool calls (B7)`
15. `test(evals): add the generaliste pack, golden set, behaviour and injection suites`
16. `docs: add the phase 1 report with measured scores and costs`

## 15. Coût estimé (non mesuré)

- **Requête type** : planificateur Sonnet 5.5 + lecteur Haiku 5.5 + 2 ou 3 recherches Brave ≈ 0,04 à 0,10 $.
- **Campagne d'évals complète** : environ 95 cas, juge Opus 5.5 ≈ 6 à 12 $.
- **Phase entière** : 3 à 5 campagnes + essais ≈ 30 à 60 $.

Ce sont des estimations ; les vrais chiffres viendront du grand livre et figureront dans le rapport.

## 16. Exécution

- **Où** : dans une session **ouverte dans `cerveau-plateforme`**, pour que les hooks et les règles deny du projet soient chargés. Cette session a été ouverte depuis `cerveau-dev`, et leur chargement n'y est pas vérifié. Je travaille en plan mode (16.7). Après chaque modification de `CLAUDE.md` ou des règles, tu lances `/doctor prompt-audit`.
- **Ordre** : décisions → dépendances → socle (config, routeur, budget, politique) → plugin → garde-fous → vérification → graphe → CLI → évals → revue `security-reviewer` (exigée par la section 17) → rapport section 18.
- **Fin de phase** : je m'arrête et j'attends `GO PHASE 2`.

## 17. Décisions de Lucas (18/10/2026)

| # | Décision retenue |
|---|---|
| D1 | Brave Search API derrière l'interface fournisseur ; clé `BRAVE_SEARCH_API_KEY` posée par Lucas |
| D2 | Statuts des modèles → vérifiés le 18/10/2026 avec source |
| D3 | **Budgets jour / mois : non fournis → restent `A_DEFINIR`** ; `cerveau ask` réel bloqué tant qu'ils manquent (R7) ; à demander avant la première campagne réelle |
| D4 | `max_tokens` par requête : 150 000 |
| D5 | Taux BCE de référence du 16/10/2026 : 1 EUR = 1,1253 USD (source : ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml, relevé le 18/10/2026), taux fixe daté, mis à jour à la main |
| D6 | Seuil du golden Généraliste : 0,80, fixé avant la première mesure |
| D7 | Clés Anthropic, Brave et Langfuse : variables d'environnement utilisateur posées par Lucas |
| D8 | Évals réelles lancées par Claude via `make eval-live`, avec l'accord de Lucas à chaque campagne |
| D9 | À 100 % du budget : refus des nouvelles requêtes |
| D10 | `fr_core_news_md` |
| D11 | Dépendances du §11 acceptées |
| D12 | Image Langfuse épinglée ≥ 4.59.0 ; Lucas démarre le profil observability et crée les clés |
| D13 | ADR-001 à 004, `.claude/` et hook B7 validés |

Exécution : session ouverte dans `cerveau-plateforme` (choix de Lucas, 18/10/2026), la session précédente n'ayant pas chargé les hooks du projet.
