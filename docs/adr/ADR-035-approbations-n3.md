# ADR-035 — Approbations N3 : machine à états, code TOTP, lien à l'intention

- Statut : accepté (D2, D3, D4, D18 et D19 du plan de phase 5, validées par Lucas le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
En N3, une action FINANCIERE n'est exécutée qu'après l'approbation de Lucas, une par une (§8.3).
`autonomy.yaml` porte déjà `approval: { channel: discord, one_time_code: true, expiry_minutes:
A_DEFINIR }` et le journal accepte l'événement `APPROVAL`, mais aucun code ne crée, ne vérifie ni
ne consomme une approbation. Un code affiché dans Discord ne prouverait rien si le compte Discord
était compromis.

## Options
1. Code affiché dans Discord, ou envoyé par ntfy.
2. Bibliothèque TOTP externe (pyotp).
3. **TOTP RFC 6238 écrit dans le projet avec la bibliothèque standard**, second facteur
   indépendant de Discord.

## Décision
Option 3.

- **Paquet `core/approvals/`**, déterministe, sans modèle :
  - `totp.py` : RFC 6238 sur RFC 4226, HMAC-SHA1, 6 chiffres, pas de 30 s, T0 = 0, comparaison
    `hmac.compare_digest`. Fenêtre ±1 pas : la RFC (§5.2) recommande au plus un pas de retard ;
    l'avance d'un pas couvre une horloge de téléphone en avance. Anti-rejeu : un code d'un pas
    inférieur ou égal au dernier pas accepté est refusé (§5.2 : « MUST NOT accept the second
    attempt »).
  - `store.py` : demandes et transitions dans `var/approvals/approvals.db`, SQLite en ajout seul
    (déclencheurs « ni UPDATE ni DELETE », comme le carnet, ADR-032).
- **États** : DEMANDEE → ACCORDEE, REFUSEE ou EXPIREE ; ACCORDEE → CONSOMMEE (une seule fois) ou
  EXPIREE. L'échéance se constate à la lecture, avec une horloge injectée : aucune minuterie.
  Expirée vaut refus, sans retour possible.
- **Lien à l'intention (D4)** : une demande porte `intent_id`, l'empreinte SHA-256 de l'intention
  et le résultat de la Porte (quantité retenue, raisons). À l'exécution, la Porte est réévaluée
  sur un instantané frais ; un refus ou une autre quantité refuse l'approbation.
- **Essais (D3)** : `expiry_minutes` = 10, 3 essais de code par demande puis REFUSEE ; 5 échecs en
  15 min verrouillent toutes les approbations et lèvent une alerte.
- **Secret** : variable d'environnement `CERVEAU_TOTP_SECRET` (base32), posée par Lucas. Absente ou
  invalide ⇒ tout code est refusé. `cerveau approvals enroll` génère le secret et l'URI
  `otpauth://` dans le terminal de Lucas seulement.
- **Journal** : une entrée `APPROVAL` par transition (`approval_id`, `intent_id`, état, raison).
  Acteur `interface` pour une demande ou un refus venu d'une interface, `lucas` pour un accord
  vérifié par code, `policy` pour une expiration ou un refus de la Porte réévaluée.
- **Kill switch** : toute demande ouverte passe à REFUSEE.
- **Compteurs N3 → N4** : approbations, refus et expirations comptés dès maintenant.

## Conséquences
- Ni le bot, ni l'API, ni Claude Code ne peuvent approuver sans le code de l'application
  d'authentification de Lucas.
- Les hooks protègent `var/approvals/` et refusent `cerveau approvals enroll` (D18) ; la
  protection effective reste l'ACL (ADR-003).
- **Tests** : vecteurs de l'annexe B de la RFC 6238 (SHA-1, SHA-256, SHA-512, 8 chiffres),
  fenêtre, rejeu, machine à états Hypothesis (`RuleBasedStateMachine`), échéance pour toute
  horloge. Couverture de 100 % des lignes et des branches de `core/approvals`, imposée par
  `make ci` (D19).
