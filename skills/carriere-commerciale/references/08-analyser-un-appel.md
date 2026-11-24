# Fiche 08 — Analyser un appel de vente ou un jeu de rôle

Objectif : progresser vite après chaque appel, entretien de vente ou jeu de rôle, avec un débrief court et
honnête : ce qui a marché, **une seule** chose à changer, et la phrase à dire la prochaine fois.

## 0. Avoir la transcription [CONSEIL]

- **Toujours avec l'accord de l'autre personne** pour enregistrer un vrai client ; sinon, écrire de mémoire juste
  après l'appel, ou s'entraîner en jeu de rôle avec Claude (fiche 05) et garder la conversation.
- Une réplique par ligne : `Moi : …` / `Client : …`. La dictée vocale ou la transcription de l'outil d'appel suffit ;
  pas besoin de l'orthographe parfaite.
- Rien de personnel sur le client (nom, téléphone, adresse) : le remplacer par « Client ».

## 1. Les repères chiffrés

`python scripts/appel.py transcription.txt` (ou `--moi "Prénom"` si le vendeur a un autre nom dans le texte) donne :
part de parole du vendeur, questions posées (ouvertes ou fermées), plus long monologue, reformulations, mots de
remplissage, objections du client et la réponse qui a suivi, prochaine étape proposée ou non.

Ce sont des repères, pas une note [CONSEIL] : un vendeur qui parle beaucoup peut avoir bien fait (démonstration
demandée). Aucun pourcentage « idéal » n'est donné ici : les chiffres qui circulent (« parlez 40 % du temps »)
viennent d'études d'éditeurs de logiciels, sur d'autres métiers [NON VÉRIFIÉ]. Comparer surtout **ses** appels entre
eux, semaine après semaine (`progression.py`, fiche 07).

## 2. La grille du débrief (lire la transcription avec les repères)

| Temps de la vente (fiche 05, section 0) | Ce qu'on regarde |
|---|---|
| Accueillir | le premier contact : bonjour, une question, pas un discours |
| Découvrir | au moins trois questions avant de montrer un produit ; des questions ouvertes (« pour quel usage ? ») |
| Reformuler | « si je comprends bien… » avant de proposer ; le client a dit oui ? |
| Proposer | deux produits, pas dix ; chaque argument relié à un besoin dit par le client |
| Objections | écoutée jusqu'au bout, reformulée, puis une réponse ou une question (« qu'est-ce qui vous fait hésiter ? ») ; jamais contredite de front |
| Conclure | une prochaine étape précise : « je vous le prépare ? », un rendez-vous, une date |

## 3. Le rendu à l'utilisateur (court, pour quelqu'un de dyslexique)

1. **Deux points forts**, avec la phrase exacte de la transcription.
2. **Une seule chose à changer**, la plus utile.
3. **La phrase à dire la prochaine fois**, prête à apprendre (une ou deux lignes).
4. **Un exercice** : rejouer ce passage en jeu de rôle avec Claude, maintenant ou avant le prochain appel.

Ne jamais relever les fautes de la transcription. La leçon se garde dans le cerveau (`brain add -t learning … --commun
non`), sans le nom du client.
