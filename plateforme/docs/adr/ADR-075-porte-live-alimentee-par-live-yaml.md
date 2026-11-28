# ADR-075 — Porte live alimentée par `live.yaml`, devant les sept conditions de la garde

- Statut : proposé (plan validé par l'utilisateur le 28/11/2026 pour B353 ; les trois nouveaux champs de
  `live.yaml` et leurs valeurs restent ta décision ; amendé le 28/11/2026 après la revue
  `risk-gate-auditor`, constats M1 à M4 et m1 à m5)
- Date : 2026-11-28
- Phase : 8+ (plan v2, étape 15 « finance en réel » ; B353, suite de B200)

## Contexte
La garde live (`core/execution/live.py`, ADR-039, ADR-067) vérifie sept conditions à chaque envoi.
La 7e lit la liste blanche, puis refuse tout ordre faute de Porte live : ni la taille de l'ordre, ni
la position, ni la perte du jour, ni le nombre d'ordres du jour, ni `allow` de `config/live.yaml` ne
s'appliquent à un ordre réel (B200, B353). R2 interdit toute action réelle sans Porte de risque ; R3
réserve `live.yaml` à l'utilisateur ; R7 veut que l'inconnu bloque ; R10 interdit toute donnée
postérieure à la décision ; R11 veut une trace de chaque décision.

Faits relevés le 28/11/2026 : `live.yaml` vaut `enabled: false`, `broker: A_DEFINIR`, limites à 0,
liste blanche vide. Ses limites sont des pourcentages sans capital de référence, et rien n'y dit
dans quel fuseau commence la journée de la perte et des ordres du jour. Aucun courtier n'est
branché : aucune source ne donne positions, cash ni P&L du jour. La Porte paper (ADR-031) est une
fonction pure qui accepte, réduit ou refuse.

## Options
1. **Ouvrir la 7e condition avec la Porte** (la condition appelle la Porte). Écartée : une seule
   serrure ; retirer ou remplacer la condition, injectable, retirerait aussi la Porte.
2. **Mode live de la Porte paper** (`PaperRiskLimits` élargie). Écartée : mêlerait des limites
   d'une autre nature et changerait le comportement paper, qu'aucune ligne ne doit toucher.
3. **Porte live distincte, devant les sept conditions, la 7e gardée fermée.** Retenue : deux
   serrures, chacune suffisante.
4. Pourcentages rapportés à l'avoir du compte donné par le courtier. Écartée : une source fausse ou
   manipulée gonflerait les plafonds ; le capital de référence reste ta décision écrite.

## Décision
Option 3.

- **`core/risk_gate/live.py`**, fonction pure `evaluate_live(intent, live, book, now, journaled)` :
  `ACCEPTE` ou `REFUSE`, jamais `REDUIT` (l'approbation est liée au contenu exact, D4). Mêmes
  briques que la Porte paper (`RiskGateResult`, contrôles tous évalués, `Decimal` exact), sans en
  changer une ligne.
- **Contrôles**, chacun en échec fermé : `enabled` vrai ; aucune donnée postérieure à la décision
  (intention, cours cité, livre, cours et taux du livre) ; même journée pour la décision, le livre
  et l'intention dans le fuseau de `live.yaml` ; livre et taux lus au plus `max_book_age_s` avant
  la décision ; liste blanche (symbole, ou ISIN confirmé par le livre) ; instrument connu du livre,
  même devise ; aucun dérivé ; `allow` : un drapeau à `true` refuse tout, la Porte ne modélisant ni
  levier, ni vente à découvert, ni dérivés ; taille de l'ordre et position (détention + achats
  ouverts + ordre) ≤ limite en % du capital ; perte du jour strictement sous la limite (l'atteindre
  arrête la journée) ; ordres du jour + 1 ≤ limite ; vente couverte par la position (sinon
  découvert) ; achat payé par le cash après les achats ouverts (sinon levier). Un ordre est
  valorisé au plus haut du prix limite et du dernier cours.
- **Valeurs revérifiées par la Porte**, quel que soit le schéma : absente, `A_DEFINIR` ou
  `A_VERIFIER`, mauvais type (booléen compris), non finie, ≤ 0, pourcentage > 100, liste blanche
  vide ou marquée, fuseau inconnu de la base IANA : refus, avec la raison. Le chargeur lit `live.yaml`
  sans coercition (m1) : `enabled: 1`, `"on"` ou `"true"`, `"2"` pour un nombre, `true` pour un
  compte ne se chargent pas, et une configuration non chargée refuse tout. La Porte paper garde son
  propre `Allow`.
- **Rien n'est pris tel quel (M2, M3)** : l'intention doit être un `OrderIntent` exact, revalidé
  depuis son contenu (une instance construite sans validation, ou une sous-classe, est refusée) ;
  son empreinte est calculée par la fonction `fingerprint` du module, jamais par une méthode de
  l'objet, et c'est la copie revalidée qui va aux conditions, à l'approbation et au courtier. Le
  livre et chacune de ses parties (ordres ouverts : un modèle `LiveOpenOrder` propre, taux,
  instruments) sont revalidés, même passés en instance.
- **Trois champs facultatifs de `live.yaml`**, écrits par toi seul : `capital_reference_eur`,
  `timezone` (nom IANA) et `max_book_age_s` (âge maximal du livre et de ses taux, en secondes).
  Absents ou marqués, la Porte refuse tout. `cerveau config check` les liste sous
  `live_trading.risk_gate`. Le fichier n'est pas modifié (R3).
- **Livre** (`LiveBook`) : positions, ordres ouverts, cash, P&L et ordres du jour, à un instant et
  pour une journée, taux datés, et `known_intents`, les empreintes des ordres du jour que le
  courtier montre déjà ; donnés par une source passée en argument, sans réseau, attendue au plus
  le délai d'appel au courtier (m3). Aucune source n'existe : `no_live_book` ne rend rien, et la
  Porte refuse.
- **Deux ordres sur un même livre (M4)** : `LiveAdapter` tient un verrou entre processus
  (`var/live/gate.lock`, l'aide de verrou du journal d'audit) de la Porte à la réponse du courtier ;
  la Porte relit au journal ses acceptations du jour (`AuditJournal.payloads`, lecture seule) et
  compte celles que le livre ne montre pas encore comme ordres ouverts et ordres du jour, chacune
  une fois, dans l'ordre de leurs empreintes. Un journal illisible refuse.
- **Branchement (m3, m4, m5)** : `LiveAdapter` construit lui-même sa `LiveRiskGate` depuis sa racine,
  son journal et sa source de livre ; aucun appelant ne lui passe de Porte. La Porte regarde d'abord
  le kill switch (refus sans rien lire, R4), puis lit `live.yaml` par le chargeur (jamais
  d'écriture), le livre et le journal, et ne prend l'heure de décision qu'une fois le livre reçu ;
  l'âge maximal borne l'écart. Seul un `ACCEPTE` de cette intention, à sa quantité, laisse lire les
  sept conditions ; sinon `LiveGateRefused`, un `LiveDisabled`, sans appel au courtier ni
  approbation consommée.
- **Journal (M1, m2)** : une entrée `POLICY` de l'acteur `risk_gate` par décision, acceptée ou
  refusée (`request_id` `live-<intent_id>`, version de la config) : contrôles, raisons, quantités,
  l'ordre lui-même (instrument, sens, quantité, prix limite, devise : de quoi le compter ensuite),
  empreinte de l'intention, SHA-256 du livre seul et, pour une erreur, le nom de son type seul
  (ADR-071, B197). Un contrôle qui lit le livre n'écrit aucun de ses chiffres : sa valeur est
  « masqué (livre) », sa limite celle de `live.yaml` ; ni cash, ni détention, ni P&L, ni exposition,
  ni courtier, ni compte. Si l'entrée ne peut être construite ou écrite, un refus nu (types
  d'erreur seuls) est tenté et l'ordre est refusé (R11).

## Conséquences
- Le live reste fermé trois fois : `enabled: false`, Porte sans livre ni capital ni fuseau ni âge
  maximal, 7e condition fermée. L'ouvrir demandera ta décision sur la 7e condition, un client de
  courtier et sa source de livre (phase dédiée, revues).
- Le journal ne permet plus de relire les chiffres du compte qui ont fondé une décision : seule
  l'empreinte du livre en témoigne, à comparer au relevé du courtier.
- Une acceptation suivie d'un refus des sept conditions compte quand même comme ordre du jour :
  plus prudent, au prix d'un ordre de moins possible ce jour-là.
- Tests : chaque refus, chaque limite atteinte puis franchie d'une unité, `A_DEFINIR`, fichier
  inchangé (octets et date de modification), 7e condition toujours fermée, Porte seule suffisante
  sans 7e condition, propriété Hypothesis contre un oracle en fractions (3 000 cas dérandomisés,
  acceptations du jour et livre trop ancien compris), journal des deux issues sans chiffre du livre,
  verrou tenu, deux achats sur un même cash, une mutation par constat qui fait échouer un test.
  `core/risk_gate` et `core.execution.live` restent couverts à 100 % (lignes et branches).
- Reste (B353) : frais du courtier dans le contrôle du levier (R10) ; plafond d'ordres par heure ;
  journalisation des refus des sept conditions ; idempotence côté courtier ; fraîcheur des cours
  (le seuil d'âge couvre le livre et les taux, pas encore le dernier cours de chaque instrument).
