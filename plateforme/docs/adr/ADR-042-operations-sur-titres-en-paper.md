# ADR-042 — Opérations sur titres dans le compte paper

- Statut : accepté (B187, inclus dans la phase 5 par la décision D20 validée par l'utilisateur le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le simulateur paper et la boucle ignoraient les splits et les dividendes (B187). Un split 2:1 sur
une ligne de 10 % simulait une perte de 5 % et déclenchait le kill switch à tort. Aucun dividende
n'était crédité. Le référentiel du store connaît déjà ces opérations au point dans le temps (ADR-012),
et le backtest s'en sert. Le compte paper doit rester un second livre, indépendant du carnet de
CERVEAU (ADR-033), pour que la réconciliation compare deux comptabilités.

## Options
1. Valoriser sur des clôtures ajustées sans toucher aux positions.
2. Laisser la boucle corriger le carnet de CERVEAU.
3. **Faire comptabiliser les opérations par le simulateur, dans sa propre base, et les rejouer des
   deux côtés avec les mêmes règles.**

## Décision
Option 3.

- **Règles communes** (`core/execution/actions.py`), appliquées séance par séance :
  1. les splits s'appliquent aux positions du début de séance ;
  2. puis viennent les exécutions de la séance ;
  3. enfin, les dividendes sont versés sur les positions du début de séance.
- **Split** : seuls des titres entiers sont conservés. Un ratio à 10⁻⁹ près d'un nombre entier de
  titres compte pour ce nombre : un `float` 1/3 sur 3 titres donne 1 titre. Le rompu est payé à la
  clôture de la séance, arrondi au centime inférieur.
- **Dividende** : il est crédité en euros à l'ex-date, sur les titres détenus, arrondi au centime
  inférieur. Un dividende dans une autre devise n'est pas crédité et fait l'objet d'une note.
- **Comptabilisation** (`PaperSimulator.book_actions`) :
  - Une opération est comptabilisée une fois la clôture de sa séance publiée. Sa séance est la
    première séance de la place à partir de l'ex-date.
  - Elle ne vaut que pour les instruments sur lesquels le compte a passé un ordre, et jamais avant
    la séance du premier de ces ordres.
  - Elle est enregistrée dans une table `actions` en insertion seule, avec une seule version par
    opération.
- **Ordres** : un split annule les ordres ouverts de l'instrument à partir de sa séance, parce que
  leur quantité et leur limite datent d'avant le split. La boucle reporte cette annulation dans le
  carnet.
- **Réconciliation** : le relevé du compte porte ses opérations. Le livre de CERVEAU les rejoue avec
  le `Split` du portefeuille. Le rompu y est passé comme une vente à la clôture, et le dividende comme
  un dividende. Les empreintes du livre et du relevé incluent les opérations.

## Limites acceptées
- **Split annoncé en retard** : une opération connue après la clôture de sa séance est comptabilisée
  rétroactivement, et une note le signale. Les exécutions intermédiaires ne sont pas modifiées. La
  valorisation de la veille a pu montrer une fausse perte.
- **Split inverse tardif** : s'il est connu après une vente qui le rend impossible, il devient un
  incident d'exécution. Rien n'est alors comptabilisé.
- **Arrondis** : le paper arrondit au centime inférieur, le moteur de backtest au plus proche. L'écart
  est d'un centime au plus par opération.
- **Révisions** : la révision d'une opération déjà comptabilisée est ignorée, et une note le signale.
- **Curseur** : le curseur du relevé compte les événements seulement, pas les opérations.
- **Plusieurs splits** : deux splits du même instrument à la même séance forment un seul ratio dans
  le livre de CERVEAU.
- **Séance sans clôture** : une opération dont la séance n'a pas de clôture publiée n'est jamais
  comptabilisée.
- **Date de versement** : le dividende est crédité à l'ex-date, pas à la date de paiement.
- **Live** : le contrôle des opérations déclarées par le courtier contre le référentiel relève du live
  (backlog).

## Conséquences
- Un split ne déclenche plus le kill switch. La réconciliation reste propre après un split, un rompu
  ou un dividende (tests `tests/test_execution_actions.py` et `tests/test_execution_loop.py`).
- Le rapport du jour reçoit une section « Opérations sur titres », qui cite sa source.
- Le golden « split » reste dans B193 : les goldens d'exécution sont à valider par l'utilisateur.
