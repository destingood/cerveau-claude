# ADR-004 — Langfuse v4 auto-hébergé, dans un profil Compose séparé

- Statut : proposé
- Date : 2026-10-17
- Phase : 0

## Contexte
La section 5 retient Langfuse auto-hébergé (partie MIT) pour les traces, coûts et scores ; la
phase 0 doit livrer `infra/docker-compose.yml` avec PostgreSQL + pgvector et Langfuse. Faits
vérifiés le 2026-10-17 :
- l'auto-hébergement documenté est la v4 (images `docker.langfuse.com/langfuse/langfuse:4` et
  `langfuse-worker:4`), et non la v3 attendue ; le SDK Python `langfuse` est en 5.0.2 (MIT) ;
- le Compose officiel comprend 6 services : web, worker, PostgreSQL, ClickHouse 25.12, Redis 7,
  MinIO (image Chainguard sans étiquette de version) ;
- licence : MIT, sauf les dossiers `ee/`, sous licence commerciale ; copyright ClickHouse, Inc. ;
- le dépôt `minio/minio` est archivé (dernier push le 2026-04-24) ; `redis:7` désigne la 7.4.11,
  sous double licence RSALv2 / SSPLv1 (`docs/licences.md`).

## Options
1. **Un seul profil** : tout démarre ensemble ; 7 conteneurs même quand seule la base sert.
2. **Deux profils** : `core` (PostgreSQL + pgvector) et `observability` (Langfuse et ses
   dépendances), le même serveur PostgreSQL hébergeant une base et un rôle `langfuse` distincts.
3. **Langfuse Cloud** : rien à opérer, mais les traces (prompts, données) quittent la machine ;
   contraire à l'esprit de R6 et à la règle Presidio de la section 13 ; coût.
4. **Reporter Langfuse à la phase 1** : écart au livrable de la phase 0.

## Décision
Option 2. Le Compose reprend le fichier officiel, réduit : télémétrie coupée, fonctions IA,
stockage cloud et SMTP absents, ports publiés uniquement sur 127.0.0.1 (le fichier officiel publie
le 9090 de MinIO sur toutes les interfaces), secrets obligatoires (`${VAR:?}`) lus depuis
`infra/.env`, généré par `infra/scripts/generate_secrets.py` sans affichage.

## Conséquences
- Plus simple : la base démarre seule (`--profile core`) ; Langfuse ne tourne qu'au besoin.
- Plus difficile : PostgreSQL partagé (une panne touche les deux usages) ; empreinte mémoire du
  profil `observability` non mesurée (Docker arrêté pendant la phase 0).
- Dette : images Langfuse épinglées à la version majeure seulement, MinIO sans étiquette ;
  remplacement de MinIO (archivé) et évaluation de Valkey à la place de Redis au backlog.
- Le premier compte Langfuse est créé par Lucas sur http://localhost:3000 ; fermer ensuite les
  inscriptions (backlog). Aucune clé Langfuse n'est créée par Claude Code.
- Réversible : oui ; les volumes de données sont nommés et séparés.
