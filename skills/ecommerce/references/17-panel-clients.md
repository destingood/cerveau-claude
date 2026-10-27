# Module 17 — Panel de clients simulés (tester avant de lancer)

Objectif : avant de montrer une fiche, un prix, une idée de produit ou une accroche à de vrais clients, la faire juger
par un panel de personas variées jouées par Claude, pour trouver **les objections, les informations qui manquent et la
variante la plus solide**. Zéro euro, aucune clé d'API : Claude joue le panel avec l'abonnement de l'utilisateur.

Sommaire : 1. Ce que c'est, ce que ce n'est pas · 2. Préparer · 3. Faire jouer le panel · 4. Tour « réseau » et
événement · 5. Lire la synthèse · 6. Vérifier pour de vrai · 7. Limites et garde-fous

## 1. Ce que c'est, ce que ce n'est pas

La méthode reprend la chaîne de MiroFish [FAIT : dépôt 666ghj/MiroFish, lu le 27/10/2026, AGPL-3.0], un moteur de
« prédiction » par essaims d'agents bâti sur OASIS (camel-ai/oasis, Apache-2.0) : une graine (documents) → des
personas avec leur caractère et leur mémoire → des interactions sur un faux réseau social → un rapport. MiroFish
demande un serveur, une clé d'API LLM et un compte Zep Cloud ; ici, rien de tout cela et **aucune ligne de leur code** :
`scripts/panel_clients.py` tire les personas et fait les calculs, Claude et ses sous-agents jouent les personas.

| Bon usage | Mauvais usage |
|---|---|
| Lister les objections et les questions avant de publier une fiche | Annoncer « 62 % des clients achèteraient » |
| Comparer deux versions d'une fiche, deux accroches, deux prix (sens de l'écart) | Prévoir un taux de conversion, un chiffre d'affaires, une taille de marché |
| Repérer les segments chauds et froids (canal, motivation, budget) | Remplacer les vrais retours clients ou une vraie étude |
| Choisir les deux prix à tester pour de vrai (module 02, section 4) | Fixer un prix sans test réel |

Ce que dit la recherche, en bref :
- Des réponses de GPT-3 conditionnées par des profils réels reproduisent des tendances de groupes humains [FAIT :
  Argyle et al., « Out of One, Many », Political Analysis 31, 2023].
- GPT-3.5 donne des consentements à payer de grandeur réaliste et une demande qui baisse quand le prix monte [FAIT :
  Brand, Israeli et Ngwe, « Using GPT for Market Research », document de travail HBS 23-062, 2023].
- Mais les réponses synthétiques sont **moins variées** que les vraies, changent avec la formulation et dans le temps,
  et ne valent pas pour des tests statistiques [FAIT : Bisbee et al., « Synthetic Replacements for Human Survey
  Data? », Political Analysis 32, 2024].

D'où la règle : **les écarts et les objections sont des hypothèses ; les niveaux absolus ne valent rien.**

## 2. Préparer

1. **Le texte testé** (un fichier par variante), exactement ce que la personne voit : premier écran, description,
   prix, livraison, retours ; pour une vidéo, le script des 3 premières secondes et la légende ; pour un e-mail,
   l'objet, l'aperçu et le début.
2. **Le contexte** (fichier `--contexte`) : la fiche contexte du cerveau (`brain q "boutique <nom>"`), les conditions
   de livraison et de retour, les prix des concurrents relevés. Jamais de donnée personnelle d'un client.
3. **La cible** : traduis-la en répartitions plutôt qu'en texte seul, en gardant des voisins de la cible (ils disent
   pourquoi la cible n'est pas plus large) — ex. `--repartition "genre=femme:75,homme:25" --repartition
   "age=25-34:40,35-44:40,45-54:20"`. Le type de boutique (`--boutique-type`) règle les canaux et les motivations.
4. **La taille** : 24 personas en 4 lots par défaut ; test rapide `--nb 12 --lots 2` ; décision importante
   `--nb 40 --lots 5`. En dessous de 16 personas, un écart entre variantes ne veut presque rien dire.

```
python scripts/panel_clients.py preparer --type fiche --nom "Sac cabas en lin" --stimulus fiche-actuelle.md \
  --variante fiche-nouvelle.md --prix 34,90 --boutique-type mode --contexte contexte.md \
  --repartition "genre=femme:75,homme:25" --dossier panel-sac-lin
```

Types : `fiche` (page de vente), `prix` (un texte, plusieurs prix : `--prix "29,90/34,90/39,90"`), `produit` (idée
avant lancement : prix maximum demandé), `contenu` (accroche : arrêt du défilement, action). La variante A est la
version actuelle (`--actuelle`), sauf pour une idée de produit.

## 3. Faire jouer le panel

**Avec sous-agents (Claude Code)** — le mode recommandé, le plus proche de MiroFish : des agents indépendants
donnent des avis plus variés qu'un seul.
1. `preparer` écrit une consigne par lot (`t1-lot1.md`…) et affiche les messages à envoyer.
2. Lance **tous les lots dans un seul message** (un appel à l'outil Agent par lot, sous-agent généraliste), chacun
   avec : « Lis `<dossier>/t1-lotN.md` et suis ses consignes exactement. » Chaque sous-agent écrit son fichier JSON.
   Pour économiser le quota, un modèle plus léger suffit pour jouer les personas.
3. `python scripts/panel_clients.py reponses <dossier>` intègre les réponses et dit ce qui manque : relance seulement
   le lot incomplet.

**Sans sous-agents** (chat claude.ai, ou à la demande) : joue les lots l'un après l'autre, en relisant chaque fois la
consigne du lot, et écris les fichiers ; ou `--lots 1`. Le panel sera plus homogène : dis-le dans le rapport.

Règles pour l'orchestrateur : ne corrige jamais les réponses des personas, ne les « améliore » pas ; une réponse
illisible se relance. Coût : environ 70 000 tokens par sous-agent et par tour, surtout le coût fixe d'un sous-agent
[FAIT : mesuré le 27/10/2026, lot de 4 personas × 2 variantes], soit de l'ordre de 550 000 tokens pour 4 lots et 2
tours. Pour économiser : moins de lots plus gros (`--lots 2`), un seul tour, un modèle plus léger. Annonce le coût
avant un gros panel.

## 4. Tour « réseau » et événement

`python scripts/panel_clients.py tour <dossier> [--evenement "…"]` prépare le tour suivant : chaque persona lit un
fil d'avis d'autres personas, choisi comme le ferait un réseau (des gens qui lui ressemblent, des avis marqués, au
moins un pour et un contre), et peut changer d'avis selon sa sensibilité aux avis des autres. Puis mêmes étapes
qu'au tour 1.

Quand le faire : produits qui se vendent par le bouche-à-oreille, les communautés ou les créateurs (modules 04, 05),
ou pour voir si une objection se propage. L'**événement** (la « vue de Dieu » de MiroFish) injecte une variable à
tout le panel : « livraison offerte dès 40 € », « un avis négatif sur la qualité circule », « rupture de stock d'une
semaine », « un concurrent baisse son prix de 20 % ». 4 tours au plus.

## 5. Lire la synthèse

`python scripts/panel_clients.py synthese <dossier> --rapport rapport.md` (et `synthese.json` dans le dossier).

| Bloc | Ce qu'on en fait |
|---|---|
| Intention par variante, test du signe | « Écart net » = hypothèse forte à tester pour de vrai ; « léger » ou « aucun » = garder la version actuelle et travailler les objections |
| Objections classées, avec les mots des personas | Lever les deux premières sur la page (module 03) : preuve, information, garantie, livraison |
| Questions avant d'acheter | Les réponses vont dans la fiche et la FAQ (modules 03, 07) |
| Segments chauds et froids | Canal et angle prioritaires (modules 04, 05) ; objection propre au segment froid |
| Prix maximum (types prix et produit) | Choisir deux prix à tester pour de vrai, vérifier la marge (`unit_economics.py --prix-test`) |
| Arrêt et actions (type contenu) | Garder l'accroche qui arrête le plus, la publier, mesurer la rétention réelle (module 05) |
| Effet du fil | Une objection qui se propage au tour 2 est à traiter avant le lancement |
| Alertes | Réponses homogènes, panel trop enthousiaste, panel trop petit : le dire, relativiser |

Toute nouvelle version de texte repasse par `scripts/relire_texte.py` avant publication.

## 6. Vérifier pour de vrai

1. `brain boutique panel <boutique> --importer <dossier>` : le panel entre dans le suivi de la boutique (privé), avec
   un identifiant (S1, S2…).
2. Mets en ligne la variante choisie, **une seule modification à la fois**, puis `brain boutique panel <boutique>
   --applique S1 --variante B [--le 02/11]`.
3. Chaque lundi, `brain boutique kpi` comme d'habitude. Le cerveau compare les semaines entières d'avant et d'après la
   mise en ligne (taux d'ajout au panier pour une fiche, conversion pour un prix ; test de deux proportions) et dit :
   ✓ vu juste, ✗ contredit, ou ≈ pas encore de variation réelle. `brain boutique panel <boutique>` et le bilan
   affichent la **fiabilité du panel** pour cette boutique.
4. Leçon durable (« sur cette boutique, le panel voit juste sur les fiches, pas sur les prix ») : `brain add -t
   learning … --commun non`.

Idée de produit et contenu : pas de vérification automatique ; compare à la main (précommandes, liste d'attente,
rétention et clics réels).

## 7. Limites et garde-fous

- Une IA ne connaît ni la boutique, ni ses vrais clients, ni le prix du concurrent de la rue d'à côté : sans contexte,
  le panel juge dans le vide. Il ignore aussi la saison, la météo, l'actualité.
- Personas = stéréotypes possibles : relis les réponses qui caricaturent un âge, un genre ou un lieu, et ne tire
  aucune conclusion sur un groupe réel.
- **Jamais** de réponse simulée présentée comme un avis, un témoignage, une note ou une statistique de clients, ni
  sur le site, ni dans une publicité, ni auprès d'une banque ou d'un partenaire : pratique commerciale trompeuse
  (C. conso., art. L121-2 ; faux avis : art. L121-4, 27° et 28°). En interne seulement, nommée « simulation ».
- Jamais de donnée personnelle d'un vrai client dans une persona ou dans le contexte.
- Le panel ne remplace pas les vrais signaux : messages et avis clients, enregistrements de sessions, ventes.
