---
name: evals-claude-code
description: Passe un golden set de pack dans Claude Code, sans API (ADR-074) - le modèle de la session répond à chaque cas exporté, un sous-agent d'un autre modèle (juge-evals) note, le code contrôle et calcule le score. À lancer quand l'utilisateur le demande, jamais de soi-même.
argument-hint: "<pack> [nombre de cas]"
disable-model-invocation: true
---
# Banc Claude Code : $ARGUMENTS

Budget API à 0 € : ce banc n'appelle aucune API et ne lance jamais `cerveau eval --live`. Le
modèle de cette session répond ; le sous-agent `juge-evals` (`model: sonnet` dans son fichier)
juge ; le code note (R1). Un modèle ne se juge jamais lui-même : si cette session tourne sur
Sonnet, arrête-toi et demande à l'utilisateur de changer le `model` de `juge-evals` (haiku) ou
de lancer le banc depuis une session Opus.

1. **Exporter.** Le premier argument est le pack (`generaliste` par défaut), le second le nombre
   de cas (tous les cas exportables par défaut). `--modele-reponse` est l'identifiant du modèle
   de cette session, tel que ton environnement le donne :
   ```bash
   uv run cerveau evals exporter --pack <pack> --modele-reponse <ton modèle> [--limite N] [--cas <id>]
   ```
   Note l'identifiant du run (`AAAAMMJJTHHMMSS-xxxxxx`) et les cas exclus avec leur raison.
   Seul le `golden.jsonl` du pack est lu : un fichier de cas candidats n'est jamais passé.
2. **Répondre.** Pour chaque fichier `var/evals/claude-code/<run>/questions/<cas>.md`, lance le
   sous-agent `repondant-evals` (il tourne sur le modèle de cette session, dans un contexte neuf)
   avec ce seul message : « Réponds à la question du fichier <chemin>. » Un sous-agent par
   question. Toi-même, ne lis ni le golden set, ni les questions, ni les réponses : ce que tu
   aurais lu ne doit pas passer dans les réponses.
3. **Préparer le juge.**
   ```bash
   uv run cerveau evals preparer-juge <run>
   ```
   Une réponse absente ou invalide est listée « non jugé » ; elle compte comme un échec. Ne la
   corrige pas après coup : relance un nouveau run.
4. **Juger.** Pour chaque fichier `juge/jNN.md` listé, lance le sous-agent `juge-evals` avec ce
   seul message : « Juge le fichier <chemin>. » Un sous-agent par fichier, **sans paramètre
   `model`** (il remplacerait celui du fichier de l'agent). Ne lis pas, n'écris pas et ne modifie
   pas un verdict toi-même.
5. **Noter.**
   ```bash
   uv run cerveau evals noter <run> [--report evals/reports/claude-code-<pack>-<AAAA-MM-JJ>]
   ```
   `--report` seulement si l'utilisateur veut garder le rapport dans le dépôt.

Interdits : modifier un cas, une grille, un prompt ou un seuil pour faire passer un cas (R9) ;
retenir, dans la mémoire ou ailleurs, ce que disent les cas tenus à l'écart (`held_out`) ou leurs
verdicts : la couche apprise ne les voit jamais (ADR-011, ADR-065).

Réponds par un tableau : cas, tenu à l'écart (oui/non), réussi, score du juge, contrôles en échec ;
puis les portes du rapport, et rappelle ce que le banc ne mesure pas (ni outils, ni routage, ni
défenses du code de l'orchestrateur ; le modèle de la session, pas celui de `config/models.yaml`).
