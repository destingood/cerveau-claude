# Fiche 06 — Être trouvé sur Google et cité par les assistants IA

Objectif : quand quelqu'un cherche « map zone wars 2v2 », « meilleure map pour s'entraîner en box fight » ou
« code map 1v1 fortnite », sur Google ou dans ChatGPT, Perplexity ou Gemini, que ta map soit dans la réponse.
Méthode générale du GEO (robots des moteurs et des IA, mesure, ce qui ne sert à rien) : fiche 07 du cerveau
e-commerce (`skills/ecommerce/references/07-geo.md`). Ici, ce qui est propre à une île Fortnite.

## 1. La page fortnite.com de l'île (elle existe déjà)

Observée le 14/11/2026 sur des îles publiées [FAIT — lecture des pages et du robots.txt de fortnite.com] :

- Adresse : `https://www.fortnite.com/@<code créateur>/<code de l'île>` ; page créateur : `https://www.fortnite.com/@<code créateur>`.
- Contenu : miniature paysage, titre en H1, créateur, classification d'âge, bouton de jeu, **la description de l'île
  telle quelle**, les quatre tags, le code, les joueurs actifs, captures et vidéo, liens sociaux du créateur.
- Le `<title>` est « <TITRE> <code> by <créateur> - Fortnite » ; la méta-description est générique (« Come play in
  Fortnite. Enter the map code … ») ; aucune donnée structurée ; versions par langue (`?lang=fr`…).
- Le robots.txt n'en bloque pas l'accès, et des pages d'îles de box fight apparaissent dans les résultats de recherche,
  avec un extrait tiré de leur description. Le sitemap de fortnite.com ne les liste pas.

Conséquence : **le titre et la description de l'île sont aussi ton SEO**. Le terme exact du format dans le titre
(fiche 03) et des faits dans la description servent deux fois : à la recherche du jeu et à Google.
Remplir les liens sociaux du profil créateur : ils relient cette page à ta page web et à tes vidéos.

## 2. Une page à toi (facultatif, 0 €)

Une page à ton nom de domaine ou sur un hébergement gratuit (GitHub Pages, Cloudflare Pages) peut répondre en détail,
en français, à ce que la page fortnite.com ne dit pas.

```
python scripts/page_ile.py --modele > ile.json      # à remplir
python scripts/page_ile.py ile.json --controle      # ce qui manque
python scripts/page_ile.py ile.json                 # écrit index.html
```

Ce que la page fait pour être citée [FAIT pour Google : contenu utile, page indexable ; HYPOTHÈSE pour le poids de
chaque élément dans les réponses IA] :

- la réponse d'abord : nom, format, code d'île en clair, nombre de joueurs, en haut de page ;
- des faits vérifiables et datés (« dernière mise à jour »), une liste des nouveautés ;
- une FAQ **visible** faite des vraies questions des joueurs (le balisage FAQ ne donne plus de résultat enrichi ; la
  FAQ sert aux lecteurs et aux assistants qui lisent la page) ;
- des données structurées `VideoGame` (genre, joueurs, auteur, dates) : de la clarté pour les moteurs, aucune promesse
  d'affichage ;
- ni traceur, ni cookie, ni police distante ; la mention exigée par Epic en pied de page (règle 3.1).

Ce que la page ne doit pas faire : ressembler à un site d'Epic, utiliser le logo Fortnite, ou un nom de domaine qui
fait croire à un site officiel (règles 3.1 ; politique « Fan Content » d'Epic, règles 1.8 et 1.11). Pas de mot
« fortnite » seul dans le nom de domaine [HYPOTHÈSE prudente, d'après la règle 1.11 de cette politique].

Une page par map, ou une page créateur qui les liste toutes, liées entre elles. Puis : Search Console et Bing Webmaster
Tools, sitemap soumis (méthode : `skills/ecommerce/references/06-seo.md`).

## 3. Les sites qui listent les îles (sources tierces)

Ils tirent souvent leurs données de l'API publique d'Epic, qu'Epic ouvre aux plateformes tierces [FAIT].
Le fonctionnement de chacun n'est pas documenté par Epic [NON VÉRIFIÉ] :

- fortnite.gg/creative : classements et nombre de joueurs, pages créateurs ; l'inscription semble automatique.
- fchq.io (Fortnite Creative HQ), dropnite.com (propose « Submit Your Map ») : à vérifier sur place avant d'y passer du
  temps.

Ces pages sont souvent celles que Google et les assistants citent pour « meilleure map … » : y être, avec la même
description et le même titre partout, aide les moteurs à relier les sources entre elles [HYPOTHÈSE].

## 4. Être cité par les assistants IA

- Les assistants qui cherchent sur le web (ChatGPT, Perplexity, Copilot, Gemini, Aperçus IA de Google) citent des pages
  qu'ils trouvent : la page fortnite.com, ta page, les sites de listes, les vidéos et les fils de discussion.
- Le contenu qui revient dans ces réponses pour une requête de type « meilleure map … » : des listes comparatives et des
  avis de joueurs [HYPOTHÈSE — à vérifier en posant soi-même la question, chaque mois, et en notant les sources citées].
- Mesure simple : poser les cinq requêtes de ta niche à deux assistants, noter si ta map sort et quelles pages sont
  citées, garder le relevé dans le cerveau (`brain obs …`). Méthode complète : skill `searchfit-seo:ai-visibility`.

## 5. Vidéo : YouTube est aussi un moteur

Une vidéo de la map (vrai jeu, code dans le titre ou la description) peut sortir sur Google et être citée par les
assistants. Titre, description, chapitres : skill `cerveau:youtube`.
