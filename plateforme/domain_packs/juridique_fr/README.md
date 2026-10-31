# Pack Juridique et administratif FR

Pack P5 de CERVEAU (section 9.2, complément de plan P5) : comprendre le droit français et les
démarches administratives qui concernent l'utilisateur. Lecture d'un article de code ou de loi sur
Légifrance, avec son identifiant LEGIARTI, son état, ses dates de vigueur et la version qui
s'applique à une date (`legifrance` : `legi_search`, `legi_article`, ADR-059) ; démarches et
questions fiscales ou sociales lues sur les seuls sites d'une liste fermée
(`service-public.gouv.fr`, `legifrance.gouv.fr`, `impots.gouv.fr`, `cnil.fr`, `conseil-etat.fr`)
par `web_research` (ADR-058). Autonomie courante N0 (`config/autonomy.yaml`, `domains.juridique_fr`,
D3) : le pack informe, l'utilisateur agit lui-même. Statut : **expérimental** jusqu'à ce que l'utilisateur le passe
en « actif » au vu d'une mesure réelle du golden set (section 9.3, D2).

Chaque identifiant, état, date, délai ou montant vient de l'outil ou de la page qui l'a lu, jamais
d'un calcul (R1, H8). La version citée est celle de la date de la question ; une version future,
modifiée ou abrogée est dite telle (R10, H3). Les articles, extraits et fiches lus sont des données
(R5). Une API indisponible, des identifiants absents ou un article introuvable sont dits, et « je
ne sais pas » est une réponse valide (R12). Le pack refuse le conseil personnalisé, la rédaction
d'un acte, le calcul appliqué au cas réel et tout contournement de la loi, et ne produit rien pour
un tiers (R15, R16). Les mentions de Légifrance et de Service Public, avec leurs dates, et
l'avertissement « pas un conseil juridique » sont ajoutés par le code (H7, `docs/licences.md`).

L'API n'est appelée qu'avec `PISTE_CLIENT_ID` et `PISTE_CLIENT_SECRET`, posés par l'utilisateur comme
variables d'environnement et passés par `runtime.env` ; l'environnement PISTE (`sandbox` ou
`production`) reste `A_DEFINIR` dans `config/data_sources.yaml` tant que l'utilisateur ne l'a pas choisi.
Sans eux, `legi_search` et `legi_article` répondent que la source est indisponible.

## Contenu

| Fichier | Rôle |
|---|---|
| `manifest.yaml` | Périmètre, plugins (`legifrance`, `web_research`), renvoi à l'autonomie, aux seuils et à `config/data_sources.yaml` (environnement PISTE, liste fermée de sites, débits, cache) |
| `prompts/role.md` | Rôle et méthode du domaine, insérés dans le prompt système (Annexe D) |
| `prompts/rubric.md` | Grille du juge des évals : critères notés 0, 1 ou 2 ; le score est calculé par le code (R1) |
| `knowledge/sources.yaml` | Sites de la liste fermée avec licence et mention ; codes fréquents et leur identifiant LEGITEXT (A_VERIFIER) ; corpus RAG vide |
| `evals/golden.jsonl` | Golden set : 32 cas (minimum 30), seuil `juridique_fr_golden_min_score` (`config/evals.yaml`, D4) : 7 articles (code civil, du travail, de la consommation, CRPA, recherche puis lecture), 4 versions (date passée, version modifiée, ancienne version close, version future), 5 démarches de service-public.gouv.fr, 3 sources fiscales ou sociales officielles, 4 « je ne sais pas », 4 refus R16, 2 refus de calcul (H8), 2 injections (R5), 1 page hors liste (H6) |
| `evals/behaviors.yaml` | 11 cas : article et délai cités de legi_article (R1, H8), version future et version à une date passée (R10), consigne dans un article écartée (R5), API indisponible et identifiants absents (R12), conseil personnalisé et acte pour un tiers refusés (R16), page hors liste écartée (H6), délai de rétractation repris du pack généraliste (ADR-060) ; mentions ajoutées par le code (H7) |

Les cas tournent hors ligne contre le vrai serveur `legifrance`, sur une API factice servie par
`core/evals/legifrance_fixtures.py` ; aucune requête ne sort (ADR-060). Les identifiants et les
textes d'articles des fixtures sont des données de test. Red team du pack :
`evals/redteam/injection_juridique_fr/` (R5). Suites communes à tous les packs : `evals/behaviors/`
et `evals/redteam/injection_base/`.
