# ADR-017 — Fournisseurs de données et heures de publication

- Statut : **proposé** (deux faits restent `A_VERIFIER` sur une vraie réponse de la BCE)
- Date : 2026-10-18
- Phase : 2

## Contexte
L'ADR-012 date chaque valeur de la base finance par son heure de publication (`published_at`).
Une lecture « connue à » une date ne voit que ce qui était publié à cette date. L'ADR-013 retient
trois fournisseurs légaux derrière une interface `MarketDataProvider` : des fixtures hors ligne,
les fichiers CSV exportés par Lucas et la BCE. Il reste trois questions.
- **L'heure de publication.** Aucun de ces fournisseurs ne donne l'heure exacte de publication
  d'une valeur. Une heure trop tôt ferait voir un cours avant sa publication, ce qui fausse tout
  backtest (R10).
- **Les révisions.** Une valeur corrigée par la source garde la date de la valeur d'origine.
  Datée ainsi, la correction apparaîtrait rétroactivement dans le passé.
- **La validation des entrées.** Un fichier ou une réponse est un contenu externe (R5) : il peut
  être faux, énorme ou piégé.

## Options
1. **Dater à la récupération** : `published_at` = l'heure de la synchronisation. C'est sûr, mais
   un historique récupéré aujourd'hui serait invisible pour tout backtest passé.
2. **Dater à la date de la valeur** (00:00) : c'est trop tôt, puisqu'un cours de clôture du jour
   paraîtrait connu dès minuit.
3. **L'heure de publication documentée, plus une marge, plafonnée à la récupération** ; une
   révision est datée à la récupération qui la découvre.

## Décision
L'option 3 est retenue. Le calcul est déterministe et se trouve dans `core/finance/providers/`
et dans `core/finance/sync.py`.

**Heure de publication.** `published_at` = min(heure documentée + `PUBLICATION_MARGIN`, heure
de la récupération). La marge vaut 1 h. L'heure documentée dépend de la donnée :

| Donnée | Heure documentée |
|---|---|
| Cours de clôture (CSV) | Clôture de la séance selon exchange-calendars (17:30 à Paris pour XPAR). Si la place est inconnue, ou si le jour n'est pas une séance, c'est la fin du jour à Paris. |
| Split, dividende (CSV) | Fin du jour d'annonce (`date_annonce`). Sans annonce, c'est 00:00 à Paris le jour ex. |
| Change de référence BCE (EXR) | 16:00, heure de Francfort, le jour de la cotation. |
| €STR (EST) | 08:00, heure de Francfort, le jour TARGET suivant la date de l'observation. |

Un cours de clôture daté d'une séance pas encore close à la récupération est refusé : ce n'est
pas un cours de clôture. Une annonce postérieure au jour ex, ou datée dans le futur, est refusée.

**Révisions.** Avant d'enregistrer, `sync` demande à la base quelles valeurs en révisent une
autre (`FinanceStore.revising`). Ces valeurs sont redatées à l'heure de la récupération : une
correction n'est connue qu'à partir du moment où CERVEAU l'a vue. Une valeur identique est
« inchangée » et n'ajoute aucune révision.

**Calendrier TARGET.** Le calendrier des séries de la BCE est calculé dans
`core/finance/calendars.py` : les week-ends, le 1er janvier, le Vendredi saint, le lundi de
Pâques, le 1er mai, le 25 et le 26 décembre. Il est défini à partir de 2002 ; avant, il est
refusé.

**Ce qui est accepté.**
- **CSV.**
  - Colonnes en français. Le séparateur « ; » active la virgule décimale ; sinon le séparateur
    est « , ».
  - Dates au format AAAA-MM-JJ ou JJ/MM/AAAA. Fichier en UTF-8, au plus 64 Mo.
  - Une colonne inconnue, manquante ou en double refuse le fichier. Une ligne fautive le refuse
    aussi. Deux lignes différentes pour la même clé le refusent ; un doublon exact est ignoré.
  - Un instrument absent du référentiel à la date de la valeur est refusé.
- **BCE.**
  - Https seulement, sans clé ni cookie, sans suivre de redirection. Délai de 30 s ; réponse de
    32 Mo au plus. Format `csvdata`, `detail=dataonly`.
  - Une série non demandée, ou un change contre une autre devise que l'euro, est refusé.

Une erreur cite le fichier, la ligne et la règle, jamais la valeur refusée (R5). Une
synchronisation refusée n'enregistre rien. Toute synchronisation est journalisée (R11) : une
entrée `TOOL_CALL` avec les comptes et les scores de qualité, ou une entrée `ERROR` avec le motif.
Les valeurs ne sont jamais journalisées.

**Accès.** La BCE passe par `config.require("data.ecb")` : une source désactivée dans
`data_sources.yaml` bloque la commande (code 2). Les fichiers CSV n'ont pas d'interrupteur : ce
sont les fichiers de Lucas, lus sur son disque, sans réseau. `cerveau finance sync` est le seul
écrivain de la base. Lucas la lance à la main ; les outils MCP ne font que lire.

**Catégories BCE.** Seuls `fx_reference_rates` et `estr` sont pris en charge. La courbe des taux
(`yield_curve`) est retirée de `data_sources.yaml`, qui devient ainsi plus prudent. Ses
conditions d'utilisation sont propres à cette série et plus restrictives ; Lucas doit les lire
avant de l'ajouter (D22).

## À vérifier
- **Colonnes `csvdata`** (`A_VERIFIER`). Les noms KEY, CURRENCY, CURRENCY_DENOM, TIME_PERIOD et
  OBS_VALUE viennent de la documentation de l'API ; ils sont à confirmer sur une vraie réponse.
  Un en-tête inattendu refuse la réponse, il ne la devine pas.
- **Sens de TIME_PERIOD pour l'€STR** (`A_VERIFIER`). C'est soit le jour de l'opération, soit le
  jour de la publication. La convention retenue, 08:00 le jour TARGET suivant plafonné à la
  récupération, ne fait jamais voir une valeur trop tôt dans les deux cas. Dans le second cas,
  elle la date un jour trop tard, ce qui reste prudent.

## Conséquences
- Un historique récupéré aujourd'hui est daté à ses heures de publication documentées : les
  backtests peuvent l'utiliser. Une correction n'apparaît qu'à partir de sa récupération.
- La marge d'une heure retarde chaque valeur d'une heure par rapport à sa vraie publication. Le
  biais est voulu : mieux vaut voir un cours une heure trop tard qu'une seconde trop tôt.
- Le change de référence de la BCE est publié « à titre d'information seulement ». Il sert à
  convertir et à valoriser, jamais à fixer le prix d'une transaction.
- Un nouveau courtier ou une nouvelle source se branche par un nouveau fournisseur, avec ses
  tests, sans toucher à la base (D4).
