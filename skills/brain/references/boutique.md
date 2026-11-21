# 🧠 Cerveau — boutiques suivies

Les boutiques en ligne suivies par la skill e-commerce. Commande : `python "$HOME/.claude/brain/brain.py" <commande>`.

## Skills métier livrées avec le cerveau
**Cerveau e-commerce** (`/cerveau:ecommerce` en plugin, `/ecommerce` en installation classique) : faire décoller une
boutique en ligne sans pub et avec des outils gratuits (diagnostic, offre et marges, site et tunnel de vente, premiers
clients, vidéo et algorithmes, SEO, GEO, e-mails, gestion, conformité, pilotage du navigateur). Chaque boutique est
suivie par le cerveau : données privées (jamais dans le cerveau commun), comprises dans les sauvegardes.

| But | Commande |
|---|---|
| Boutiques suivies (dernière semaine, plan, dernier audit) · en faire suivre une (fichier de suivi + fiche contexte privée) | `boutique` · `boutique ajouter "Nom" --url https://… [--type physique\|mode\|createur\|occasion\|niche\|prevente\|local\|numerique\|b2b] [--chemin plateforme\|0euro] [--marge-commande 12,5]` |
| Plan décollage en à-faire datés (72 h, 14 jours, 30-60-90, adapté au type), rappelés au démarrage | `boutique plan <boutique> [--debut 20/10] [--court] [--force]` |
| Chiffres d'une semaine complète → taux, test statistique contre les semaines d'avant, marge par heure par canal, goulot probable | `boutique kpi <boutique> --sessions … --ajouts … [--checkouts …] --commandes … [--ca …] [--heures …] [--canal nom:sessions:commandes[:heures]] [--semaine 12/10] [--note "…"]` |
| Audit SEO/GEO gardé en historique (corrigé, nouveau) ; conformité légale, pages du sitemap, vitesse | `boutique audit <boutique\|url> [--conformite] [--pages 10] [--vitesse] [--complet] [--rapport audit.md]` |
| Revue (chiffres, plan, audits, panels, trois priorités) · réglages | `boutique bilan <boutique> [--md bilan.md]` · `boutique regler <boutique> url=… marge=… seuil.ajout=6` |
| Panel de clients simulés (skill, module 17) gardé dans le suivi · variante mise en ligne → les relevés disent si le panel avait vu juste | `boutique panel <boutique> [--importer <dossier>]` · `boutique panel <boutique> --applique S1 [--variante B] [--le 02/11]` |

Fiche « Boutique <nom> — fiche contexte » : `q "boutique <nom>"` ; décisions et apprentissages en `add` (chiffres en
`--commun non`).
