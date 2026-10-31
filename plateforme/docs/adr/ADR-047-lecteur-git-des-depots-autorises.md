# ADR-047 — Lecteur git des dépôts autorisés (plugin `code_repo`)

- Statut : proposé (liste blanche, exclusion de CERVEAU et absence de jeton validées par E2 et E6
  du complément de plan de P3)
- Date : 2026-10-22
- Phase : 6 (P3a, pack Code)

## Contexte
Le pack Code (P3a) lit l'historique, les différences et les fichiers d'un ou deux dépôts
personnels de l'utilisateur (E2), au niveau N0. Un dépôt est du contenu externe (R5) : son
`.git/config` et ses attributs peuvent nommer des programmes que git lance seul (diff externe,
pilote de diff, textconv, filtres smudge et clean, fsmonitor, pager, vérificateur de signature,
récupération paresseuse depuis un remote « promisor »). Ses fichiers peuvent contenir des secrets
(R6) ou des caractères bidirectionnels qui font lire au LLM autre chose que le code réel
(« Trojan Source »). Le dépôt CERVEAU lui-même ne doit jamais être lu par ce plugin (E2).

Faits vérifiés le 2026-10-22 :
- l'option `git --no-lazy-fetch` et la variable `GIT_NO_LAZY_FETCH` apparaissent dans git 2.45.0
  (notes de version 2.45.0 ; absentes de `Documentation/git.txt` au tag v2.44.0, présentes au tag
  v2.45.0) ;
- l'image GitHub Actions `ubuntu-24.04` (version 20261012.334.1) fournit git 2.55.0
  (`actions/runner-images`, `Ubuntu2404-Readme.md`) ; le poste de l'utilisateur a git 2.56.0.windows.2 ;
- avec git seul et le même environnement réduit, le dépôt hostile des tests déclenche le diff
  externe ou le pilote de diff, textconv, le vérificateur de signature (`log.showSignature`),
  fsmonitor (`git status`) et le filtre smudge (`checkout`).

## Options
1. **git en ligne de commande, durci, lecture des objets seulement** : aucune dépendance Python
   nouvelle ; git (GPL-2.0) est lancé comme programme externe, sans édition de liens (R14).
2. **Bibliothèque git** (dulwich, pygit2/libgit2) : pas de programme externe, mais une dépendance
   de plus à auditer ; licences à vérifier avant tout choix (R14, [A_VERIFIER]).
3. **Lecture directe du dossier de travail** : simple, mais lit les fichiers non suivis (les
   vrais `.env`), suit les liens symboliques hors du dépôt et ne donne pas l'historique.
4. **Extraction par `git checkout` ou `git archive`** puis lecture : les filtres smudge du dépôt
   s'appliquent à l'extraction.

## Décision
Option 1, avec ces règles, toutes testées (`tests/test_code_*.py`, `plugins/code_repo/tests/`) :
- **Liste blanche** : `config/code.yaml`, clé `repositories` ; `A_DEFINIR` bloque les trois outils
  (R7). Le LLM ne donne qu'un identifiant de la liste, jamais un chemin ; la liste est relue à
  chaque appel.
- **CERVEAU exclu**, dans la configuration et à l'exécution : refus d'un dossier égal, parent ou
  enfant de la racine CERVEAU, puis d'un dépôt dont le `git-dir`, le `common-dir` ou le dossier
  `objects` recouvre CERVEAU (worktree de CERVEAU placé ailleurs) ; objets empruntés
  (`objects/info/alternates`, donc un clone partagé) refusés ; le dossier listé doit être la
  racine de son dépôt. Un clone ordinaire de CERVEAU (`git clone`, ou `--local` avec liens
  physiques) a ses propres objets : il n'est pas reconnu et reste lisible s'il est listé. La
  comparaison des commits racines est prévue pour P3b (backlog, revue de sécurité de P3a).
- **Objets seulement** : `rev-parse`, `log`, `diff` entre deux commits, `ls-tree`, `cat-file`.
  Jamais le dossier de travail, ni `checkout`, ni `archive`, ni `status` ; aucune commande lancée
  n'écrit dans le dépôt.
- **git durci** (`core/code/git.py`) : sans shell ; environnement réduit à `PATH`, `SYSTEMROOT`,
  `TEMP`, `TMP`, sans configuration système ni globale, sans attributs système, sans objets de
  remplacement, sans invite ; options `--no-pager`, `--no-lazy-fetch`, `--no-optional-locks`,
  `core.fsmonitor=false`, `log.showSignature=false` ; `--no-ext-diff` et `--no-textconv` pour
  chaque `diff` (`--numstat` puis `-p`) ; chemins littéraux (`GIT_LITERAL_PATHSPECS`, `:(exclude,literal)`) ;
  révisions filtrées puis passées après `--end-of-options` ; délai de 10 s ; sorties bornées en
  octets, coupure signalée.
- **Sorties** : fichier sensible (`.env*` sauf `.env.example`, clés et trousseaux, fichiers
  d'identifiants, `secret`/`secrets`/`credentials` sans extension ou avec une extension de
  données, `.docker/config.json`, état et variables Terraform) jamais lu, seulement nommé comme
  retenu ; dans `repo_diff`, le patch n'est pas montré si un nom de fichier n'est pas en UTF-8 ou
  si la liste des fichiers est tronquée, et toute section du patch dont le chemin est sensible ou
  illisible est retirée (défense en profondeur derrière les exclusions) ; secrets et blocs de
  clés privées (PEM, OpenSSH, OpenPGP) masqués et comptés ; caractères invisibles et bidirectionnels montrés `⟨U+XXXX⟩` ; tranches de
  200 lignes au plus ; tout le texte reste une donnée (R5).
- **Version de git** : 2.45.0 au moins. Avec un git plus ancien, `--no-lazy-fetch` est inconnu,
  chaque appel échoue et l'outil refuse : l'échec est fermé.
- **Autonomie** : trois outils en lecture (`readOnly`, `openWorld: false`), plafond N1, pack à N0.

## Conséquences
- Les outils restent bloqués tant que l'utilisateur n'a pas rempli `repositories`.
- Le pager n'est pas testable sans terminal : git ne le lance que si sa sortie est un terminal, et
  ici elle est toujours un tube ; `--no-pager` reste passé.
- Les commandes de lecture ne déclenchent ni hook git, ni ramasse-miettes, ni accès réseau ; une
  nouvelle commande git ajoutée au lecteur exige un nouveau cas dans le test du dépôt hostile.
- La liste des options désactivées est à revoir aux versions majeures de git (backlog).
- Réversible : le plugin est isolé ; retirer `code_repo` du pack suffit.
