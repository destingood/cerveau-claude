# Fiche 07 — Monter d'échelon : les preuves, la promotion, changer d'entreprise

## 1. Ce qui fait monter

En vente, on monte sur des **résultats visibles** : objectifs atteints, clients satisfaits, aide aux collègues. Les
fiches métiers parlent d'« atteindre les objectifs de vente individuels et collectifs » et, à l'échelon suivant, de
« coordonner une équipe » [FAIT — France Travail, fiche D1212].

Chaque semaine (5 minutes), noter ce qui se compte en magasin : clients conseillés (`--conversations`), ventes
conclues (`--signes`), chiffre vendu (`--ca`), objectif (`--objectif-ca`) :
`python scripts/progression.py noter --conversations 180 --signes 41 --ca 14500 --objectif-ca 13000`.
Puis `progression.py bilan` chaque mois, et `progression.py preuves` avant un entretien.

## 2. Les signaux qu'on est prêt

[CONSEIL]
- Objectif atteint ou dépassé plusieurs mois de suite.
- On forme déjà les nouveaux, on remplace le responsable quand il est absent.
- On connaît les chiffres du rayon, pas seulement les siens.
- Le titre suivant est en route (TP Manager d'établissement marchand, niveau 5 : fiche 02).

## 3. Promotion interne ou changement d'entreprise ?

- Chez les cadres en 2026 : 68 % de ceux qui ont changé de poste en interne et 61 % de ceux qui ont changé
  d'entreprise ont été augmentés, contre 42 % de ceux restés au même poste ; « avant 40 ans, la mobilité interne
  comme externe favorise l'évolution salariale » [FAIT — APEC, baromètre 2026 de la rémunération des cadres, d'après
  sa synthèse]. Ce chiffre dit **combien** ont été augmentés, pas de combien.
- Tous salariés, 2021-2022 : ceux qui ont changé d'employeur ont gagné en moyenne +2,9 % la première année, contre
  +5,7 % pour ceux restés ; c'est l'inverse pour les CDD (+13,2 % contre +7,8 %) [FAIT — Insee, « Emploi, chômage,
  revenus du travail », édition 2024].

Lecture [CONSEIL] : changer d'entreprise rapporte surtout quand on change aussi **de poste** (vendeur → responsable,
magasin → vente aux entreprises), ou quand on sort d'un CDD. Changer pour le même poste ne rapporte pas toujours.

## 4. Le plan sur plusieurs années

[CONSEIL ; durées indicatives tirées de la fiche 01 : « quelques années », « trois ans minimum »]

| Étape | Objectif | Preuve à obtenir |
|---|---|---|
| Vendeur (alternance ou CDI) | Atteindre ses objectifs, finir le titre de niveau 4 | Mois au-dessus de l'objectif, titre obtenu |
| Vendeur expert | Être la référence d'une gamme (informatique, téléphonie) | Meilleur vendeur du rayon, formation des nouveaux |
| Chef de rayon ou adjoint | Faire réussir une équipe | Objectifs du rayon tenus, titre de niveau 5 |
| Directeur de magasin | Tenir le chiffre et l'équipe d'un magasin | Résultats du magasin |
| Directeur régional, ou vente aux entreprises | Plusieurs magasins, ou de plus gros contrats | Plusieurs années de résultats |

À chaque étape : `brain add -t decision -T "Carrière : <étape visée>" -b "preuves à réunir, date de revue" --commun non`.
