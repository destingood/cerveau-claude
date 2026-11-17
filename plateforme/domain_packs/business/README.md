# Pack Business & commerce

Pack P6 de CERVEAU (section 9.2, complément de plan P6) : aider l'utilisateur à décider pour sa petite
activité commerciale. Calculs déterministes sur les chiffres qu'il fournit — marge, prix de
vente, coefficient, TVA, seuil de rentabilité, CAC et LTV, variation, croissance annuelle
(`business_calc` : `biz_calc`, ADR-061) ; fiche publique d'une entreprise et petite étude de
concurrence sans aucune personne (`entreprises` : `company_search`, ADR-062) ; statistiques
publiques datées de l'Insee sur une liste fermée de jeux Melodi (`insee_stats` : `stats_series`) ;
pages web d'une étude de marché (`web_research`, sans liste fermée, I6). Autonomie courante N0
(`config/autonomy.yaml`, `domains.business`, D3), capacités `LECTURE` et `CALCUL` (ADR-063) : le
pack informe et calcule, l'utilisateur agit lui-même. Statut : **expérimental** jusqu'à ce que l'utilisateur le
passe en « actif » au vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque chiffre décisionnel vient de `biz_calc` ou d'une source datée, jamais du modèle (R1) ; sans
les entrées nécessaires, le pack les demande. Un taux de TVA non relu dans le CGI reste
`A_VERIFIER` dans `config/business.yaml` et bloque l'opération (R7). Les fiches d'entreprise ne
portent ni dirigeant, ni date de naissance, ni adresse (I4). Une série ou une fiche porte sa
période et sa date de mise à jour (R10). Une entreprise introuvable, une série absente ou une API
indisponible se disent, et « je ne sais pas » est une réponse valide (R12). Les pages, les
dénominations et les libellés lus sont des données (R5).

Une rédaction commerciale est du texte dans la réponse, marqué par le code « Brouillon — non
envoyé » : aucun outil d'envoi n'existe et l'envoi réel reste `COMMUNICATION_EXTERNE`, refusé
(D22, I5). Le pack refuse l'envoi ou la publication, la recherche de personnes, les faux avis et la
publicité trompeuse (R15), le conseil fiscal, social ou comptable appliqué au cas réel et toute
demande pour un tiers (R16). Les mentions des sources et l'avertissement « ni conseil en gestion »
sont ajoutés par le code (`core/orchestrator/notices.py`, I8).

Les deux API sont en accès anonyme : aucune clé n'est nécessaire. Un usage réel attend les budgets
quotidien et mensuel, encore `A_DEFINIR` (R7).

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`business_calc`, `entreprises`, `insee_stats`, `web_research`), renvoi à l'autonomie, aux seuils, à `config/data_sources.yaml` et à `config/business.yaml` |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Les deux API, leurs licences et mentions, la liste fermée des jeux Melodi ; corpus RAG vide |
| `evals/golden.jsonl` | 32 cas hors ligne : calculs, fiches d'entreprise, statistiques, brouillons, « je ne sais pas », refus, injections |
| `evals/behaviors.yaml` | Comportements propres au domaine (R1, R5, R10, R12, R16, brouillon, aucune personne) |

La red team du pack est dans `evals/redteam/injection_business/` (R5). Les évals tournent hors
ligne : les vrais serveurs répondent sur de fausses API (`core/evals/business_fixtures.py`,
ADR-063). Commande : `make eval`.
