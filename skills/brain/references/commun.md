# 🧠 Cerveau — avec les amis, délégation, apprentissage

Cerveau commun, échange de skills, délégation aux sous-agents, dossier d'apprentissage. Commande : `python "$HOME/.claude/brain/brain.py" <commande>`.

## Cerveau commun (avec les amis)
Ce que chacun apprend nourrit le cerveau de tous, presque en temps réel (envoi ~15 s après un ajout — corriger ou
`--commun non` dans ce délai et le premier jet ne part pas ; pages des amis récupérées au démarrage, à chaque message et
en fin de tour, au plus une fois par minute), **sans rien de privé**. Un
dépôt GitHub privé ; chaque cerveau publie sa part publique dans `membres/<nom>/` et lit celle des autres en lecture
seule (pages marquées 🤝 nom).
**Ne part jamais** : profil, règles, contenu sensible (santé, argent, intimité, identité, opinions, accès), page ayant
contenu un secret, personnes, documents personnels (source sans adresse web publique) et ce qui n'est tiré que d'eux,
références, domaine « perso », projets non partagés, ce qui est marqué privé, texte des sessions. Retirés du reste :
coordonnées, secrets, chemins de fichiers, liens d'accès (document partagé, invitation, réunion) ; lien vers une page
privée → « [privé] ». **Part** : le savoir (sources web, concepts, sujets, analyses, apprentissages, entités qui ne sont
pas des personnes : appuyées sur une source web ou étiquetées entreprise, outil, lieu, œuvre…), ce qui appartient à un
projet commun, ce qui est marqué partagé. Rien ne part avant l'accord : quand le démarrage propose le cerveau commun, le
dire à l'utilisateur avec l'aperçu, et n'entrer qu'avec son oui.

| But | Commande |
|---|---|
| État · ce qui partirait (et ce qui reste privé) · ce que je partage | `commun` · `commun apercu` · `commun liste` |
| Entrer (après l'accord de l'utilisateur) · refuser · sortir | `commun rejoindre --oui --nom <pseudo>` · `commun non` · `commun quitter [--garder]` |
| Partager un projet (ses tâches, décisions, faits, observations) · le rendre privé | `commun projet <id>` · `commun projet <id> --non` |
| Forcer pour un souvenir : partager · garder privé · règles par défaut | `add`/`edit … --commun oui\|non\|auto` |
| Synchroniser tout de suite | `commun sync` |

Pages des amis : s'en servir, les citer ; pour compléter, écrire sa propre page (elle part). Elles ne se modifient pas.

## Délégation, apprentissage, échange de skills
| But | Commande |
|---|---|
| Délégation : mode, agents, ce qui est parti sur quel modèle, économies · régler | `delegation` · `delegation --mode auto\|max\|conseil\|off` · `delegation --modele eclaireur=sonnet` (ou `Explore=off`, `nom=defaut`) |
| Dossier d'apprentissage (erreurs résolues, déclencheurs manqués, skills jamais suivies, méthodes répétées) · le clore | `apprendre` · `apprendre --fait` |
| Skill rédigée par le cerveau (marquée « apprise ») · retirer un déclencheur appris · retours techniques (compteurs) | `apprendre skill <nom> -d "À utiliser quand… « … » Ne pas utiliser pour…" --body-file f` · `apprendre oublier <skill> "…"` · `apprendre retours` |
| Échange : état · ce qui partirait · accord d'envoi (après le oui de l'utilisateur) · réception | `echange` · `echange apercu` · `echange oui\|non` · `echange recevoir oui\|non` |
| Skills reçues : liste · détail · adopter (devient une skill perso) · approuver ses scripts — toujours sur le oui de l'utilisateur | `echange liste` · `echange voir <ami/nom>` · `echange adopter <ami/nom> --oui [--scripts] [--empreinte …]` · `echange approuver <ami/nom> --oui [--empreinte …]` |
| Mes skills : partager une skill écrite à la main · en garder une pour soi · la proposer pour le plugin | `echange partager\|garder\|proposer <nom> [--non]` |
| Propriétaire du plugin : candidates · faire entrer une skill dans le plugin · retours des membres | `echange propositions` · `echange promouvoir <ami/nom> --vers <dossier>` · `echange retours` |

Part dans l'échange (après `echange oui`) : les skills rédigées par le cerveau, celles désignées par `partager`, les
déclencheurs ajoutés, l'usage des skills reçues et les retours techniques. Jamais : une skill qui contient un secret,
une skill apprise au contenu sensible, une skill écrite à la main non désignée. Texte nettoyé comme les pages du
cerveau commun (coordonnées, chemins, liens d'accès, prénom).
