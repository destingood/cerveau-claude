# ADR-073 — Secrets des approbations dans le Gestionnaire d'identification Windows

- Statut : proposé (B228, partie C : « C ensuite », décision de l'utilisateur du 27/11/2026)
- Date : 2026-11-27
- Phase : plan du cerveau, Bloc B (« Une chaîne d'approbation »)
- Complète l'ADR-035 (qui place le secret TOTP dans une variable d'environnement) sans le remplacer
  tant que l'utilisateur n'a pas validé.

## Contexte
`CERVEAU_TOTP_SECRET` (ADR-035) et `CERVEAU_API_TOKEN` (ADR-037) sont lus dans l'environnement du
processus. Une variable d'environnement est héritée par tout processus enfant et, posée en
« variable utilisateur » Windows, elle est aussi copiée dans le registre (`HKCU\Environment`), lisible
par tout processus du compte. B228, parties A et B (faites le 27/11) : `guard_shell` refuse toute
lecture de ces valeurs, et `.claude/settings.json` les met à vide pour Claude Code. La procédure live
(prérequis 5 et 6) les place dans l'environnement d'un compte de service dédié au bot et à l'API.
Reste un risque : une variable d'environnement se retrouve dans tout processus lancé par le compte
de service, et un oubli (variable posée au mauvais compte) n'est vu par rien.

Faits vérifiés le 27/11/2026 :
- `keyring` 25.7.0 (PyPI, publié le 16/11/2025) : licence MIT ; sous Windows, son moteur
  `WinVaultKeyring` passe par le Gestionnaire d'identification (`win32cred`, source
  `keyring/backends/Windows.py`, tag v25.7.0), avec la persistance `CRED_PERSIST_ENTERPRISE` par
  défaut (l'identifiant suit un profil itinérant). Dépendances : `pywin32-ctypes` 0.2.3
  (BSD-3-Clause) sous Windows, `jaraco.classes` 3.4.0, `jaraco.functools` 4.6.0, `jaraco.context`
  6.1.2 (MIT) ; `SecretStorage` et `jeepney` sous Linux.
- API Win32 : `CredReadW` / `CredFree` (`advapi32.dll`, en-tête `wincred.h`), appelables par
  `ctypes` de la bibliothèque standard. **A_VERIFIER** : la page de Microsoft
  (learn.microsoft.com) n'a pas pu être lue depuis la session ; signature, types et portée par
  utilisateur sont écrits de mémoire.
- Un identifiant du Gestionnaire est rangé **par compte Windows** et lisible sans invite par tout
  processus de ce compte (A_VERIFIER, même source). Il ne protège donc de Claude Code que s'il est
  rangé sous le compte de service, Claude Code tournant sous un autre compte (prérequis 5).

## Options
1. **Rester aux variables d'environnement du compte de service** (état actuel, parties A et B).
   Rien à écrire ; mais le secret est hérité par chaque processus du service et copié dans le registre.
2. **Gestionnaire d'identification par l'API Win32, via `ctypes`** : une petite fonction de
   `core/approvals/` lit l'identifiant générique `CERVEAU/totp` (et `CERVEAU/api`), sous Windows
   seulement ; la variable d'environnement reste le repli sous Linux (VPS) et dans les tests.
   Aucune dépendance (R14 sans objet), environ 40 lignes à tester, comportement identique en CI Linux.
3. **`keyring`** : même stockage, API portable (Windows, macOS, Linux par Secret Service). Quatre
   dépendances transitives à épingler et à relever dans `docs/licences.md` ; persistance
   `ENTERPRISE` par défaut, à forcer en `LOCAL_MACHINE`.

Le bot Discord (Node.js) lit `CERVEAU_API_TOKEN` et `DISCORD_BOT_TOKEN` : Node n'a pas d'accès natif
au Gestionnaire. Dans les options 2 et 3, son lanceur (script PowerShell de l'utilisateur, sous le
compte de service) lit l'identifiant et le passe dans l'environnement du seul processus du bot,
sans variable persistante.

## Décision
Proposée : option 2. Elle n'ajoute aucune dépendance, garde le même code sous Windows et en CI, et
retire le secret des variables persistantes du compte de service. `keyring` (option 3) reste la
voie si un autre système doit un jour lire un coffre (macOS). Rien n'est appliqué avant la
validation de l'utilisateur, ni sans tests ; la protection effective reste le compte de service.

## Conséquences
- À faire après validation : lecteur `ctypes` de l'identifiant, repli sur la variable, tests
  (lecteur factice sous Linux), `cerveau approvals enroll` qui dit de ranger le secret par
  `cmdkey /generic:CERVEAU/totp /user:cerveau /pass` sous le compte de service ; lanceur du bot.
- Les gestes de l'utilisateur sont décrits dans `docs/procedure-live.md` (§ « Secrets dans le
  Gestionnaire d'identification »).
- Les parties A et B restent en place : le hook continue de refuser les lectures, et le masquage
  des variables dans `.claude/settings.json` demeure, utile tant qu'une variable traîne.
- Limite : ni le hook, ni le Gestionnaire ne protègent si Claude Code tourne sous le compte de
  service ; c'est le prérequis 5 qui tient (`whoami`).
