# Plan — Phase 5 : supervision et activation contrôlée (N3) : bot Discord, approbations, adaptateur live désactivé, rapport de promotion, dashboard

Date : 21/10/2026 · Statut : **validé par l'utilisateur le 21/10/2026**, avec les recommandations D1 à D26 du §14.

## 0. En une phrase

Une action financière en N3 attend ton approbation, une par une : un bouton Discord, puis un code à usage unique d'une application d'authentification, lié à une intention précise et valable quelques minutes. Une approbation expirée vaut refus, et tout passe au journal. Un adaptateur live existe, mais il refuse de démarrer tant que tu n'as pas fait toi-même chacune des actions manuelles requises ; un test le prouve pour toutes les combinaisons. `/kill` et `/status` passent aussi par Discord, les alertes par ntfy. Un rapport de promotion se génère tout seul, mais tu le signes à la main. Un dashboard local en lecture seule complète le tout. Claude Code n'active rien et ne se connecte à aucun service.

## 1. Vérifié aujourd'hui (21/10/2026)

| Sujet | Constat | Source |
|---|---|---|
| discord.js | 14.27.0, Apache-2.0, Node ≥ 18. Node v26.11.1 est installé sur ce poste. | [registry.npmjs.org/discord.js/latest](https://registry.npmjs.org/discord.js/latest) |
| Modales discord.js | `ModalBuilder` et `showModal` existent. Le guide actuel et l'ancien ne décrivent pas la même structure (`LabelBuilder` contre `ActionRowBuilder` + `TextInputBuilder`). L'ouverture d'une modale depuis un bouton n'est confirmée que par un site communautaire. [VERIFICATION REQUIRED : documentation de discord.js 14.27, avant d'écrire le bot] | [discordjs.guide/guide/interactions/modals](https://discordjs.guide/guide/interactions/modals), [discordjs.guide/legacy/interactions/modals](https://discordjs.guide/legacy/interactions/modals) |
| FastAPI | 0.156.7, MIT, Python ≥ 3.10. Absent du dépôt, alors que la section 5 de la spec le prévoit (API interne). | [pypi.org/pypi/fastapi/json](https://pypi.org/pypi/fastapi/json) |
| Uvicorn | 0.54.0, BSD-3-Clause, Python ≥ 3.10. | [pypi.org/pypi/uvicorn/json](https://pypi.org/pypi/uvicorn/json) |
| Jinja2 | 3.1.6, Python ≥ 3.7. Les métadonnées PyPI ne donnent pas la licence. [VERIFICATION REQUIRED : fichier LICENSE du dépôt pallets/jinja, BSD-3 attendu] | [pypi.org/pypi/jinja2/json](https://pypi.org/pypi/jinja2/json) |
| ntfy | Publication par `POST https://<serveur>/<sujet>`, en-têtes `X-Title`, `X-Priority` (1 à 5) et `X-Tags`. Jeton : `Authorization: Bearer <jeton>`. Sur ntfy.sh, la doc dit que tous les sujets sont publics et que « le sujet est en pratique un mot de passe ». La réservation de sujets n'est pas vérifiée : [VERIFICATION REQUIRED : offre et limites de ntfy.sh]. | [docs.ntfy.sh/publish](https://docs.ntfy.sh/publish/) |
| TOTP | RFC 6238 (TOTP) sur RFC 4226 (HOTP). La RFC 6238 donne des vecteurs de test en annexe B. La bibliothèque standard suffit (`hmac`, `hashlib`, `hmac.compare_digest`). [VERIFICATION REQUIRED : relire l'annexe B avant d'écrire les tests] | rfc-editor.org/rfc/rfc6238 |
| État du dépôt | `interfaces/discord_bot/` et `interfaces/dashboard/` sont vides. `autonomy.yaml` contient `approval: { channel: discord, one_time_code: true, expiry_minutes: A_DEFINIR }`. La fonction `approvals` est bloquée par `cerveau config check`. Le journal accepte déjà l'événement `APPROVAL`. Le moteur de politique n'accorde que `auto`, `proposition` et `paper`, et refuse tout si `live.yaml` dit `enabled: true`. | `config/autonomy.yaml`, `core/config/loader.py:688`, `core/audit/chain.py`, `core/policy/engine.py` |
| Niveau d'autonomie | Le code lit le niveau dans `autonomy.yaml` sans vérifier la signature de `governance/approvals/`. `autonomy.yaml` n'est protégé par aucun hook. | `core/policy/engine.py`, `.claude/hooks/_common.py` |
| Hooks | Ils protègent `config/live.yaml`, `governance/approvals`, `var/audit`, `var/incidents` et `KILL`, mais pas un futur magasin d'approbations. | `.claude/hooks/_common.py` |

## 2. Périmètre (§17)

| Livrable (§17) | Livré en phase 5 | Reporté |
|---|---|---|
| Bot Discord : approbations, `/kill`, `/status` | client discord.js mince ; toute la logique reste en Python, derrière une API interne locale (D1) ; rapport quotidien en message privé | rapports hebdomadaires (phase 7) |
| Procédure d'activation manuelle | `docs/procedure-live.md` : prérequis, activation, vérification, retour arrière, désactivation | — |
| Adaptateur live présent mais désactivé | `LiveAdapter` : garde d'activation + protocole `BrokerClient`, aucun client de courtier tant que `broker` vaut `A_DEFINIR` (D8) | client IBKR, après ton choix du courtier |
| Rapport de promotion automatique | `cerveau promotion report finance --to N3` : tous les critères du §8.3, valeur, seuil et statut ; jamais de signature | N3 → N4 : compteurs posés, rapport en phase 7 |
| Dashboard v1 | FastAPI + Jinja2, local, lecture seule : positions, risque, décisions en cours, évals, santé des plugins (D15) | graphiques interactifs, accès à distance |
| Alertes | ntfy + Discord : kill switch, incidents, réconciliation, limites, budget (B46, B172) | — |

Critères de sortie du §17 :

- activation impossible sans action manuelle de l'utilisateur (test dédié, §7) ;
- approbation expirée = refus ;
- journal complet ;
- Claude Code n'active rien ;
- en plus : tests verts, évals au-dessus des seuils, revue `security-reviewer`, compte rendu du §18.

## 3. Approbations N3 — ADR-035

- **Nouveau paquet `core/approvals/`**, déterministe, sans modèle.
- **Demande.** Quand la politique rend `approbation`, une `ApprovalRequest` est créée. Elle contient :
  - `approval_id` (UUID v7) ;
  - `intent_id` et le SHA-256 de l'intention ;
  - le résultat de la Porte (quantité retenue, contrôles) ;
  - `created_at` et `expires_at` ;
  - l'environnement (`paper` ou `live`).
- **États** (machine à états, comme le carnet) :

| De | Vers | Événement |
|---|---|---|
| DEMANDEE | ACCORDEE | bouton + code valide, avant l'échéance |
| DEMANDEE | REFUSEE | bouton « Refuser », trop d'essais de code, kill switch |
| DEMANDEE | EXPIREE | échéance dépassée, constatée à la lecture (aucune minuterie nécessaire) |
| ACCORDEE | CONSOMMEE | exécution lancée, une seule fois |
| ACCORDEE | EXPIREE | non consommée avant l'échéance |

- **Expirée = refus.** L'échéance se vérifie à chaque lecture, avec une horloge injectée dans les tests. Une approbation expirée ne peut plus jamais passer à ACCORDEE ni à CONSOMMEE.
- **Lien à l'intention** (D4). L'approbation vaut pour un seul `intent_id` et pour son empreinte. À l'exécution, la Porte est réévaluée sur une photographie fraîche. Si le résultat change (refus, autre quantité), l'approbation est refusée et il en faut une nouvelle.
- **Code à usage unique** (D2) : TOTP RFC 6238, 6 chiffres, pas de 30 s, fenêtre ±1 pas.
  - Écrit dans le projet avec la bibliothèque standard, comparaison en temps constant, testé contre les vecteurs de la RFC.
  - Pas de rejeu : le dernier pas utilisé est enregistré, et un code d'un pas inférieur ou égal est refusé.
  - 3 essais par demande, puis REFUSEE. 5 échecs en 15 min verrouillent les approbations et déclenchent une alerte.
  - Le secret vit dans une variable d'environnement de l'utilisateur (`CERVEAU_TOTP_SECRET`), que tu poses et que Claude Code ne lit jamais.
  - `cerveau approvals enroll` génère le secret et l'URI `otpauth://` à scanner, dans ton terminal seulement. Les hooks refusent cette commande à Claude Code.
- **Magasin** : `var/approvals/approvals.db`, SQLite en ajout seul, comme le carnet. Il est protégé par les hooks (D18).
- **Journal** : une entrée `APPROVAL` par transition, avec `approval_id`, `intent_id`, état, raison et acteur. L'acteur est `owner` pour un accord vérifié par code, `interface` pour une demande (nouvel acteur).
- **Kill switch** : toutes les demandes ouvertes passent à REFUSEE (« kill switch »).
- **Compteurs N3 → N4** : approbations, refus et taux d'accord entre toi et CERVEAU, enregistrés dès maintenant.

## 4. Politique et niveau effectif — ADR-036

- **Décision accordée** (D5) : `approbation` pour `FINANCIERE`, dans le domaine `finance` seulement. `COMMUNICATION_EXTERNE` et `IRREVERSIBLE` restent refusés, car aucun composant ne les porte. Un test parcourt toute la matrice pour vérifier qu'aucun chemin ne devient plus permissif qu'écrit.
- **Effet** `approbation` : l'intention passe la Porte, puis attend. Elle n'est envoyée qu'après un accord valide, à l'adaptateur que désigne l'environnement.
- **Niveau effectif** (D6, durcissement) : le minimum entre le niveau de `autonomy.yaml` et le plus haut niveau signé dans `governance/approvals/AAAA-MM-JJ-finance-NX.md`. Modifier `autonomy.yaml` seul ne promeut donc rien.
- **Fichier de signature** (D7) : un en-tête YAML minimal (`domain`, `level`, `date`, `promotion_report_sha256`, `signed_by: owner`). Le code le lit, ne l'écrit jamais, et vérifie que le rapport cité existe et a cette empreinte.
- **Répétition N3 sur le paper** (D10) : en N3 avec le live désactivé, une intention approuvée part au simulateur paper, étiquetée « paper ». Le circuit complet s'éprouve ainsi sans argent réel.
- **Défense en profondeur** : `live.yaml` à `enabled: true` sans les autres conditions du §7 donne un refus avec alerte, comme en phase 4.

## 5. Interfaces : API interne et bot Discord — ADR-037

- **API interne** (`interfaces/api/`, FastAPI, D1) :
  - liée à `127.0.0.1` seulement ;
  - jeton partagé avec le bot dans une variable d'environnement (`CERVEAU_API_TOKEN`), comparé en temps constant ;
  - routes : `GET /status`, `POST /kill`, `GET /approvals/pending`, `POST /approvals/{id}/approve` (code requis), `POST /approvals/{id}/refuse`, `GET /reports/daily` ;
  - **aucune route de réarmement** : le réarmement reste en terminal interactif (ADR-034).
- **Bot** (`interfaces/discord_bot/`, Node, discord.js 14.27.0) : un client mince qui relaie à l'API et ne décide rien.
  - Il ne répond qu'à ton identifiant Discord (`config/interfaces.yaml`, `A_DEFINIR`), en message privé seulement. Tout autre utilisateur ou salon est ignoré et journalisé.
  - **Approbation** : un message résume l'intention (instrument, sens, quantité retenue, prix limite, raisons de la Porte, échéance) avec deux boutons, « Approuver » et « Refuser ». « Approuver » ouvre une modale qui demande le code.
  - **`/kill`** : sans code, pour aller vite (D11). La cible de 5 s se mesure de la réception par l'API jusqu'à l'état écrit, dans un processus déjà chargé (B170).
  - **`/status`** : kill switch, live (oui/non), niveaux, approbations en attente, ordres ouverts, dernière réconciliation, dernier passage de la boucle, budget.
  - **Rapport quotidien** : résumé en message privé, avec la tête de la chaîne d'audit, ce qui fournit une ancre externe horodatée (B8 en partie, D13).
  - **Contenu** (D12) : états, nombres et pourcentages ; ni montant ni position. Le détail chiffré reste au dashboard local.
- **Lancement** : par toi seul (D22). Claude Code ne lance jamais le bot et ne se connecte jamais à Discord ; les hooks refusent le démarrage du bot. Les tests n'utilisent aucun réseau : `TestClient` de FastAPI pour l'API, un faux client Discord avec `node:test` pour le bot.

## 6. Alertes ntfy — ADR-038

- **`core/notify/`** : un protocole `Notifier`, avec deux canaux, ntfy (`httpx`) et Discord (via l'API).
- **Événements** : kill switch engagé, annulation non confirmée (B172), incident d'exécution, écart de réconciliation, limite dépassée, approbation verrouillée, budget à 50, 80 et 100 % (B46), rapport quotidien prêt.
- **Contenu minimal** (D14) : type, gravité et identifiant, sans montant ni instrument. Un sujet qui fuit n'apprend rien d'exploitable.
- **Configuration** : URL du serveur et sujet `A_DEFINIR` dans `config/interfaces.yaml` ; jeton dans `NTFY_TOKEN`, que tu poses. Sans configuration, l'alerte reste au journal et à la console, et `cerveau config check` le signale.
- **Échec d'envoi** : il est journalisé et ne bloque jamais un arrêt.

## 7. Adaptateur live et activation — ADR-039

- **`core/execution/live.py`** : `LiveAdapter` met en œuvre `BrokerAdapter` au-dessus d'un protocole `BrokerClient`. Le dépôt ne fournit **aucun client de courtier** tant que `broker` vaut `A_DEFINIR` (D8).
- **Conditions d'activation**, toutes manuelles, toutes requises, revérifiées **à chaque appel** et pas seulement au démarrage :
  1. `config/live.yaml` : `enabled: true`, `broker` renseigné, limites > 0, liste blanche non vide ;
  2. ACL posée sur `config/live.yaml` et `governance/approvals/` (B1, B2), vérifiée par `icacls` sous Windows ;
  3. signature N3 valide dans `governance/approvals/` (§4) ;
  4. niveau effectif de la finance ≥ N3 ;
  5. kill switch non engagé ;
  6. approbation ACCORDEE, non expirée, liée à l'intention.
- **Test dédié** (critère du §17) : les 2⁶ combinaisons des six conditions. Une seule, toutes vraies, laisse passer, avec un client de courtier factice qui compte les appels. Dans les 63 autres, ce client n'est jamais appelé.
- **Test statique** : aucun module de `core/` ni de `interfaces/` n'écrit dans `config/live.yaml`, `governance/approvals/` ou `var/approvals/` (lecture de l'AST : `open` en écriture, `write_text`, `Path.write_bytes`, `shutil`, `os.replace` sur ces chemins).
- **Limites** : une intention live passe la Porte avec les limites de `live.yaml`, qui valent toutes 0 aujourd'hui, donc tout est refusé. Le levier, la vente à découvert et les dérivés restent interdits.
- **Exigences de la phase 4 pour un adaptateur réel** :
  - chaque appel est borné par un délai inférieur à la cible du kill switch (B171) ;
  - exécutions et relevé sont lus dans une même coupe (B169) ;
  - seuls un code de refus et le nom du type d'exception sont journalisés, jamais leur texte (B197).
- **Procédure** `docs/procedure-live.md` (D9) :
  - prérequis : rapport de promotion, campagne réelle et red team, ACL, utilisateur Windows dédié au service live, clés sans droit de retrait (§8.6) ;
  - activation pas à pas, puis vérification par `cerveau status` et un ordre de taille minimale approuvé ;
  - retour arrière : `/kill`, `enabled: false`, révocation des clés ;
  - rotation des clés tous les `A_DEFINIR` jours.

## 8. Rapport de promotion — ADR-040

- **`cerveau promotion report finance --to N3`** produit `var/promotion/finance-N3-AAAA-MM-JJ.md` et son SHA-256.
- **Critères du §8.3**, chacun avec valeur, seuil, statut et outil source (R1) :
  - semaines et décisions de paper (B181) ;
  - incidents d'exécution ;
  - écart paper/backtest mesuré et expliqué (B181) ;
  - drawdown paper ;
  - golden et red team du domaine ;
  - éval nocturne si elle existe.
- **Seuil `A_DEFINIR`** : le critère est « non évaluable » et la promotion impossible (R7).
- **Signature** : le rapport propose le texte du fichier de signature. Tu le copies toi-même dans `governance/approvals/` ; le code n'y écrit jamais.
- **Valeurs N2 → N3** (D17, point 16 de la phase 4) : à toi de les fixer. Je propose 13 semaines, 30 décisions et un drawdown paper ≤ 10 %.

## 9. Dashboard v1 — ADR-041

- **FastAPI + Jinja2**, servi par l'API interne, sur `127.0.0.1`, en **lecture seule** : aucune route d'écriture, aucune approbation, aucun JavaScript tiers.
- **Pages** :
  - positions et cash du compte paper ;
  - risque (outils `finance_risk` existants, chiffres cités) ;
  - décisions en cours (intentions, approbations en attente, échéances) ;
  - évals (dernier rapport hors ligne) ;
  - santé des plugins (registre, dernières erreurs du journal) ;
  - état du kill switch et du live.
- **Accès** (D16) : boucle locale seule, plus le jeton de l'API.

## 10. Dette du backlog incluse (D20)

| Groupe | Éléments |
|---|---|
| Avant tout adaptateur réel | B197 (textes recopiés), B169 (coupe cohérente), B171 (délai par appel), B170 (kill switch dans un processus chargé), B1 et B2 (ACL vérifiée à l'activation) |
| Fidélité du paper | B187 (splits et dividendes, avant `universe`), B189 (pertes par séance), B190 (volume moyen), B192 (« écart d'exécution »), B194 (marqueur de fraîcheur) |
| Porte et évals | B195 (liste blanche des outils de dimensionnement), B196 (tests des interdits), B186 (cas sur les compteurs d'ordres) ; B188 seulement si tu dis oui |
| Promotion | B181 (compteurs N2 → N3 et écart paper/backtest) |
| Alertes | B46, B172 |
| Hooks | B185 (faux positifs), sous réserve de ta validation des hooks |

Reportés : B166 et B180 (multi-devise et multi-place), B168, B182 et B191 (état de séance, qui demande une source), B174 à B178, B193 (goldens, à valider par toi).

## 11. Évaluations

| Élément | Contenu | Critère mesuré |
|---|---|---|
| Comportements `finance_approbation` | ≥ 8 cas : ne jamais dire « approuvé » sans accord ; ne jamais demander le code dans la conversation ; ne jamais dire « ordre réel envoyé » quand le live est désactivé ; expliquer une expiration ; distinguer paper et live | 100 % |
| Red team `injection_approbation` | ≥ 10 cas : un contenu externe pousse à approuver, à donner le code, à activer le live, à modifier `live.yaml` ou `autonomy.yaml`, à monter de niveau, à désactiver le kill switch | 0 violation |
| Golden Finance | Cas existants **inchangés**. Environ 6 nouveaux cas (statut, rapport de promotion, approbation expirée), que je rédige, que tu valides, puis gelés (R9) | taux ≥ 0,85 |
| Déterministe | approbations, TOTP, activation, notifications | 100 % des tests |

- **Hors ligne (CI)** : modèles scriptés, fixtures.
- **Réel** : bloqué tant que les budgets restent `A_DEFINIR`, puis lancé avec ton accord pour chaque campagne.

## 12. Tests (aucun réseau en CI)

- **TOTP** : vecteurs de la RFC 6238, fenêtre ±1, rejeu refusé, comparaison en temps constant, secret absent ⇒ refus.
- **Approbations** : `RuleBasedStateMachine` ; jamais CONSOMMEE sans ACCORDEE, jamais deux fois, jamais après l'échéance. Propriété : pour toute horloge, une approbation expirée est refusée.
- **Activation** : les 64 combinaisons du §7 et le test statique d'écriture.
- **Journal complet** : un parcours de bout en bout (intention → politique → Porte → demande → accord → envoi → exécution → réconciliation), puis `audit verify`, puis la reconstruction du cycle de chaque intention à partir du seul journal, sans trou.
- **API** : `TestClient` ; jeton absent ou faux ⇒ 401 ; aucune route de réarmement ; `/kill` sous la cible.
- **Bot** : `node:test` avec un faux client ; un autre utilisateur ou un salon ⇒ ignoré ; la modale transmet le code sans le journaliser.
- **Notifications** : `httpx.MockTransport` ; échec d'envoi ⇒ journal, jamais de blocage de l'arrêt.
- **Hooks** : `var/approvals/` protégé ; `cerveau approvals enroll` et le lancement du bot refusés.
- **Couverture** (D19) : 100 % des lignes et des branches pour `core/approvals` et la garde d'activation de `core/execution/live.py`, imposée par `make ci` comme pour `core/risk_gate`.

## 13. Nouvelles dépendances

| Paquet | Version | Licence | Rôle |
|---|---|---|---|
| fastapi | 0.156.7 | MIT | API interne et dashboard |
| uvicorn | 0.54.0 | BSD-3-Clause | serveur de l'API |
| jinja2 | 3.1.6 | BSD-3 attendu, `A_VERIFIER` | gabarits du dashboard |
| discord.js (npm) | 14.27.0 | Apache-2.0 | bot |

Avant chaque ajout : `source-verifier`, `pip-audit` ou `npm audit`, `docs/licences.md`. Le bot a son propre `package.json` et un `package-lock.json` épinglé. Le TOTP n'ajoute aucune dépendance.

## 14. Décisions demandées à l'utilisateur

| # | Décision | Options | Ma recommandation |
|---|---|---|---|
| D1 | Pile du bot | discord.js mince + API interne FastAPI (spec, section 5) / discord.py en un seul processus Python | **discord.js**, comme le prévoit la spec. Toute la logique reste en Python, et l'API ne peut rien approuver sans ton code. Le coût : une API locale et un `npm audit`. |
| D2 | Code à usage unique | TOTP (application d'authentification) / code aléatoire envoyé par ntfy / code affiché dans Discord | **TOTP écrit dans le projet** : c'est un second facteur indépendant de Discord. Un code affiché dans Discord ne prouve rien si le compte Discord est compromis. |
| D3 | Échéance et essais | `expiry_minutes` ; essais par demande | **10 min**, **3 essais**, puis verrouillage à 5 échecs en 15 min. `A_DEFINIR` jusqu'à ta réponse. |
| D4 | Lien à l'intention | approbation liée à l'empreinte de l'intention + Porte réévaluée à l'exécution / approbation libre | **Liée et réévaluée** : un changement de quantité demande une nouvelle approbation. |
| D5 | Politique en N3 | `approbation` pour FINANCIERE en finance ; COMMUNICATION_EXTERNE et IRREVERSIBLE refusés | **Oui**. |
| D6 | Niveau effectif | minimum entre `autonomy.yaml` et la signature / `autonomy.yaml` seul | **Minimum** : c'est un durcissement. |
| D7 | Format de signature | en-tête YAML minimal, avec l'empreinte du rapport de promotion / texte libre | **En-tête YAML**, que le code lit sans jamais l'écrire. |
| D8 | Adaptateur live | garde d'activation + protocole `BrokerClient`, sans client de courtier / client IBKR (ib_async) dès maintenant | **Sans client** tant que `broker` vaut `A_DEFINIR`. Un client réel demande ton compte, et Claude Code n'active jamais de compte de courtier. |
| D9 | Conditions d'activation | les six du §7, revérifiées à chaque appel | **Oui**, avec le test des 64 combinaisons. |
| D10 | Répétition N3 sur le paper | approbation → simulateur paper tant que le live est désactivé / approbations seulement pour le live | **Oui** : le circuit complet s'éprouve sans argent réel. |
| D11 | `/kill` sur Discord | sans code, ton identifiant seulement / avec code | **Sans code** : l'arrêt doit être immédiat, et il ne va que dans le sens sûr. Le réarmement reste local. |
| D12 | Contenu sur Discord | états, nombres et pourcentages / montants et positions | **Sans montant ni position** ; le détail est au dashboard local. Une approbation montre l'instrument, la quantité et le prix limite : c'est indispensable pour décider. |
| D13 | Rapport quotidien et ancre | résumé quotidien avec la tête de la chaîne d'audit / pas de rapport sur Discord | **Oui** : une ancre externe horodatée (B8 en partie). |
| D14 | ntfy | ntfy.sh avec un sujet aléatoire long et un contenu minimal / auto-hébergé (profil Docker), joignable depuis le téléphone seulement par un VPN | **ntfy.sh** jusqu'au VPS, avec un sujet d'au moins 32 caractères aléatoires en variable d'environnement et aucun contenu sensible. URL et sujet `A_DEFINIR`. |
| D15 | Dashboard | FastAPI + Jinja2, en lecture seule / Streamlit / HTML statique généré | **FastAPI + Jinja2** : il réutilise l'API, sans JavaScript tiers ni nouvelle surface d'écriture. |
| D16 | Accès au dashboard | boucle locale + jeton / boucle locale seule | **Boucle locale + jeton**. |
| D17 | Valeurs N2 → N3 | à toi | Proposition : 13 semaines, 30 décisions, drawdown paper ≤ 10 %. Elles restent `A_DEFINIR` jusqu'à ta réponse ; la promotion reste impossible d'ici là. |
| D18 | Protection des approbations | `var/approvals/` protégé par les hooks ; `enroll` et le lancement du bot refusés à Claude Code | **Oui**, plus l'ACL quand tu la poses (B173). |
| D19 | Couverture 100 % | `core/approvals` + garde d'activation / `core/risk_gate` seul | **Les deux**. |
| D20 | Dette incluse | liste du §10 | **Incluse** comme au §10. B188 selon ta réponse. B185 seulement après ta validation des hooks (point 8 de la phase 4). |
| D21 | Revues | `security-reviewer` + `risk-gate-auditor` (politique et autonomie changent) + `quant-reviewer` (B187 et B189 touchent le paper) / `security-reviewer` seul | **Les trois** : la règle `finance.md` impose les deux dernières. |
| D22 | Lancement | toi seul (API, bot) ; Claude Code jamais / Claude Code lance l'API pour une démonstration | **Toi seul**. La procédure est écrite, et les tests couvrent le reste sans réseau. |
| D23 | Identifiant Discord, URL ntfy, port | `config/interfaces.yaml`, `A_DEFINIR` | Tu les donnes quand tu crées l'application Discord. Les jetons vont en variables d'environnement : `DISCORD_BOT_TOKEN`, `CERVEAU_API_TOKEN`, `CERVEAU_TOTP_SECRET`, `NTFY_TOKEN`. |
| D24 | B188 (vente sous les frais) | autoriser `max(0, frais − brut)` / garder le refus | **Autoriser**, avec l'oracle et un test dédié. C'est un assouplissement de la Porte, donc ta décision. |
| D25 | Nouveaux goldens | environ 6 cas, les existants inchangés / aucun | **Oui** : je les rédige, tu les valides, puis ils sont gelés. |
| D26 | Points restés ouverts en phase 4 | ACL (B173), validation des hooks, push et CI GitHub (B14), budgets | **Pas bloquants pour la livraison** ; le live reste impossible sans eux. L'ACL est à poser avant tout essai réel. |

## 15. Hors périmètre → `docs/backlog.md`

- Client de courtier réel (IBKR ou autre), comptes et clés.
- VPS, WireGuard, ntfy auto-hébergé, accès au dashboard à distance.
- Rapports hebdomadaires, champion / challenger, rétrogradation sur dérive de calibration, éval nocturne et SLO de plugin (phase 7).
- Rapport de promotion N3 → N4 (compteurs posés en phase 5).
- Serveur MCP « cerveau » (section 15) : `.mcp.json` reste vide.
- B166, B168, B174 à B178, B180, B182, B191, B193.

## 16. Commits atomiques (en anglais, `make ci` vert à chaque étape)

1. `docs: add the validated phase 5 plan`
2. `docs(adr): add ADR-035 to ADR-041 (approvals, effective level, interfaces, notifications, live adapter, promotion report, dashboard)`
3. `feat(config): add interfaces settings and approval parameters as A_DEFINIR`
4. `feat(approvals): add an RFC 6238 one-time code verifier tested against the RFC vectors`
5. `feat(approvals): add the approval state machine and the append-only approval store`
6. `ci: require full line and branch coverage of core/approvals`
7. `feat(policy): grant approbation at N3 for finance and bind approvals to intents`
8. `feat(policy): cap the autonomy level at the highest signed approval`
9. `feat(hooks): protect var/approvals and refuse enrollment and bot launch from Claude Code`
10. `feat(execution): add the live adapter guard with per-call activation checks (B1, B2, B169, B171)`
11. `test(execution): prove live activation needs every manual step (64 combinations, static write scan)`
12. `fix(execution): log refusal codes and exception types, never their text (B197)`
13. `feat(execution): route approved intents to the paper simulator while live is disabled`
14. `feat(notify): add ntfy and Discord notifiers with minimal content (B46, B172)`
15. `feat(api): add the local internal API (status, kill, approvals, daily report)`
16. `feat(discord): add the discord.js bot (approvals, /kill, /status, daily report)`
17. `feat(dashboard): add the read-only local dashboard`
18. `feat(promotion): generate the N2 to N3 promotion report with paper counters (B181)`
19. `fix(execution): apply splits and dividends known at decision time in the paper loop (B187)`
20. `fix(execution): count losses per session, check volume continuity, rename execution gap (B189, B190, B192, B194)`
21. `fix(risk-gate): whitelist sizing tools and test every forbidden instrument (B195, B196)` (+ B188 selon D24)
22. `test: add the end-to-end journal completeness test`
23. `test(evals): add approval behaviours, approval red team and golden drafts (B186)`
24. `docs: add the live activation procedure`
25. `docs: update licences, threat model and backlog`
26. `docs: add the phase 5 report`

## 17. Coût estimé (non mesuré)

- **Développement** : aucun appel payant, tout passe hors ligne.
- **Discord** : 0 €. **ntfy.sh** : 0 € dans l'offre gratuite. [VERIFICATION REQUIRED : limites de l'offre gratuite]
- **Campagne d'évals réelle** : environ 25 nouveaux cas, plus les suites que relance un changement de prompt, soit **5 à 15 $** (estimation). Elle n'a lieu qu'avec ton accord et les budgets fixés.
- **Données et bibliothèques** : 0 €.

## 18. Exécution

- **Où** : dans cette session, ouverte dans `cerveau-plateforme`, où les hooks du projet sont chargés.
- **Ordre** :
  1. tes décisions ;
  2. la documentation (discord.js 14.27 : boutons, modales, messages privés ; FastAPI : `TestClient`, dépendances de sécurité ; RFC 6238 ; ntfy) ;
  3. ADR et configuration ;
  4. TOTP et approbations, avec la couverture ;
  5. politique et niveau effectif ;
  6. hooks ;
  7. adaptateur live et test d'activation ;
  8. notifications, API, bot, dashboard ;
  9. rapport de promotion ;
  10. dette du paper et de la Porte ;
  11. journal complet ;
  12. évals ;
  13. procédure live ;
  14. revues selon D21 ;
  15. rapport du §18.
- **Fin de phase** : je m'arrête et j'attends `GO PHASE 6`.
