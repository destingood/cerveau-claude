# ADR-072 — Une seule mémoire : la plateforme lit le cerveau du plugin, en lecture seule

- Statut : proposé (le périmètre est ta décision du 26/11/2026 ; le reste attend ta validation)
- Date : 2026-11-26
- Phase : plan, Bloc B « Une seule mémoire » (étape B2) ; ferme B58 ; suit la décision P6 du plan
  de parité (« pont en lecture vers le plugin d'abord ; module propre seulement si une mesure le
  justifie »)

## Contexte
La section 11 du méga-prompt demande une mémoire long terme faite de faits validés, jamais d'une
consigne venue d'un contenu externe, où chaque souvenir porte sa source, sa date, sa confiance et
sa fin de validité, et que `/oublier` efface sans trace. `core/memory/` était vide ; le nœud 1
« Contexte » donnait « aucune (mémoire désactivée en phase 1) » au prompt système. Le plugin
« cerveau » de Claude Code tient déjà cette mémoire (`graph.json`, ou un wiki Markdown dont
`graph.json` n'est que le cache), avec des dates de validité (`brainkit/temps.py`), une mise de
côté des souvenirs piégés (`meta.a_verifier`, `brainkit/garde.py`) et des domaines (décision E19 :
code, business, contenu, finance, infra, recherche, perso). Deux mémoires divergeraient (R12).
Contraintes : R5 (un souvenir est une donnée), R6 (aucun secret dans un prompt), R7, ADR-010
(pseudonymiser avant tout modèle), ADR-071 (aucun chemin dans un message rendu).

## Options
1. **Module propre** (Postgres, pgvector, section 11). Écartée pour l'instant (P6) : une seconde
   mémoire à remplir et à faire oublier deux fois ; aucune mesure ne la justifie.
2. **Copie périodique** du cerveau dans `var/`. Écartée : une copie garde un souvenir oublié
   jusqu'à la suivante, contraire à `/oublier`.
3. **Lecture seule du cerveau du plugin à chaque requête**, ses règles appliquées par la
   plateforme. Retenue : une seule source, rien à effacer de ce côté.
4. **Passer par le serveur MCP du plugin.** Écartée : aucun outil MCP de plus (ton choix), et le
   format se lit très bien avec la bibliothèque standard.

## Décision
- **Où** : `config/memory.yaml › brain_home`, sinon `BRAIN_HOME`, sinon `brain` sous le dossier
  de Claude Code (`CLAUDE_CONFIG_DIR` ou `~/.claude`), comme le plugin. Fichiers ouverts en lecture
  (`rb`) ; rien d'écrit, copié ni gardé d'une requête à l'autre. Un graphe ancien se lit tel
  quel, un champ inconnu est ignoré. Cerveau absent, illisible, de plus de 64 Mo ou mal formé :
  aucun souvenir, une raison sans chemin. Mode wiki : la plateforme ne lit pas les pages ; elle lit
  le cache seulement si la signature des pages (chemin, date, taille, celle du plugin) n'a pas
  bougé. Une page modifiée ou supprimée depuis, ou un wiki hors de portée, ne donne aucun souvenir
  jusqu'à la prochaine lecture du plugin.
- **Règles**, avant que rien ne sorte : souvenir actif (ni archivé, ni remplacé, ni fusionné), de
  ton cerveau (pas la page d'un ami), valable aujourd'hui (début écrit ou date de création, fin
  `valid_to` incluse, date de Paris) ; jamais `a_verifier` ; une source autre que toi
  (« utilisateur », « verifie ») repasse le détecteur de consignes de la plateforme
  (`core/guardrails/injection.py`), car un graphe ancien n'a pas eu la garde du plugin ; confiance
  au moins « moyen » (`min_confidence`) ; secrets masqués par le motif de la plateforme
  (`core/guardrails/secrets.py`, le même que les hooks). Ces deux dernières règles, les plus
  chères, ne passent que sur les souvenirs classés pour sortir, dans l'ordre : un souvenir écarté
  cède sa place au suivant (à 3 000 souvenirs, 52 ms par requête au lieu de 850).
- **Confiance** : celle du plugin (`meta.conf`, sinon selon la source : 0,95 vérifié ; 0,9 toi,
  Obsidian ; 0,8 wiki ; 0,7 Claude, MCP, import ; 0,6 automatique ; 0,5 déduit), en trois niveaux :
  élevée dès 0,85, moyenne dès 0,7, faible en dessous. L'importance n'y entre pas : un souvenir
  important n'est pas plus vrai ; elle départage le classement.
- **Périmètre** (ta décision du 26/11) : les domaines que `memory.yaml › packs` donne au pack
  traité, plus les préférences générales (type « feedback » sans domaine) ; « perso » jamais, sauf
  demande explicite (`cerveau memoire chercher --perso` ; l'orchestrateur ne le demande jamais).
  Le chargeur refuse « perso » dans `packs`. Un souvenir lié à plusieurs domaines dont « perso »,
  étiqueté `perso` ou rangé dans un projet « perso » reste personnel. Correspondance proposée :
  généraliste et juridique_fr : rien ; finance : finance ; recherche : recherche ; code : code,
  infra ; cyber : infra ; business : business, contenu. Un souvenir sans domaine qui n'est pas une
  préférence n'est vu par aucun pack.
- **Classement** : BM25 sur le titre (compté deux fois), le corps et les étiquettes, mots sans
  accents ni pluriel ; `top_k` souvenirs du domaine qui partagent un mot avec la requête, plus
  `preferences_k` préférences générales quelle que soit la requête.
- **Câblage** : le nœud 1 lit le cerveau une fois (pas sous kill switch) ; le domaine n'étant
  connu qu'au nœud 3, le tri, la pseudonymisation (celle de la requête, ADR-010) et le rendu s'y
  font. Chaque souvenir arrive dans `<donnees_externes>` (R5), sous une étiquette de mots fermés
  (type, source, confiance, date, fin) ; ni titre ni identifiant hors du bloc. Le journal n'en
  garde que des comptes (`memory` : mode, lus, rendus). Les évals et les tests ne lisent aucun
  cerveau : l'orchestrateur n'en reçoit un que de `cerveau ask`. `cerveau memoire chercher` montre
  ce qu'un pack lirait ; `cerveau config check` dit où est le cerveau et ce qu'il donne.

## Conséquences
- `/oublier` dans le plugin vaut pour la plateforme à la requête suivante ; en mode wiki, une page
  changée coupe la mémoire jusqu'à la prochaine session Claude Code (prudence, pas de relecture).
- La plateforme dépend du format du plugin, lu dans son code (`store.py`, `temps.py`,
  `garde.py`, `wikistore.py`) : un changement de format sans compatibilité ascendante (contraire
  à la règle du plugin) couperait la mémoire, jamais la plateforme.
- La section 11 veut des faits validés : par défaut, ce que Claude a noté (confiance moyenne) est
  lu, le déduit et l'automatique ne le sont pas. Lire seulement ce que tu as dit ou vérifié :
  `min_confidence: eleve`.
- Mesuré le 26/11 sur un cerveau d'essai de 3 000 souvenirs (2,1 Mo) : lecture, règles, tri et
  rendu en 51 à 73 ms. À mesurer : la qualité du classement (aucun jeu de requêtes ; B363).
- Réversible : `enabled: false` coupe tout ; aucune donnée n'est à migrer.
