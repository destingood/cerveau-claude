# ADR-070 — Les règles de `verifier` : aucun chiffre inventé ne passe (R1)

- Statut : proposé
- Date : 2026-11-26
- Phase : plan du cerveau, Bloc B, pont MCP, point 1 (étape B1.1, validée par l'utilisateur le 26/11)

## Contexte
L'outil `verifier` du pont MCP (ADR-069) relit chaque chiffre et chaque date d'un brouillon contre
les sorties d'outils de la session (`core/verification/`). L'audit du 20/11 (plan, annexe G-1,
G-9, G-10) l'a pris en défaut : 16 brouillons inventés sur 21 passaient, 7 brouillons justes sur
18 étaient refusés, et rien n'allait au journal. Ses 39 brouillons n'ont pas été gardés ; un
corpus refait (`tests/test_verifier_corpus.py`, 21 + 18 brouillons avec leurs sorties d'outils)
donne, avant ce changement, 5 refus sur 21 et 9 acceptations sur 18.

Causes : « 10'000'000 € » lu comme trois nombres (10, 000, 000), chacun trouvé ailleurs ; un zéro
dont la tolérance d'arrondi couvre toute source sous la moitié de son échelle (« 0 Md€ ») ; un
chiffre d'une page ou d'un résultat de recherche accepté comme une VaR ; un pourcentage accepté
contre une fraction écrite sans % (« 0,031 % » contre 0.031) ; « Étape 2 », la date du jour et
les chiffres de l'utilisateur sans preuve.

## Options
1. **Durcir la lecture et l'appariement des nombres, pour tous** (pont, orchestrateur, comité,
   évals), et ajouter au pont seul ce qui demande sa session. Retenue.
2. Tout faire dans le pont seulement : le même trou resterait dans l'orchestrateur et le comité.
3. Exiger une figure d'outil pour tout chiffre : la recherche web et juridique ne pourrait plus
   citer une page. Écartée.

Aucune dépendance nouvelle (bibliothèque standard), coût nul.

## Décision
Pour tous les appelants (`numbers.py`) :
- un nombre groupé est un seul nombre : espaces de toute largeur (dont l'espace de chiffre),
  apostrophes `'` et `’` ; les caractères invisibles et le gras Markdown entre deux chiffres sont
  retirés ; un exposant collé fait partie du nombre (« 10⁶ » se lit 106, jamais 10) ;
- un arrondi garde l'ordre de grandeur : un zéro, avec ou sans échelle, demande une source nulle ;
  « 1 » n'arrondit pas 0,87 ; « 10 % » arrondit 9,62 % (une demi-unité vaut au plus 5 % du
  brouillon) ;
- contre un texte, un pourcentage s'apparie à un pourcentage, ou par sa fraction à une fraction
  écrite avec des décimales : « 0,031 % » ne s'apparie plus à 0.031, ni « 100 % » à « 1 » ;
- un petit entier qui nomme une partie n'est pas un nombre : après étape, phase, section,
  chapitre, partie, annexe, tableau, figure, scénario, option, question, step, chapter, appendix,
  sans unité, échelle ni décimale. « article 1240 » reste vérifié.

Pour le pont (`trace(..., metrics=True, user=...)`, `Bridge.verify`) :
- un nombre présenté comme une mesure calculée (VaR, CVaR, volatilité, Sharpe, Sortino, Calmar,
  Treynor, drawdown ou perte maximale, bêta, tracking error, ratio d'information, TWR, MWR,
  rendement annualisé ou pondéré, TRI ; `metrics.py`) ne vient que d'une figure d'outil dont
  l'identifiant nomme cette mesure, la dernière nommée (`var/…/cvar_eur` est une CVaR) ;
- la date du jour est une preuve (horloge injectable, `Bridge.clock`) ;
- `citations_utilisateur` (10 phrases de 1 000 caractères au plus) : un nombre ou une date que
  rien d'autre ne porte y est accepté s'il y est écrit de la même façon (mêmes chiffres, échelle,
  pourcentage et devise, sans arrondi) et de même signe ; jamais pour une mesure, jamais contre
  une source contraire ; il est rendu à part (`utilisateur`, origine « utilisateur ») ;
- chaque appel de `verifier` écrit au journal une entrée `DECISION` : les comptes de nombres,
  dates, tracés, chiffres de l'utilisateur, sans source et de signe contraire, sans un nombre ni
  un mot du brouillon (R6, R11).

## Conséquences
- Corpus après ce changement : 21 refus sur 21, 18 acceptations sur 18 ; ces planchers ne
  peuvent que monter (R9).
- **Limite honnête des citations** : Claude les écrit lui-même ; le pont ne voit pas le message de
  l'utilisateur. Un chiffre inventé recopié dans `citations_utilisateur` passe, mais il reste
  visible dans la liste `utilisateur` et compté au journal ; il ne peut ni porter une mesure ni
  contredire une source. La vraie preuve viendra quand le pont recevra le message de
  l'utilisateur lui-même (B360).
- Une mesure se repère par un mot de mesure dans la même phrase, avant le nombre, ou juste après
  (« 18 % de volatilité »). Un mot plus loin, ou dans l'en-tête d'un tableau sur une autre ligne,
  n'est pas vu. Un autre nombre placé après le mot dans la même phrase est tenu à la même mesure :
  faux refus possible, corrigé en coupant la phrase. Une volatilité publiée par une page est
  refusée ; « rendement » et « performance » seuls ne sont pas des mesures (un taux d'OAT, un
  indice).
- `verifier` reste facultatif (G-9) : il devient obligatoire quand le pont recevra la réponse
  finale avant envoi, hors de ce changement (B360).
- L'orchestrateur, le comité et les évals gardent `metrics=False` : la règle des mesures leur
  sera appliquée après une mesure de leurs golden sets (R9, B361).
- Réversible : chaque règle a son test (`tests/test_verification_numbers.py`,
  `tests/test_verification_trace.py`, `tests/test_verifier_corpus.py`).
