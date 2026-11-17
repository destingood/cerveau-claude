# ADR-010 — Pseudonymisation française avec presidio-analyzer seul

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
La section 13 impose Presidio avant tout envoi à un LLM ou à Langfuse ; R6 interdit toute donnée
sensible dans les logs. La réponse doit pourtant rendre les vrais noms à l'utilisateur : la
pseudonymisation doit être réversible, sans que la table ne quitte la mémoire. Faits vérifiés le
2026-10-18 :
- Presidio 2.2.364 ne fournit aucun recognizer français ; il faut un moteur spaCy `fr`
  (`fr_core_news_md` 3.8.0, LGPL-LR, compatible spaCy `>=3.8.0,<3.9.0`) et nos recognizers ;
- `presidio-anonymizer` 2.2.364 impose `cryptography>=48.0.1,<49` ; pip-audit signale
  `cryptography` 48.0.1 (PYSEC-2026-3554, corrigé en 49.0.0 ; PYSEC-2026-3552, corrigé en 50.0.0).
  Il n'utilise `cryptography` que pour ses opérateurs AES, dont nous n'avons pas besoin.

## Options
1. **presidio-analyzer + presidio-anonymizer** : plan initial ; bloqué par la vulnérabilité, sauf
   à forcer `cryptography>=50` contre la borne déclarée (compatibilité non garantie).
2. **presidio-analyzer seul + remplacement maison** : la détection reste Presidio ; le
   remplacement (tri des intervalles, résolution des chevauchements, `<PERSONNE_1>`…) tient en
   quelques dizaines de lignes testées.
3. **Autre moteur (regex seules)** : sans NER, les noms et lieux échappent.

## Décision
Option 2. `core/guardrails/` construit un `AnalyzerEngine` sur spaCy `fr_core_news_md`, avec
PERSON et LOCATION (NER), EMAIL, IBAN et CREDIT_CARD (recognizers Presidio déclarés `fr`) et
FR_PHONE, FR_NIR (clé de contrôle) et IP (recognizers maison). Seuil de score lu dans
`config/guardrails.yaml` (proposé 0,5, à valider par l'utilisateur). Un même texte reçoit toujours le
même pseudonyme dans une requête ; la table vit en mémoire le temps de la requête et ne sert qu'à
la ré-identification finale. Le journal ne garde que le nombre d'entités par type.

## Conséquences
- Plus simple : `cryptography` passe en 50.0.2 ; une dépendance de moins.
- Plus difficile : le remplacement est notre code (tests de chevauchement et de réversibilité).
- Limites connues : la NER rate des noms rares et en marque à tort ; SIREN / SIRET et plaques au
  backlog ; la RAM de spaCy sera mesurée et publiée.
- Réversible : oui ; `presidio-anonymizer` pourra revenir quand sa borne `cryptography` sera levée.
