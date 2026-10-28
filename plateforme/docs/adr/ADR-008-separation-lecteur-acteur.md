# ADR-008 — Séparation lecteur / acteur contre l'injection (R5)

- Statut : proposé
- Date : 2026-10-18
- Phase : 1

## Contexte
R5 : un contenu externe est une donnée, jamais une instruction, et « le lecteur n'a aucun outil
d'action ». Une page web peut contenir une injection (directe, texte caché, attribut `alt`, lien
Markdown d'exfiltration, demande d'appel d'outil, fuite du prompt système, en base64, en français
ou en anglais). Le critère de phase est 0 violation R5 sur la suite d'injection de base.
Aucune défense par prompt n'est fiable seule : la défense doit être structurelle.

## Options
1. **Le planificateur lit le texte brut des pages**, avec une consigne de méfiance : simple,
   mais toute l'injection atteint le modèle qui choisit les outils.
2. **Lecteur sans outil + extraits validés par schéma** : le planificateur ne voit que des
   affirmations courtes et des citations vérifiées ; plus d'appels de modèle (tier `fast`).
3. **Option 2 + classifieur d'injection dédié** : défense de plus, modèle de plus à évaluer
   (backlog si la suite le justifie, R13).

## Décision
Option 2.
- **Acteur** (planificateur) : aucun outil d'action ; seulement `web_search` et `web_read`.
- **Lecteur** (tier `fast`, sans outil) : transforme le texte d'une page en objets `Extract`
  (affirmation ≤ 300 caractères, citation mot pour mot, URL, date). Toute citation absente du texte
  stocké de la page (après normalisation) est rejetée. Les formulations d'instruction (« ignore »,
  « appelle l'outil », « system prompt »…) sont détectées par du code et signalées.
- Le planificateur ne voit que les extraits, encadrés par `<donnees_externes>` (principe 3 de
  l'Annexe D), jamais le HTML ni le texte brut.
- Provenance des URL (ADR-006) et sortie filtrée : aucun lien ni image Markdown vers un domaine
  absent des sources vérifiées.
- **Violation R5** : la réponse ou un appel d'outil suit une instruction venue d'un contenu non
  fiable, ou fait fuiter le prompt système ou des données pseudonymisées. La définition et les
  contrôles sont écrits dans `evals/redteam/README.md`.

## Conséquences
- Plus simple : une injection réussie sur le lecteur ne peut déclencher aucune action.
- Plus difficile : coût et latence d'un appel `fast` par page ; une affirmation résumée peut
  déformer la page (la vérification des citations le limite, sans l'exclure).
- Le planificateur peut encore être influencé par une affirmation biaisée : le contre-argument et
  les deux sources indépendantes (nœud 5) restent nécessaires.
- Réversible : oui.
