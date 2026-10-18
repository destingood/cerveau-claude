# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par Lucas : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre.

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris).
- **En fin de tâche** : Claude note ce qui mérite d'être retenu (décisions, pièges, préférences).
- Cartes de tes projets (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.
- **Nouveau — le cerveau en wiki** (le « LLM Wiki » d'Andrej Karpathy) : `brain wiki init <dossier>` range chaque
  souvenir dans une page Markdown d'un dossier que tu ouvres dans Obsidian (idéalement un dépôt GitHub privé). Tu y
  déposes des sources (articles, PDF, transcriptions, notes) ; Claude les lit et tient à jour des pages de synthèse
  (sources résumées, entités, concepts, sujets, analyses), liées entre elles. Rien ne change tant que tu ne le lances pas.

Tout reste chez toi, dans `~/.claude/brain` — ou dans ton wiki, sur ton PC et, si tu le choisis, dans ton dépôt
GitHub privé : rien n'est envoyé ailleurs, et chacun a sa propre mémoire.

## Installer (une seule fois)

1. **Python 3.10 ou plus récent** : https://www.python.org/downloads/ — pendant l'installation, coche
   **« Add python.exe to PATH »**. Et **Git** (https://git-scm.com/download/win), si Claude Code ne te l'a pas déjà
   fait installer.
2. **Le plugin**, dans Claude Code (onglet Code de l'app Claude, ou terminal) :
   ```
   /plugin marketplace add https://github.com/destingood/cerveau-claude.git
   /plugin install cerveau@cerveau
   ```
3. **Les mises à jour automatiques**, une fois : `/plugin` → onglet des marketplaces → « cerveau » → *Enable
   auto-update*. Claude Code les laisse coupées par défaut pour un marketplace qui n'est pas d'Anthropic : c'est à
   toi de les autoriser.
4. **Redémarre Claude Code.** Au premier démarrage, le cerveau crée `~/.claude/brain`.

Variante sans commande, mises à jour automatiques comprises (`"autoUpdate": true`) : ajoute ceci à
`~/.claude/settings.json` (à fusionner avec ce qui s'y trouve déjà), puis redémarre Claude Code :

```json
{
  "extraKnownMarketplaces": {
    "cerveau": { "source": { "source": "git", "url": "https://github.com/destingood/cerveau-claude.git" }, "autoUpdate": true }
  },
  "enabledPlugins": { "cerveau@cerveau": true }
}
```

## Mises à jour

Une fois l'étape 3 faite, elles sont automatiques : quand une nouvelle version est publiée, Claude Code la récupère
pendant une session (quelques minutes après ton premier message) et l'applique au démarrage suivant. Tes souvenirs ne
sont jamais touchés par une mise à jour.

## Au quotidien

Rien à faire : parle normalement à Claude. Pour aller plus loin, demande-lui « qu'est-ce que tu sais sur … ? »,
« retiens que … », ou tape `/brain`. Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html`.

Avec un wiki : « ingère cet article », « range cette réponse dans le wiki », « fais le point sur le wiki » (contrôle de
santé : pages à créer, sources en attente, pages dépassées). Le schéma que suit Claude est dans le `CLAUDE.md` du wiki :
fais-le évoluer avec lui.

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version 8.0.0.
