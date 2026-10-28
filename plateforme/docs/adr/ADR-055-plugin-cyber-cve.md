# ADR-055 — Plugin `cyber_cve` : NVD, catalogue KEV et EPSS en lecture, tri déterministe

- Statut : **proposé** (G1 à G4, G8 et G10 du complément de plan P4, validés par Lucas le
  27/10/2026)
- Date : 2026-10-27
- Phase : 6 (P4)

## Contexte
Le pack Cyber (P4, défensif, R15) doit dire si une CVE est publiée, exploitée et probable, sans
qu'un LLM produise de score ni d'ordre de priorité (R1). Trois sources publiques existent. Faits
relevés par requêtes directes le 26/10/2026 (vers 23 h 53 UTC) et lus le 27/10/2026 :
- **NVD, API CVE 2.0** : fiche CVE-2021-44228 de 87 139 octets (CVSS 3.1 de 10.0 par
  nvd@nist.gov, CVSS 2.0, SSVC, CWE) ; une CVE inconnue donne 200 et `totalResults` 0 ; une plage
  de plus de 120 jours donne **404** avec l'en-tête `message: Date range cannot exceed 120 days.` ;
  l'en-tête `apiKey` figure dans `access-control-allow-headers`. Une recherche par plage rend les
  CVE par date de publication croissante : constaté sur un échantillon de 5 réponses sur 134, non
  documenté (`A_VERIFIER`).
- **Catalogue KEV de la CISA** (CC0 1.0) : version 2026.10.26, 1 758 entrées, 1 810 928 octets.
- **EPSS de FIRST** : champs `cve`, `epss`, `percentile`, `date` ; attribution demandée.

Incertitudes conservées : débits du NVD (5 requêtes par 30 s sans clé, 50 avec clé) et
2 000 résultats par page, tous deux de source secondaire ; conditions du programme CVE (page non
lue) ; aucun débit EPSS publié. Les cinq sont `A_VERIFIER`.

## Options
1. **Un plugin, deux outils** (`cve_lookup`, `cve_watch`) qui croisent les trois sources et
   rangent en code. Tient dans R13 avec ATT&CK et la lecture web (5 outils, G1).
2. **Un outil par source** (7 outils) : exception à R13, et le LLM devrait croiser et ranger
   lui-même (contraire à R1).
3. **NVD seul** (champs `cisa*` des fiches) : ni usage par un rançongiciel ni veille datée du KEV
   (G2 écarte cette option).

Aucune nouvelle dépendance : `httpx`, Pydantic et `core/net` existent déjà (R14).

## Décision
Option 1, dans `plugins/cyber_cve` ; deux outils de classe LECTURE.
- **Réseau.** Les requêtes sont en HTTPS seulement, vers trois hôtes fixes (`services.nvd.nist.gov`,
  `www.cisa.gov`, `api.first.org`). Elles passent par l'anti-SSRF de `core/net`, avec l'adresse
  résolue épinglée pour la connexion. Ni redirection, ni proxy d'environnement. Le délai est de
  15 s. Le corps est plafonné à 2 Mo (NVD, EPSS) ou à 10 Mo (KEV). Il est toujours lu comme du
  JSON strict (profondeur bornée, ni NaN ni infini) ; un type annoncé autre que `application/json`
  est refusé, un type absent est accepté.
  Aucune entrée d'outil ne porte d'hôte, d'URL ou d'adresse. Le SDK MCP ignore un argument
  inconnu (constaté en écrivant le golden set) : un champ ajouté n'est donc jamais lu. Un mot-clé
  contenant un caractère de contrôle, invisible, un demi-codet isolé, un caractère privé ou non
  attribué est refusé.
- **Débit (G4)** : limiteur partagé `core/net/throttle.py`.
  - NVD : une requête toutes les 6 s sans clé, toutes les 0,6 s avec clé.
  - EPSS : une par seconde (hypothèse).
  - KEV : une par seconde ; le cache limite la lecture du flux à une fois par 24 h.
- **Clé (G3)** : `NVD_API_KEY` facultative, posée par Lucas.
  - Validation : `[A-Za-z0-9-]{1,64}` ; une autre valeur est ignorée.
  - Elle part dans l'en-tête `apiKey` du seul client NVD.
  - Elle n'apparaît jamais dans l'URL, la clé de cache, une sortie ou un journal.
- **Cache** : `var/cyber/cache/{nvd,cisa_kev,epss}`, 24 h.
  - Nom du fichier : SHA-256 de l'URL. Empreinte du corps vérifiée à la lecture : elle détecte
    une copie abîmée, pas une falsification, puisqu'elle est rangée à côté du corps. Un processus
    local qui écrit dans `var/` reste dans le périmètre de confiance (droits du compte de Lucas).
  - Écriture atomique, au mieux. Seul un corps lisible est conservé.
  - Une fiche NVD absente n'est pas conservée, car elle peut être publiée le lendemain.
  - Un catalogue KEV dont la longueur diffère de son champ `count` (copie tronquée) est refusé.
  - Chaque résultat porte la date de lecture de sa source (R10).
- **Interrupteurs** : `data.nvd`, `data.cisa_kev` et `data.epss` de `config/data_sources.yaml`,
  relus à chaque appel.
  - `cve_lookup` exige le NVD. Un KEV ou un EPSS fermé ou en panne donne une réponse dégradée,
    avec la raison dans `sources[].error`.
- **Tri (G8)** : KEV d'abord, puis EPSS décroissant, puis CVSS de base décroissant, puis
  identifiant. Le CVSS retenu est celui de la version la plus récente publiée, principal d'abord.
  Il n'y a aucun seuil. La règle est rendue avec le résultat.
- **Veille (G10).** Le KEV est filtré par dates et par éditeur ou produit.
  - NVD : la plage est de 120 jours au plus, bornes comprises, contrôlée avant toute requête.
  - Le mot-clé, à défaut `produits_suivis` (5 noms au plus), vient de
    `domain_packs/cyber/knowledge/sources.yaml`.
  - Si plus de 20 entrées correspondent, la dernière page est lue (les plus récentes).
  - Le code écarte toute entrée hors de la plage.

## Conséquences
- Un score ou un ordre vient toujours d'un outil daté. Le LLM le cite et ne le calcule pas.
- Sans clé, une veille NVD de deux pages prend au moins 6 s. Le délai d'appel du plugin est de
  180 s (ADR-052).
- Si la CVE la plus récente n'arrive plus en fin de liste, la veille NVD rend des entrées anciennes.
  Un test réel d'ordre est à prévoir dans la campagne P4 (backlog).
- Mentions des sources (NVD, CISA, FIRST) ajoutées par le code : G9, commit suivant.
- Réversible : retirer le plugin du pack suffit, aucune donnée n'est conservée hors du cache.
