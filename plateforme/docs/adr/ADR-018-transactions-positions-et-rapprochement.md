# ADR-018 — Transactions, positions et rapprochement

- Statut : **proposé**
- Date : 2026-10-18
- Phase : 2

## Contexte
Le plan de phase 2 (§4, F2) reconstruit le portefeuille de Lucas à partir de ses transactions.
Il fixe le format CERVEAU (date, compte, type, identifiant, quantité, prix, devise, frais),
l'import par la CLI, la valorisation en euros au change BCE et le rapprochement avec le relevé
du courtier. Il reste plusieurs choix à faire.
- **L'arithmétique.** Un solde calculé en nombres flottants ne tombe pas juste au centime. Une
  tolérance de rapprochement serait alors un seuil à régler (R7).
- **Les imports qui se recouvrent.** Lucas peut exporter tout l'historique chaque mois ou
  seulement le dernier mois. Ajouter chaque fichier au précédent compterait deux fois les
  opérations communes.
- **Le coût de revient** des titres, les splits, les dividendes et l'ordre des opérations d'une
  même journée.
- **La date de connaissance** d'une transaction (R10).

## Options
1. **Flottants, imports ajoutés bout à bout, tolérance réglable** : c'est simple, mais il faut un
   seuil de plus, et un export complet compte tout en double.
2. **Un import remplace tout l'historique du compte** : un export partiel effacerait le passé.
3. **Décimaux exacts ; un fichier fait foi, compte par compte, sur sa période ; aucune
   tolérance.**

## Décision
L'option 3 est retenue. Le code est dans `core/finance/portfolio.py`, `core/finance/brokers.py`
et `interfaces/cli/portfolio.py`. Les tables sont créées par la migration 2 de la base finance.

**Format CERVEAU.** Les colonnes sont `date, compte, type, identifiant, quantite, prix, devise,
frais`, plus deux colonnes facultatives : `montant` et `libelle`. Les règles de lecture sont
celles de l'ADR-017 : UTF-8, « ; » avec virgule décimale ou « , », un fichier lu en entier ou
refusé en entier. Les nombres sont des décimaux simples, sans exposant, avec au plus 15 chiffres
avant la virgule et 10 après.

| Type | Identifiant | Quantité | Prix | Frais | Effet |
|---|---|---|---|---|---|
| `achat` | instrument | titres | prix unitaire | facultatifs | titres +q ; cash −(q·p + f) |
| `vente` | instrument | titres | prix unitaire | facultatifs | titres −q ; cash +(q·p − f) |
| `dividende` | instrument | montant brut | vide | retenue et frais | cash +(q − f) |
| `frais` | instrument ou vide | montant | vide | vide | cash −q |
| `depot` | vide | montant | vide | vide | cash +q |
| `retrait` | vide | montant | vide | vide | cash −q |
| `change` | devise achetée | montant acheté | prix d'une unité | facultatifs | cash achetée +q ; cash de `devise` −(q·p + f) |

- `devise` est la devise du mouvement. Pour un achat, une vente ou un dividende, c'est la devise
  de l'instrument dans le référentiel à la date de l'opération ; une autre devise refuse le
  fichier. Un courtier qui convertit lui-même donne une ligne `change` puis la ligne de l'achat.
- `montant` (achat, vente, change) est le montant réellement débité ou crédité, frais compris.
  Quand il est donné, il fait foi pour le cash et le coût de revient. Sans lui, le calcul q·p ± f
  est exact, mais il peut différer d'un centime de l'arrondi du courtier : le rapprochement le
  signalera, et il suffira d'ajouter `montant`.
- `compte` est un libellé court (lettres, chiffres, espace, `.`, `_`, `-` ; 32 caractères au
  plus). `libelle` (120 caractères au plus) passe le contrôle `injection_signals` comme le nom
  d'un instrument (R5).
- Dans une même journée, l'ordre des lignes du fichier est l'ordre des opérations. Une
  transaction datée dans le futur refuse le fichier.
- Chaque courtier a son adaptateur (D4). Il convertit son export dans ce format, ordre des
  lignes compris, et il est testé sur un vrai export anonymisé. Seul le format `cerveau` existe
  tant que Lucas n'a pas désigné son courtier. L'API d'IBKR reste au backlog (D5).

**Arithmétique.** Quantités, prix, frais, cash et coûts de revient sont des `Decimal`, lus
depuis le texte du fichier et stockés en texte. Le rejeu calcule avec 60 chiffres significatifs :
le produit de deux nombres du fichier (25 chiffres chacun au plus) et toutes les sommes sont
donc exacts. Un solde reconstruit est exactement la somme des montants. Seule la part du coût
retirée par une vente (coût × q / quantité détenue) peut être arrondie, à 60 chiffres. La
conversion en flottant n'a lieu qu'à la valorisation (cours × change).

**Imports.**
- `cerveau portfolio import <fichier> --format cerveau` est lancé par Lucas. Ni le planificateur
  ni un outil MCP ne l'appellent.
- L'empreinte SHA-256 du fichier rend l'import idempotent : le même fichier une seconde fois ne
  change rien.
- **Un fichier fait foi, compte par compte, sur sa période**, du premier au dernier jour qu'il
  contient pour ce compte. Ses transactions remplacent celles des imports précédents sur cette
  période ; en dehors, rien ne change. Un export complet remplace donc tout et un export
  mensuel s'ajoute à la suite. Un vieux fichier réimporté ne touche que sa propre période.
- Chaque import est conservé. L'historique effectif se recalcule à la lecture en appliquant les
  imports dans l'ordre où ils ont été faits.
- L'import reconstruit le portefeuille et l'état du rapprochement dans la transaction de la
  base qui l'enregistre. Une vente supérieure à la position détenue refuse le fichier, et rien
  n'est enregistré. Un cash négatif est signalé, sans refuser le fichier.
- L'import est journalisé (R11) avec l'empreinte, le nombre de lignes, les transactions ajoutées
  et retirées, les avertissements et l'état du rapprochement de chaque compte (clé
  `reconciliation`). Les montants et les libellés ne sont jamais journalisés. Un refus est
  journalisé aussi (entrée `ERROR`) ; son message nomme le fichier, la ligne, le compte ou
  l'identifiant, jamais une valeur.

**Positions.**
- Elles sont tenues par compte et par instrument, le cash par compte et par devise.
- Le coût de revient est le **prix moyen pondéré** : un achat ajoute q·p + f, ou `montant`. Une
  vente retire du coût la part vendue (coût × q / quantité détenue) et dégage une plus-value
  réalisée : produit net moins coût retiré. Le prix moyen ne change pas à la vente.
- Un **split** de la base finance (ratio r, nouveaux titres par ancien) s'applique au début de
  son jour ex, avant les opérations de ce jour. La quantité est multipliée par r et le coût ne
  change pas. Un adaptateur de courtier ne doit donc pas produire de ligne pour un split.
- Un **dividende** n'entre dans le cash que par sa ligne `dividende`, c'est-à-dire le versement
  réellement reçu. Les dividendes de la base finance servent au rendement total des cours.
- **Point-in-time.** Une transaction est connue à la fin de son jour, heure de Paris, et au plus
  tard à son import. Une lecture « connue à » `as_of` ne voit qu'elle, et la valorise au
  dernier cours et au dernier change de la BCE publiés à `as_of` (ADR-017). En mode strict, seuls
  les imports faits avant `as_of` comptent. Un instrument sans cours connu n'a pas de valeur, et
  le total est alors absent, jamais partiel (R12).

**Rapprochement.**
- `cerveau portfolio reconcile <relevé>` lit un relevé de positions au format CERVEAU :
  `date, compte, nature, identifiant, quantite`. `nature` vaut `titre` (identifiant d'un
  instrument) ou `especes` (code de la devise). Un relevé porte une seule date.
- Le relevé est comparé aux positions calculées à sa date, compte par compte, avec **égalité
  exacte**, puis conservé dans la base, de façon idempotente. Tout écart, même d'un centime, est
  un écart. Une position absente d'un côté vaut zéro de ce côté.
- L'état du rapprochement d'un compte est **recalculé à chaque lecture**, à partir de son dernier
  relevé connu. Il vaut `ok`, `ecart`, ou `non_rapproche` si le compte n'a pas de relevé. Le
  dernier relevé d'un compte est celui de la date la plus récente ; à date égale, le dernier
  importé. Réimporter un relevé déjà enregistré ne change pas sa place. Un import qui corrige les transactions corrige donc l'état sans relancer de commande. Les outils
  de la phase 2 afficheront `rapprochement: ecart` ; le blocage des intentions arrive en phase 4.
- Un écart produit une alerte dans la CLI (code de sortie 4) et dans le journal : une entrée
  `TOOL_CALL` avec `alert: "rapprochement: ecart"`, les comptes et les identifiants en écart,
  sans les quantités. Les quantités ne s'affichent que dans la CLI. Un import après lequel un
  compte est en écart avec son dernier relevé donne la même alerte et le même code.

## Conséquences
- Aucun seuil de rapprochement à régler : l'égalité exacte est la règle la plus prudente, et les
  décimaux la rendent atteignable.
- Un export partiel qui oublie une opération au milieu de sa période l'efface pour cette
  période. Le rapprochement le révèle, puisque le relevé du courtier ne tombe plus juste.
- Les plus-values réalisées au prix moyen pondéré préparent l'export fiscal (F10). Le traitement
  fiscal exact (PEA, frais, change) sera vérifié avec l'export, pas ici.
- La migration 2 s'applique à la première ouverture en écriture (`cerveau finance sync` ou
  `cerveau portfolio import`). Une base au schéma 1 ouverte en lecture seule est refusée avec
  ce conseil.
