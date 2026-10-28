# Procédure d'activation du live (finance)

Décision D9 du plan de phase 5 ; ADR-039 (adaptateur et six conditions), ADR-036 (niveau effectif et
signature), ADR-035 (approbations), ADR-034 (kill switch), ADR-003 (ACL).

**Qui** : Lucas seul, à la main. Claude Code ne modifie jamais `config/live.yaml` ni
`governance/approvals/`, ne lance jamais `protect-live.ps1` et n'a jamais accès aux clés du
courtier (R3, §8.6).

## 0. État au 21/10/2026 : activation impossible

| Élément | État | Conséquence |
|---|---|---|
| Client de courtier | aucun (`broker: A_DEFINIR`, D8) | `LiveAdapter` n'a rien à appeler |
| Boucle live | aucune : seuls les tests instancient `LiveAdapter` | aucune intention n'atteint l'adaptateur live |
| `config/live.yaml` | `enabled: false`, limites à 0, liste blanche vide | condition 1 fausse : tout envoi est refusé |
| Signature N3 | aucune dans `governance/approvals/` | conditions 3 et 4 fausses |
| ACL | non posée sur ce poste (B173) | condition 2 fausse |
| Rotation des clés | `keys.rotation_days: A_DEFINIR` (`config/risk.yaml`) | prérequis 7 non rempli |

Ce document fixe ce qui devra être vrai et l'ordre des gestes. Le client de courtier et la boucle
live relèvent d'une phase dédiée, avec ses revues.

## 1. Prérequis, tous requis

| # | Prérequis | Comment le constater |
|---|---|---|
| 1 | Rapport de promotion N2 → N3 qui conclut `promotion_possible` (§8.3 : semaines et décisions de paper, incidents d'exécution, écart paper/backtest expliqué, drawdown paper, golden et red team du domaine) | `cerveau promotion report finance --to N3 --evals var/evals/<campagne>/report.json` : code de sortie 0, rapport `var/promotion/finance-N3-AAAA-MM-JJ.md` et son SHA-256. Code 1 : promotion impossible ; code 2 : critère non évaluable (seuil `A_DEFINIR`, R7) |
| 2 | Campagne d'évals réelle et red team du domaine réussies | `make eval-live`, avec ton accord pour cette campagne ; son `report.json` sert au prérequis 1 |
| 3 | Client de courtier réel livré et revu (`security-reviewer`, `risk-gate-auditor`) | délai par appel inférieur à la cible du kill switch, 5 s (B171) ; exécutions et relevé lus dans une même coupe (B169) ; seuls un code de refus et le nom du type d'exception journalisés (B197) |
| 4 | Compte live séparé du compte paper ; clés distinctes, sans droit de retrait, permissions minimales, hors dépôt (§8.6) | interface du courtier : droits de la clé |
| 5 | Utilisateur Windows dédié au service live (l'équivalent de l'utilisateur Unix du §8.6) ; Claude Code tourne sous un autre compte et ne lit pas ses clés | `whoami` dans chaque session |
| 6 | Approbations opérationnelles : secret TOTP enrôlé, bot Discord et alertes ntfy configurés ; `CERVEAU_TOTP_SECRET` et `CERVEAU_API_TOKEN` posés dans l'environnement du compte de service du prérequis 5, qui seul lance le bot et l'API, jamais en variables du compte où tourne Claude Code (B228) | `cerveau approvals enroll` (terminal interactif, une fois, sous le compte de service) ; `config/interfaces.yaml` renseigné ; `cerveau config check` liste les canaux d'alerte ; `Test-Path env:CERVEAU_TOTP_SECRET` renvoie `False` dans une session du compte de Claude Code |
| 7 | Période de rotation des clés fixée | `keys.rotation_days` dans `config/risk.yaml`, valeur décidée par toi |
| 8 | Kill switch éprouvé en paper | `/kill` sur Discord, puis `cerveau kill` : ordres annulés, N0 forcé, approbations ouvertes refusées ; `cerveau rearm` ensuite |
| 9 | Limites live décidées : ordre, position, perte du jour, ordres par jour (toutes > 0) et liste blanche | levier, vente à découvert et dérivés restent `false` |
| 10 | ACL posée et vérifiée (B1, B2) | `protect-live.ps1 -Check` depuis un PowerShell **non élevé** : l'écriture de `live.yaml` est refusée |

## 2. Activation pas à pas

1. **État de départ** : `cerveau status` (kill switch armé, live désactivé), `cerveau config check`
   (configuration valide) et `make audit-verify` (chaîne du journal intacte).
2. **Rapport de promotion** : `cerveau promotion report finance --to N3 --evals …`. Lire chaque
   critère : valeur, seuil, statut, outil source (R1). Si la promotion est possible, la commande
   affiche le texte de signature.
3. **Lever la protection** : PowerShell « Exécuter en tant qu'administrateur »,
   `powershell -ExecutionPolicy Bypass -File infra\windows\protect-live.ps1 -Unprotect`.
4. **Signer** : copier le texte affiché dans `governance/approvals/AAAA-MM-JJ-finance-N3.md`. Son
   en-tête YAML porte `domain: finance`, `level: N3`, la date, `promotion_report_sha256` et
   `signed_by: lucas`. Une signature dont le nom, l'en-tête ou la date divergent, datée après
   aujourd'hui ou avant le jour du rapport qu'elle cite, ou qui cite un rapport absent, modifié ou
   négatif, est ignorée (ADR-036). Dater la signature du jour où elle est écrite.
5. **Niveau** : dans `config/autonomy.yaml`, `domains.finance.level: N3`. Le niveau effectif est le
   plus bas du niveau écrit et du plus haut niveau signé : ni la signature seule ni le fichier seul
   ne suffisent.
6. **Live** : dans `config/live.yaml`, `enabled: true`, `broker` renseigné, limites décidées
   (prérequis 9), liste blanche non vide. `allow` reste entièrement à `false`.
7. **Reposer la protection** : `protect-live.ps1` sans option (administrateur), puis
   `protect-live.ps1 -Check` depuis un PowerShell non élevé.
8. **Contrôle** : `cerveau config check` doit afficher `live.yaml : enabled = true`, la ligne
   « finance : écrit N3, effectif N3 » et aucune « signature ignorée ». `cerveau status` doit
   afficher « Kill switch : armé » et « Live : ACTIVÉ ».
9. **Premier ordre** : une intention de taille minimale sur un titre de la liste blanche, approuvée
   sur Discord avec le code à usage unique. Vérifier ensuite le journal (`cerveau audit tail`),
   l'état de l'ordre et la réconciliation du compte live.

## 3. Ce que le code revérifie à chaque envoi

Rien n'est gardé en mémoire : à chaque ordre, `LiveAdapter` relit le disque et exige les six
conditions (ADR-039, D9). Une seule fausse lève `LiveDisabled`, qui les nomme toutes, et le
courtier n'est pas appelé.

1. `live.yaml` complet : `enabled`, courtier nommé, limites > 0, liste blanche non vide.
2. `live.yaml` et `governance/approvals/` appartiennent aux Administrateurs (ACL).
3. Signature N3 valide, sur un rapport de promotion présent et positif.
4. Niveau effectif de la finance ≥ N3.
5. Kill switch non engagé.
6. Approbation ACCORDEE pour `live`, non expirée, liée au contenu exact de l'intention ; elle est
   consommée une seule fois, avant l'envoi.

L'annulation et la lecture restent permises sans condition : elles ne vont que dans le sens sûr.

## 4. Retour arrière

Dans cet ordre, du plus rapide au plus complet :

1. **Arrêt** : `/kill` sur Discord, `cerveau kill` ou fichier `governance/kill_switch/KILL`. Les
   ordres ouverts sont annulés, toute nouvelle intention est bloquée, N0 est forcé, les
   approbations ouvertes sont refusées (R4, cible 5 s).
2. **Désactivation** : `protect-live.ps1 -Unprotect`, `enabled: false` dans `config/live.yaml`,
   puis `protect-live.ps1` et `-Check`.
3. **Clés** : révocation chez le courtier, puis nouvelle clé sans droit de retrait.
4. **Niveau** (si besoin) : baisser `domains.finance.level` dans `config/autonomy.yaml` rétrograde
   aussitôt ; la remontée repasse par la promotion (§8.3).
5. **Réarmement** : `cerveau rearm`, par toi seul, en terminal interactif, après lecture du rapport
   d'incident (`var/incidents/`).

## 5. Rotation des clés

Tous les `A_DEFINIR` jours (`keys.rotation_days`, `config/risk.yaml`, §8.6) : créer la nouvelle clé
avec les mêmes droits minimaux, la poser dans l'environnement du compte du service live, vérifier
la lecture du relevé, puis révoquer l'ancienne. Un nouvel enrôlement TOTP (`cerveau approvals
enroll`) remplace l'ancien secret : les codes de l'ancien ne valent plus.

## 6. Limites connues

- `cerveau status` affiche le niveau écrit, pas le niveau effectif ni les six conditions : le
  contrôle passe par `cerveau config check` (B225).
- Le compte courant garde le contrôle des dossiers parents `config/` et `governance/` ; la
  vérification du propriétaire par l'adaptateur est la parade (`docs/threat-model.md`).
- L'ACL ne couvre pas encore `governance/kill_switch/` ni `var/incidents/` (B173).
- Aucune rétrogradation automatique n'est vérifiée par cette procédure : elle dépend de la boucle
  live à venir.
