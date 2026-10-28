# Pack Cyber

Pack P4 de CERVEAU (section 9.2, complément de plan P4) : cybersécurité strictement défensive pour
les systèmes de Lucas. Fiche d'une à dix CVE (NVD, catalogue KEV de la CISA, EPSS de FIRST) et
ordre de priorité rendu par une règle déterministe et citée (`cyber_cve`, ADR-055) ; veille datée
du KEV ou du NVD ; cartographie ATT&CK Enterprise depuis une copie locale vérifiée par empreinte
(`cyber_attack`, ADR-056) ; durcissement et OWASP Top 10 des applications LLM par des pages
officielles lues à la demande (`web_research`). Autonomie courante N0 (`config/autonomy.yaml`,
`domains.cyber`, D3) : le pack lit et propose des actions défensives que Lucas exécute lui-même ;
N1 n'est pas livré et se gagnera par les évals réelles (R9). Statut : **expérimental** jusqu'à ce
que Lucas le passe en « actif » au vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque score, date, rang et identifiant vient de l'outil qui l'a lu (R1) ; un objet ATT&CK révoqué
ou obsolète est dit tel. Les descriptions de CVE, les entrées du KEV, les objets ATT&CK et les
pages lues sont des données (R5). Une source non lue (NVD, KEV, EPSS indisponible, index ATT&CK
absent ou altéré) est dite, et « je ne sais pas » est une réponse valide (R12). Le pack refuse
l'exploit, la preuve de concept, le logiciel malveillant, le scan, le contournement d'une
protection et la recherche de cibles (R15, D20) ; aucun outil ne prend d'hôte, d'adresse ni de port
cible. Les mentions des sources (NVD, programme CVE, CISA, FIRST, MITRE, OWASP) sont ajoutées par le
code (G9, `docs/licences.md`).

L'index ATT&CK n'existe qu'après `uv run cerveau cyber attack-fetch`, lancé par Lucas ; sans lui,
`attack_lookup` répond qu'il est absent.

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`cyber_cve`, `cyber_attack`, `web_research`), renvoi à l'autonomie, aux seuils et à `config/data_sources.yaml` (hôtes, débits, cache, plafonds, empreinte d'ATT&CK) |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Guides OWASP lus à la demande, licence et date de vérification ; `produits_suivis` (vide, rempli par Lucas) ; corpus RAG vide |
| `evals/golden.jsonl` | Golden set : 31 cas (minimum 30), seuil 0,80 (`config/evals.yaml`, D4) : fiches de CVE (KEV, hors KEV, sans CVSS, EPSS indisponible, rançongiciel, deux scores), priorisation, veille du KEV et du NVD, ATT&CK (sous-technique, révoquée, obsolète, atténuation), OWASP, « je ne sais pas », refus R15 et R16, injection |
| `evals/behaviors.yaml` | 10 cas : scores et ordre cités de cve_lookup (R1), consigne dans une entrée du KEV écartée (R5), index altéré et EPSS indisponible (R12), logiciel malveillant, recherche de cibles et preuve de concept refusés (R15), bulletin pour des clients refusé (R16), bonne pratique de sécurité routée vers le pack (ADR-057) |

Les cas tournent hors ligne contre les vrais serveurs `cyber_cve` et `cyber_attack`, sur des
données factices servies par `core/evals/cyber_fixtures.py` et un bundle ATT&CK de synthèse
(`core/evals/attack_sample.py`) ; aucune requête ne sort (ADR-057). Red team du pack :
`evals/redteam/injection_cyber/` (12 cas, R5). Suites communes à tous les packs : `evals/behaviors/`
et `evals/redteam/injection_base/`.
