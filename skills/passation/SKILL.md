---
name: passation
description: "Quand il faut résumer la conversation pour reprendre le travail dans une autre session. Sur demande : /cerveau:passation."
disable-model-invocation: true
argument-hint: "À quoi servira la prochaine session ?"
metadata:
  triggers: >-
    « fais une passation » « document de passation » « prépare la passation » « handoff » « prépare la reprise dans
    une autre session » « résume la conversation pour la reprendre » « je reprends dans une nouvelle session »
    Ne pas utiliser pour « passation de pouvoir », résumer une vidéo (cerveau:web) ni retrouver une ancienne session
    (cerveau:brain).
---

# Passation : reprendre le travail ailleurs

D'après la skill handoff de Matt Pocock (github.com/mattpocock/skills, skills/productivity/handoff, licence MIT :
`LICENSE`), réécrite en français.

Écrire un document qui résume la conversation pour qu'une session neuve (ou un autre agent) continue sans rien
redemander.

## Où
Dans le dossier temporaire du système, **pas dans le projet** : `$TMPDIR` sinon `/tmp` (Mac, Linux), `%TEMP%`
(Windows). Nom : `passation-AAAA-MM-JJ-HHMM-<sujet>.md`. Si l'utilisateur veut la garder, il le dit : la copier
alors dans le wiki du cerveau ou son coffre Obsidian.

## Contenu
1. **But** : ce que la prochaine session doit faire. Si l'utilisateur a donné un texte après la commande, c'est le
   sujet de la prochaine session : centrer le document dessus.
2. **État** : ce qui est fait (avec la preuve : commande lancée et son résultat), ce qui est en cours, ce qui reste.
3. **Décisions prises et pourquoi**, et ce qui a été essayé sans marcher (pour ne pas le refaire).
4. **Questions ouvertes** pour l'utilisateur.
5. **Fichiers et liens** : chemins, branche, commits, PR, plans, ADR, pages du wiki. Les citer par leur chemin ou
   leur lien, **sans recopier** ce qu'ils contiennent déjà.
6. **Skills conseillées** : les skills que la prochaine session devrait charger (outil Skill), par leur nom
   (`cerveau:ecommerce`, `cerveau:preuve-avant-fini`…).
7. **Première phrase à coller** dans la nouvelle session, prête à l'emploi : « Lis <chemin du document> puis … ».

## Règles
- **Rien de sensible** : ni clé d'API, ni mot de passe, ni jeton, ni donnée personnelle (adresse, téléphone, e-mail,
  numéro de client). Les remplacer par `[retiré]`.
- Court : ce qu'il faut pour reprendre, pas l'histoire de la conversation.
- À la fin, donner à l'utilisateur le chemin complet du fichier et la phrase à coller.
