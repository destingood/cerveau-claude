# Couche apprise de CERVEAU (`learned/`)

Ce dossier contient ce que CERVEAU apprend de ses erreurs et des retours (ADR-011, ADR-065).
Il est versionné (décision D3 de Lucas, 29/10/2026) : chaque changement se relit dans git.

## Liste fermée

Seuls ces fichiers sont lus et écrits, pour chaque pack de domaine déclaré :

```
learned/<pack>/lessons.md    leçons apprises (méthode, pièges)
learned/<pack>/examples.md   exemples de bonnes réponses
```

Tout autre chemin est refusé (`core/learning/layer.py`), de même qu'un chemin qui passe par un lien
symbolique ou une jonction.

## Ce que la couche ne peut pas faire

- Elle est **non vérifiée** : le prompt l'annonce comme telle, et elle ne change aucune règle.
- Le **noyau est verrouillé** : règles R1 à R16, garde-fous, seuils, autonomie, `config/`,
  `governance/` et prompts système ne s'apprennent pas.
- Une section de plus de 4 000 caractères, avec des caractères de contrôle, des accolades de
  gabarit ou des signaux d'injection (R5) est refusée ; le prompt n'est alors pas construit
  (échec fermé).
- Un changement n'entre en service qu'après la porte champion / challenger
  (`cerveau learn gate`) : jeu tenu à l'écart de 20 % du golden, aucune régression de
  comportement ni de red team, évals réelles (D4).

## Protection

Les droits d'écriture sur ce dossier (ACL Windows) sont à poser par Lucas (backlog B77).
