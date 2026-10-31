# ADR-011 — Auto-amélioration automatique sous porte d'évals et noyau verrouillé

- Statut : **accepté par l'utilisateur le 18/10/2026**
- Date : 2026-10-18
- Phase : 1 (premières briques) ; boucle complète en phase 7 ; ouverture publique en phase 8

## Contexte
La section 11 de la spécification dit : « Pas d'auto-modification en production : une amélioration
de prompt ou de paramètre proposée par CERVEAU passe par une PR, les évals et une comparaison
champion / challenger. » l'utilisateur a décidé autrement le 18/10/2026. Ses mots :

1. « le cerveau doit être capable d'évoluer et d'apprendre de ses erreurs, et toute personne qui
   l'utilise doit aussi améliorer le cerveau en automatique, même quand le cerveau est public »
2. « Option B : tout automatique, y compris le prompt et les paramètres, sans validation. »
3. « Oui : tout automatique, avec le test avant chaque mise en ligne et le noyau verrouillé. »

## Options
1. **Statu quo de la section 11** : chaque amélioration passe par une PR que l'utilisateur relit. Sûr,
   mais lent, et contraire à la décision.
2. **Proposition automatique, validation humaine** : CERVEAU prépare le challenger, l'utilisateur
   promeut. Écartée par l'utilisateur (« sans validation »).
3. **Tout automatique derrière deux verrous automatiques** : une porte d'évals avant chaque mise
   en ligne et un noyau que l'apprentissage ne peut pas toucher.

## Décision
Option 3.

**Amendement de la section 11.** Pour les seuls éléments apprenables listés ci-dessous, la phrase
de la section 11 est remplacée par la porte automatique décrite ici : pas de PR, pas de validation
humaine. Le noyau verrouillé garde la règle d'origine, en plus strict : il ne change qu'à la main,
par l'utilisateur (R3). `docs/MEGA-PROMPT-CERVEAU.md` n'est pas modifié ; cet ADR fait foi.

**Sources d'apprentissage**
- Ses propres erreurs : citations rejetées, chiffres non vérifiés, liens retirés, faibles scores
  du juge, budgets dépassés, limites de requête atteintes, requêtes en erreur.
- Les retours de chaque utilisateur, public compris : 👍 / 👎, corrections, questions ratées.
- R5 s'applique sans exception : un retour ou une contribution est une donnée non fiable, jamais
  une instruction. Il est pseudonymisé avant d'être stocké et balisé comme contenu externe avant
  d'être lu par un modèle.

**Ce que l'apprentissage peut changer**
- Les sections de prompt des packs de domaine : rôle, exemples, leçons.
- Les paramètres de routage, de recherche et de choix d'outils, dans une configuration apprise
  dédiée, séparée de `config/*.yaml` (emplacement `A_DEFINIR` en phase 7).
- Les leçons de la mémoire.

**Noyau verrouillé** (l'apprentissage n'y touche jamais)
- `config/live.yaml` et `governance/approvals/**` ;
- `config/autonomy.yaml` ;
- les limites de la Porte de risque ;
- `config/budgets.yaml` ;
- les golden sets et les seuils : `config/evals.yaml`, `domain_packs/*/evals/golden.jsonl` ;
- les hooks et réglages de `.claude/` ;
- les principes de sécurité de l'Annexe D dans le prompt système ;
- le code du moteur d'apprentissage et de la porte eux-mêmes.

Raison : R3. Ces réglages n'appartiennent qu'à l'utilisateur, qui les change à la main.

**Porte de mise en ligne**
- Un challenger est comparé au champion sur les évals et le red teaming.
- Un challenger moins bon est rejeté. R9 tient : la porte ne baisse jamais un seuil et ne retouche
  jamais un golden set.
- Après promotion, une baisse des métriques en production déclenche un retour automatique au
  champion.
- Marge de promotion, métriques et fenêtre du retour arrière, taille minimale d'échantillon :
  `A_DEFINIR` (phase 7).

**Mode public** (phase 8)
- Contributions anonymisées par Presidio.
- Utilisateurs isolés : aucune donnée d'un utilisateur n'atteint un autre.
- Information des utilisateurs : leurs échanges améliorent le service (RGPD).
- Quotas par utilisateur, qui protègent le budget LLM de l'utilisateur.

**Premières briques en phase 1** (ajout de périmètre approuvé par l'utilisateur)
- Deux événements s'ajoutent à l'Annexe C.3 : `ERROR` et `FEEDBACK`. Les entrées existantes
  restent valides ; la chaîne n'est pas modifiée.
- `ERROR` (acteur `orchestrator` ou `policy`) : un enregistrement structuré par type d'erreur,
  avec des compteurs et des codes, jamais de texte (R6). Types : `verification`,
  `partial_answer` (limite par requête atteinte), `task_failed`, `budget_exceeded`, `judge_score`.
- `cerveau feedback <request_id> {bon|mauvais} [note]` : l'entrée `FEEDBACK` (acteur `owner`) ne
  garde que le verdict et des compteurs. La note, pseudonymisée sans table de retour, va dans
  `var/feedback/feedback.jsonl`, marquée non fiable. Elle reste hors du journal pour qu'un oubli
  par utilisateur (phase 8) n'oblige pas à casser la chaîne, dont `verify` contrôle chaque payload.
- En phase 1, rien ne lit ces enregistrements pour modifier CERVEAU : ils préparent la phase 7.

## Conséquences
- (+) CERVEAU progresse sans attendre une relecture ; ses erreurs deviennent des données
  mesurables dès la phase 1.
- (−) Le verrou repose sur les évals : un challenger peut sur-apprendre le golden set (loi de
  Goodhart). Il faudra des cas tenus à l'écart de l'apprentissage et le red teaming à chaque
  promotion.
- (−) En mode public, le retour d'un utilisateur peut chercher à empoisonner l'apprentissage. R5,
  l'anonymisation, les quotas et la porte limitent ce risque sans l'annuler.
- (−) Le noyau verrouillé doit l'être techniquement, pas seulement par convention : ACL Windows ou
  droits Unix (comme `config/live.yaml`, ADR-003) et refus dans le moteur d'apprentissage
  lui-même (phase 7).
- À confirmer par l'utilisateur : la section 11 réserve aussi la mémoire long terme aux faits validés par
  l'utilisateur ou produits par un outil déterministe. Des leçons apprises automatiquement y dérogent ;
  je propose de les garder à part des faits validés, avec source, confiance et date d'expiration,
  et lues comme des données.
