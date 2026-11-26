# À valider par l'utilisateur

Liste préparée le 21/11/2026 (étape 9 du plan, `docs/plans/plan-cerveau.md`). Rien n'y est validé : c'est à
toi de répondre, en une fois si tu veux (« tout validé », ou les numéros à refuser ou à revoir). Une fois ta
réponse donnée, chaque ADR passe à « accepté » (ou « refusé ») avec la date, dans son propre fichier.

## 1. Les 36 ADR encore « proposé »

41 le 21/11 ; le 23/11/2026, tu as validé les retraits R9 (section 2) : les ADR-021, 046, 050, 057, 060 et
068 sont acceptés, l'ADR-063 reste ici pour le reste de sa décision.

Le détail de chaque décision est dans son fichier (`docs/adr/ADR-NNN-….md`). Une ligne par ADR ici.

### Socle de la phase 1 (orchestrateur, à l'arrêt tant que le budget API est à 0 €)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 005 | Routage des modèles, coûts déterministes et budgets | Chaque rôle a un niveau de modèle (`fast`, `standard`, `deep`) lu dans `models.yaml` ; coûts calculés, budgets qui refusent au-delà |
| 006 | Plugin `web_research` | Serveur MCP de lecture à deux outils : `web_search` (Brave) et `web_read` (lecteur web gardé) |
| 007 | Client MCP maison | Adaptateur sur le SDK officiel : environnement réduit, seuls les outils du manifeste validé et permis par la politique |
| 008 | Séparation lecteur / acteur (R5) | Le planificateur n'a aucun outil d'action ; un lecteur sans outil extrait des affirmations citées mot pour mot, vérifiées dans la page |
| 009 | Harnais d'évaluation de la phase 1 | Les évals appellent le graphe complet, contrôles déterministes, juge d'un autre modèle que celui évalué |
| 010 | Pseudonymisation française (presidio-analyzer) | presidio-analyzer seul sur spaCy `fr_core_news_md` (personnes, lieux, e-mail, IBAN, carte, téléphone, NIR, IP), seuil proposé 0,5 |

### Finance (phases 2 et 3)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 016 | Contrôles de qualité des séries de cours | Score déterministe sur les 500 séances de la fenêtre de VaR ; **les deux seuils attendent ta décision** |
| 017 | Fournisseurs et heures de publication | Heure de publication = la plus petite entre l'heure documentée + 1 h et l'heure de récupération (R10) ; deux faits `A_VERIFIER` sur une vraie réponse de la BCE |
| 018 | Transactions, positions et rapprochement | Format CSV de CERVEAU (date, compte, type, identifiant, quantité, prix, devise, frais), import des exports de courtier, rapprochement |
| 019 | Conventions de l'optimisation | Univers = titres détenus, positions longues sans levier, covariance de Ledoit-Wolf, proposition de rééquilibrage |
| 020 | Conventions de la performance | Jours TARGET, livre rejoué chaque jour, rendement pondéré par le temps et attribution |
| 022 | Capacité CALCUL du pack Finance | Le domaine `finance` reçoit les classes LECTURE et CALCUL ; aucune décision au-delà de `auto` |
| 023 | Horloge et chiffres gelés des évals Finance | Horloge fixe pour les cas Finance, chiffres attendus gelés dans le golden set ; **à valider** |

### Socle des packs et pack Recherche (phase 6)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 043 | Socle commun des packs | Packs découverts par leur manifeste, statut `experimental` ou `actif`, généraliste toujours en repli |
| 044 | Plugins `scholarly` et `feeds` | arXiv et Crossref (hôtes fixes, débit partagé) ; flux RSS et Atom d'une liste blanche |
| 045 | Agent `deep_research` | Recherche approfondie seulement avec `cerveau ask --approfondi`, bornes fixes, affirmation retirée si sa citation n'est pas vérifiée |
| 058 | Liste fermée de sites par domaine | Lecture web d'un domaine limitée à des hôtes exacts ou leurs sous-domaines, sans joker |

### Pack Code (P3a, P3b)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 047 | Lecteur git des dépôts autorisés | Liste blanche (`config/code.yaml`), CERVEAU exclu, aucun jeton |
| 048 | Bac à sable Docker des contrôles | Copie depuis les objets git, conteneur sans réseau, pytest dans un environnement préparé, image construite par toi |
| 049 | Capacité CALCUL du pack Code | LECTURE et CALCUL pour `code`, aucune écriture |
| 051 | Classe d'action EXECUTION_ISOLEE | Tâche dans un conteneur jetable sur une copie ; sa seule sortie est une proposition rangée sous `var/` |
| 052 | Délai d'appel déclaré par le plugin | `runtime.tool_timeout_s` du manifeste (30 s par défaut, 900 s au plus) ; démarrage toujours borné à 30 s |
| 053 | Proxy de l'API d'Anthropic pour l'agent de code | Un conteneur proxy par tâche, seul à sortir vers l'API, requêtes filtrées (ne sert qu'avec un budget API) |
| 054 | Agent de code en conteneur | Claude Code dans un conteneur Linux sur un réseau interne, patch calculé par CERVEAU (ne sert qu'avec un budget API) |

### Pack Cyber (P4)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 055 | Plugin `cyber_cve` | NVD, KEV et EPSS en lecture, trois hôtes fixes en HTTPS, tri déterministe |
| 056 | Copie figée d'ATT&CK | `cerveau cyber attack-fetch` lancé par toi seulement, index local, plugin `cyber_attack` |

### Pack Juridique FR (P5)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 059 | Plugin `legifrance` (API PISTE) | API officielle, entrées fermées (identifiants, dates, fonds), lecture seule |

### Pack Business (P6)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 061 | Plugin `business_calc` | Calculateur déterministe à opérations fermées (marge, prix de vente, TVA, seuil de rentabilité, CAC/LTV, variation, TCAC) |
| 062 | Plugin `entreprises` | Lecteur du registre des entreprises, un outil `company_search`, aucune personne |
| 063 | Pack Business & commerce | LECTURE et CALCUL, brouillons jamais envoyés, évals hors ligne ; **remplace aussi un cas d'éval** (voir sous le tableau 2) |

### Amélioration continue (phase 7)

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 064 | Registre des prévisions et calibration | Base où rien ne s'efface, résolution après l'échéance seulement, score de Brier |
| 065 | Couche apprise et porte champion / challenger | Fichiers `learned/<pack>/` en liste fermée, noyau verrouillé, un challenger ne remplace le champion qu'après la porte d'évals |
| 066 | Rapports planifiés | Rapport hebdomadaire, rapport de sécurité du mois, série de semaines |
| 067 | Promotion N3 → N4 et rétrogradation automatique | Rapport de promotion que tu signes, bornes, rétrogradation automatique sur incident |

### Chef d'orchestre à 0 € d'API

| ADR | Titre | Décision en une ligne |
|---|---|---|
| 069 | Claude Code comme chef d'orchestre | Pont MCP `cerveau-plateforme` à cinq outils, sous la même gouvernance ; le graphe LangGraph reste en place (il modifie l'ADR-002) |
| 070 | Les règles de `verifier` (26/11) | Un nombre groupé se lit d'un bloc, un zéro demande un zéro, une mesure ne vient que de sa figure ; date du jour, « Étape 2 » et tes chiffres (`citations_utilisateur`, listés à part) acceptés ; chaque vérification au journal |

## 2. Les 5 retraits de cas d'évaluation (règle R9 : à toi seul)

**Validés par toi le 23/11/2026**, avec le retrait de l'ADR-063 et la valeur du golden de l'ADR-068 (ci-dessous).

Chaque cas vérifiait qu'une question d'un domaine sans pack retombait sur le pack généraliste, avec la note
« … n'existe pas encore ». L'arrivée du pack rend sa prémisse fausse : il échoue par construction. Dans
chaque cas, le remplaçant garde la même attente, et ni le seuil du groupe (100 %), ni le minimum de cinq
cas par groupe ne changent.

| ADR | Cas retiré | Pourquoi | Remplacé par |
|---|---|---|---|
| 021 | `pack-finance-absent` : une question de finance | Le pack Finance existe (phase 2) | `pack-business-absent` : une question de gestion d'entreprise |
| 046 | `pack-recherche-absent` : « Qu'est-ce qu'une revue systématique de la littérature ? » | Le pack Recherche existe (phase 6) | `pack-cuisine-absent` : une question de cuisine |
| 050 | `pack-code-absent` : « À quoi sert une liste en compréhension en Python ? » | Le pack Code existe (P3a) | `pack-jardinage-absent` : une question de jardinage |
| 057 | `pack-cyber-absent` : « Qu'est-ce qu'un gestionnaire de mots de passe ? » | Le pack Cyber existe (P4) | `pack-astronomie-absent` : une question d'astronomie |
| 060 | `pack-juridique-absent` : « Quel est le délai de rétractation pour un achat en ligne ? » | Le pack Juridique FR existe (P5) | `pack-musique-absent` : une question de musique |

À savoir en même temps : l'ADR-063 retire de la même façon `pack-business-absent` (le remplaçant de
l'ADR-021) au profit de `pack-photographie-absent`, le dernier de la série (B263, clos en P6). L'ADR-068
change une valeur attendue du golden set Finance (tableau 1). Ces deux-là relèvent aussi de R9.
