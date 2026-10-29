# 🧠 Cerveau pour Claude Code

Une mémoire persistante pour Claude Code, faite par Lucas : Claude se souvient de toi, de tes projets, de tes
décisions et de ce qu'il a appris, d'une session à l'autre.

- **Au démarrage** de chaque session : l'essentiel de ta mémoire et du projet courant est injecté.
- **À chaque message** : les souvenirs et fichiers vraiment liés remontent tout seuls (fautes de frappe, écriture
  phonétique et synonymes compris).
- **En fin de tâche** : Claude note ce qui mérite d'être retenu (décisions, pièges, préférences).
- Cartes de tes projets (fichiers clés, où est défini quoi), à-faire datés, vue 3D, serveur MCP.
- **Nouveau — le mode éco** : moins de tokens sans rien perdre — les sorties de commandes très longues vont dans un fichier (aperçu seul dans la conversation), la conversation est résumée plus tôt, et `brain eco` liste les plugins jamais utilisés ; posé une fois au démarrage, `brain eco --annuler` pour revenir.
- **Nouveau — encore moins de tokens** : les sorties de commandes sont compactées avant d'arriver à Claude, le texte
  injecté au démarrage, à chaque message et dans la liste des outils est plus court ; `brain recall --pourquoi` dit
  pourquoi un souvenir n'est pas remonté ; `brain tokens` donne aussi le coût au tarif de l'API, en dollars ; et la
  skill `/cerveau:securite` relit le code exposé (site, API, formulaire) avant de le livrer.
- **Nouveau — rappel plus précis, filtres appris, style concis** : un souvenir rappelé montre les phrases qui répondent
  à ton message, pas seulement son début ; `brain compact --decouvrir` repère le bruit qui revient dans les sorties de
  tes commandes et `brain compact --apprendre <commande> --enregistrer` en fait un filtre appliqué tout seul (erreurs
  gardées) ; une liste JSON arrive en tableau, une sortie déjà lue dans la session renvoie vers la première ; et le
  style de réponse « concis » (l'action d'abord, sans préambule ni récapitulatif) : `/output-style cerveau:concis`.
- **Nouveau — tout s'active seul, sans commande** : le style concis devient ton style par défaut (sauf si tu en avais
  déjà choisi un ; `brain config style off` pour revenir) ; l'entretien du jour repère le bruit qui revient dans les
  sorties de tes commandes et en fait un filtre, annoncé une fois (erreurs toujours gardées ; `brain compact --oublier
  <commande>` pour le retirer) ; et Claude ingère tout seul les sources déposées dans le wiki et tranche les points du
  rêve (ce qui est sûr est appliqué, un doute est laissé et cité, rien n'est inventé).
- **Nouveau — le cerveau en wiki** (le « LLM Wiki » d'Andrej Karpathy) : `brain wiki init <dossier>` range chaque
  souvenir dans une page Markdown d'un dossier que tu ouvres dans Obsidian (idéalement un dépôt GitHub privé). Tu y
  déposes des sources (articles, PDF, transcriptions, notes) ; Claude les lit et tient à jour des pages de synthèse
  (sources résumées, entités, concepts, sujets, analyses), liées entre elles. Rien ne change tant que tu ne le lances pas.
- **Nouveau — la veille automatique** : `brain auto --installer` pose une tâche planifiée (Windows ; ailleurs, une
  ligne cron à ajouter) qui tient le cerveau à jour toutes les 30 min sans ouvrir Claude, et sans fenêtre : notes du
  jour d'Obsidian mémorisées, wiki synchronisé avec GitHub, page Cerveau et carte réécrites, entretien et sauvegarde du
  jour. Zéro token. `brain auto --etat` pour voir la dernière passe, `brain auto --retirer` pour l'enlever.

- **Nouveau — le cerveau commun** : si tu le veux, ce que tu apprends (recherches, savoir, projets que tu déclares
  communs) nourrit aussi le cerveau de tes amis, et le leur nourrit le tien, presque en temps réel. Claude te le
  propose ; rien ne part avant ton oui, et jamais ton profil, tes préférences ni rien de personnel ou de sensible.

- **Nouveau — le cerveau e-commerce** (skill `/cerveau:ecommerce`) : un expert pour lancer ou faire décoller une
  boutique en ligne sans publicité et avec des outils gratuits — diagnostic, offre et marges, site et tunnel de vente,
  premiers clients, vidéo courte et algorithmes, SEO, GEO (ChatGPT, Perplexity, AI Overviews), e-mails, gestion,
  conformité. Il agit lui-même sur ta boutique et tes outils Google (fiches, SEO, flux), puis te dit ce qu'il a fait
  et comment l'annuler ; il te demande seulement pour l'argent (prix, promos) et les envois aux clients. Il publie sur
  ta page Facebook, ton Instagram pro ou YouTube une fois l'accès officiel branché, après ton « oui » sur le lot de la
  semaine ; ailleurs, il prépare et tu cliques. Le contexte de chaque boutique reste dans ta mémoire, chez toi.

- **Nouveau — Perplexity** (skill `/cerveau:perplexity`) : dis « branche perplexity » et Claude ajoute le serveur officiel de Perplexity sur ton PC, puis te guide pour te connecter avec ton propre compte (payant à l'appel, à ta charge, rien de partagé). Ensuite, « cherche sur perplexity … » : recherche web filtrée par sites, langue, pays ou date, ou recherche approfondie avec sources. Sans ce mot, Claude garde sa recherche web intégrée, sans frais.
- **Nouveau — le suivi de tes boutiques** : le cerveau suit chaque boutique comme un copilote. Un plan décollage daté
  (72 h, 14 jours, 30-60-90) dont les échéances te sont rappelées ; chaque lundi, les chiffres de la semaine avec un
  test statistique qui dit si une hausse est réelle ou du hasard, le canal qui rapporte le plus par heure et le goulot
  à traiter ; des audits gardés en historique (ce qui a été corrigé) avec contrôle de conformité légale, pages du site
  et vitesse ; un bilan avec trois priorités. Outils inclus : audit de tout le catalogue et flux Google Shopping,
  relecture des textes avant publication (allégations interdites, fausse urgence), comparaison des marges entre ta
  boutique, Etsy, Vinted ou TikTok Shop, modèles de textes prêts à adapter.

Tout reste chez toi, dans `~/.claude/brain` — ou dans ton wiki, sur ton PC et, si tu le choisis, dans ton dépôt
GitHub privé. Rien n'est envoyé ailleurs, sauf ta part publique si tu rejoins le cerveau commun ; chacun garde sa
propre mémoire.

## Prérequis

**Python 3.10 ou plus, et la commande `python`** : les hooks du plugin la lancent ; sans elle, rien n'est enregistré, sans aucune erreur visible.
- macOS : `mkdir -p ~/.local/bin && ln -sf "$(command -v python3)" ~/.local/bin/python`, puis redémarre Claude Code · Debian/Ubuntu : `sudo apt install python-is-python3` · Windows : réinstalle Python depuis python.org en cochant « Add python.exe to PATH ».
- **Vérifier que le cerveau enregistre**, après ton premier message : `python ~/.claude/brain/brain.py doctor` puis `python ~/.claude/brain/brain.py journal` (macOS sans `python` : `python3`) ; si ce fichier n'existe pas, les hooks ne tournent pas : diagnostic direct avec `python3 "$(ls -d ~/.claude/plugins/cache/*/cerveau/*/ | tail -1)brain.py" doctor`.

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

Tu avais déjà le cerveau en installation classique (code dans `~/.claude/brain`) ? Rien de plus à faire : au premier
démarrage, le plugin prend le relais tout seul — souvenirs gardés, ancien code archivé dans
`~/.claude/brain/archives`, anciens hooks retirés, mises à jour automatiques activées.

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
« retiens que … », ou tape `/brain`. Vue 3D de ta mémoire : `~/.claude/brain/cerveau.html` (souvenirs, projets,
le cerveau e-commerce avec ses fiches et ses outils, et tes boutiques suivies).

Pour une boutique : « fais décoller ma boutique », « trouve-moi des clients sans pub », « audite mon site », « quel
produit vendre ? », « fais le point de la semaine » — le cerveau e-commerce prend le relais tout seul (ou tape
`/cerveau:ecommerce`) et tient le suivi de chaque boutique (« où en est ma boutique ? »).

Avec un wiki : « ingère cet article », « range cette réponse dans le wiki », « fais le point sur le wiki » (contrôle de
santé : pages à créer, sources en attente, pages dépassées). Le schéma que suit Claude est dans le `CLAUDE.md` du wiki :
fais-le évoluer avec lui.

## Le cerveau commun (avec tes amis)

1. Lucas t'invite sur le dépôt GitHub privé du cerveau commun : accepte l'invitation (e-mail, ou
   https://github.com/notifications). Dépôt : `destingood/cerveau-commun`.
2. Au démarrage suivant, Claude te le propose et te montre ce qui partirait. Rien ne part avant ton oui ; la première
   fois, une fenêtre de connexion à GitHub peut s'ouvrir.
3. Ensuite tout est automatique : ce que tu apprends part une quinzaine de secondes après (le temps de corriger ou de
   dire « garde ça pour moi »), ce que tes amis apprennent arrive à ton message suivant (moins de 2 minutes), marqué 🤝
   et en lecture seule.

Ne part jamais : ton profil et tes préférences, le contenu sensible (santé, argent, intimité, identité, opinions, mots
de passe), les personnes, tes documents personnels, tes projets tant que tu ne les déclares pas communs (« partage le
projet X avec les amis »), le texte de tes sessions. Coordonnées, secrets, chemins de fichiers et liens d'accès
(documents partagés, invitations, réunions) sont retirés du reste. « Garde ça pour moi » : la page reste privée.
`brain commun` montre l'état ; `brain commun quitter` pour en sortir (tes pages sont retirées).

Pour le lancer (Lucas) : crée sur GitHub le dépôt **privé et vide** `destingood/cerveau-commun`,
invite tes amis (Settings → Collaborators → Add people), puis rejoins-le le premier (dis oui quand Claude le propose).

## Désinstaller

`/plugin uninstall cerveau@cerveau`. Tes souvenirs restent dans `~/.claude/brain` (supprime ce dossier pour tout effacer).

Version 8.15.1.
