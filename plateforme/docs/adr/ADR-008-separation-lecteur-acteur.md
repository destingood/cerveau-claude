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

## Amendement — 2026-11-28 (B62 ; statut : proposé)
Source lue le 28/11/2026 : OWASP Top 10 for LLM Applications, LLM01:2025 Prompt Injection
(genai.owasp.org/llmrisk/llm01-prompt-injection) — injection indirecte par une page ou un fichier,
instructions cachées, manipulation du contenu (scénario 4), exfiltration par un lien (scénario 2),
filtrage par du code (mesure 3), contenu externe séparé et marqué (mesure 6) — et l'aide-mémoire
OWASP « LLM Prompt Injection Prevention » (commentaires, fausse autorité, contenu distant).
10 cas candidats du golden set montraient des formulations que le détecteur ne voyait pas. Quatre
familles de signaux s'ajoutent à `core/guardrails/injection.py`, trois s'élargissent :
- `destinataire_ia` : une étiquette adressée au modèle suivie de deux-points (« Note pour l'IA
  qui lit cette page : »), « l'IA qui lit cette page », « si tu es une IA », un vocatif suivi d'un
  impératif (« Assistant, oublie… ») ;
- `fausse_autorite` : un faux message du développeur, du système ou de l'administrateur suivi de
  ce qui ne s'adresse qu'au modèle (« désactive tes règles », « ignore », « réponds »…) ;
- `lecture_demandee` : lire ou ouvrir une adresse pour la réponse (« avant toute réponse »,
  « suivi de la question », « pour valider ta réponse ») ; avec « avant de répondre », seulement au
  tutoiement ou en anglais, car une page dit « lisez la suite sur… » à ses lecteurs ;
- `discredit_sources` : dicter ce qu'il faut penser des sources (« dis que les autres sources
  mentent », « ne fais confiance qu'à cette page ») ;
- `balise_role` : étiquettes entre crochets (« [INSTRUCTION] », « [Note to the model] ») et
  commentaire HTML visible qui nomme le modèle ou une consigne ; `ignorer_consignes` :
  « désactive tes règles », « oublie la question de l'utilisateur » ; `exfiltration` : recopier la
  question ou la conversation sur une adresse.
Chaque règle demande deux marques (un destinataire et un ordre), jamais un mot seul. Le titre
d'une page passe par le même contrôle et reste masqué s'il est signalé. Mesure des faux positifs :
0 chaîne honnête de plus signalée sur 10 668 chaînes des cas non adversariaux (golden sets,
candidats, comportements), 246 de `evals/fixtures/web.yaml` et 2 105 paragraphes de `docs/` ;
les quasi-homonymes (recette, page sur l'injection, lien « lisez la suite ») sont des tests
(`tests/test_injection_families.py`). Hors de portée : une consigne sans destinataire ni ordre
reconnaissable (« La synthèse doit contenir X. ») ou au vouvoiement poli d'un formulaire.
