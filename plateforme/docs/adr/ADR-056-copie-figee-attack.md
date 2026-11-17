# ADR-056 — Copie figée d'ATT&CK Enterprise : commande `attack-fetch`, index local, plugin `cyber_attack`

- Statut : **proposé** (G5 du complément de plan P4, validé par l'utilisateur le 27/10/2026)
- Date : 2026-10-27
- Phase : 6 (P4)

## Contexte
Le pack Cyber (défensif, R15) doit relier une technique d'attaque à ses mesures d'atténuation et
à ses stratégies de détection, sur une version d'ATT&CK figée (R10) et sans réseau à chaque appel.
Faits relevés le 27/10/2026 (métadonnées GitHub et pages attack.mitre.org, en lecture ; le bundle
n'a pas été téléchargé) :
- ATT&CK **v20.0** (13/10/2026), publiée en STIX 2.1 seulement dans `mitre-attack/attack-stix-data`.
  Tag `v20.0` = commit `20664a889568dce884a1dac0ec7b12ae3a199f51`. Le fichier
  `enterprise-attack/enterprise-attack-20.0.json` pèse 55 271 014 octets, blob git SHA-1
  `b39ce73c609d0f028841546e042ec16ffd7fe63f`.
- Licence de MITRE, gratuite et non exclusive : toute copie reproduit la mention « © 2026 The
  MITRE Corporation… » et la licence ; ATT&CK est une marque déposée (terms-of-use, R14).
- Version de la spécification ATT&CK du bundle réel (3.3.0, celle de la fixture) : `A_VERIFIER`
  au premier téléchargement.

Contraintes : G5 (l'utilisateur lance le téléchargement), R4 (kill switch), R5 (texte externe = donnée),
R7 (l'inconnu bloque), R11 (journal), R13 (un seul outil).

## Options
1. **Bundle dans git** : 55 Mo et une licence à reproduire ; écartée (G5).
2. **`mitreattack-python` ou `stix2`** : dépendances lourdes à vérifier (R14) pour lire un JSON.
3. **Commande `cerveau cyber attack-fetch`** : URL figée sur un commit, taille et blob épinglés
   dans le code, SHA-256 inscrit au premier passage, index compact local. Aucune dépendance.
4. **Lecture en ligne à chaque appel** (site, TAXII) : réseau permanent, version mouvante (R10).

## Décision
Option 3.
- **Commande**, lancée par l'utilisateur seulement : `cerveau cyber attack-fetch --version 20.0`.
  - Refus avant l'ouverture du journal, non journalisés : version malformée, kill switch engagé,
    configuration invalide, `--journal` hors de `var/`. Refus journalisés (`ERROR`) : source
    `attack` absente ou désactivée (R7), version différente de `config/data_sources.yaml`, version
    sans épinglage, puis toute erreur de téléchargement, d'empreinte ou d'écriture, et tout échec
    inattendu (mémoire, interruption).
  - Téléchargement : HTTPS vers `raw.githubusercontent.com` seul, anti-SSRF de `core/net` avec
    adresse épinglée, ni redirection ni proxy, lecture arrêtée à la taille épinglée (80 Mo au
    plus), 600 s en tout et 60 s entre deux blocs. Le kill switch est relu avant chaque bloc, avant
    l'écriture de l'index et avant celle de la configuration.
  - Contrôle : taille et blob SHA-1 git de `PINS` (`core/cyber/fetch.py`), puis SHA-256. Le premier
    passage remplace le seul marqueur `A_VERIFIER` du bloc `attack` (une ligne, fin de ligne et
    commentaire conservés ; fichier restauré si le chargeur ne le relit pas). Ensuite l'empreinte
    doit être identique, sinon refus. Le bundle n'est pas conservé.
  - Journal (R11) : `TOOL_CALL` avec version, commit, SHA-256 du bundle et de l'index écrit,
    octets, objets par type, relations.
- **Index** `var/cyber/attack/enterprise-attack-20.0.index.json`, écrit atomiquement, relu et
  validé en entier (format, version, empreinte, mention de MITRE, identifiants uniques, textes
  déjà nettoyés et sans citation ; 40 Mo et 50 000 objets au plus).
  - Domaine Enterprise ; tactiques, techniques, sous-techniques, mesures, stratégies de détection,
    groupes, logiciels, campagnes. Descriptions sur une ligne, citations (même reformées par un
    premier retrait) et caractères cachés, privés ou non attribués retirés, 2 000 caractères au
    plus. Le champ `url` d'un objet hors `attack.mitre.org` est retiré ; les liens Markdown des
    descriptions restent et sont filtrés à la sortie (`strip_foreign_links`, R5).
  - Relations : `subtechnique-of`, `revoked-by` (dans la même famille : une technique peut être
    révoquée par une sous-technique, cas de T1086 et T1059.001, `A_VERIFIER` sur le bundle réel),
    `mitigates`, `detects`, `uses` vers une technique seulement. Un lien vers un objet révoqué ou
    obsolète n'est pas affiché.
  - Doublon d'identifiant : l'objet en vigueur, puis le plus récent, puis le plus petit
    identifiant STIX ; les relations de l'objet écarté sont perdues.
- **Plugin `cyber_attack`**, un outil `attack_lookup` (LECTURE, aucun réseau, N1 au plus).
  - À chaque appel, il relit la configuration : source activée, SHA-256 connu, index de cette
    version et de cette empreinte. L'index reste en mémoire tant que son fichier ne change pas.
  - Requête : un identifiant (l'objet, puis son remplaçant s'il est révoqué) ou des mots-clés
    anglais (200 caractères, 8 mots d'au moins 2 caractères), cherchés comme sous-chaînes du nom,
    des alias et de la description. Ordre fixe, rendu avec le résultat ; 10 résultats au plus. Une
    requête avec un caractère de contrôle ou invisible est refusée sans être citée.
  - Chaque réponse porte version, commit, SHA-256, date de construction, mention de MITRE et URL
    des conditions.

## Conséquences
- Rien ne télécharge ATT&CK sans l'utilisateur ; d'ici là, `cyber_attack` répond « index absent » (R7).
- Confiance au premier usage : la taille et le blob SHA-1 limitent le risque d'un premier corps
  falsifié (une seconde préimage SHA-1 reste théorique) ; le SHA-256 protège ensuite. Un accès en
  écriture à `var/` suffit à remplacer l'index : la relecture refuse un texte non nettoyé, une
  citation ou un doublon, mais pas un index forgé de façon cohérente avec l'empreinte inscrite. La
  limite est le compte de l'utilisateur ; le SHA-256 de l'index écrit, journalisé, permet de le contrôler.
- La lecture du bundle (`json.loads`, 55 Mo) demande plusieurs centaines de Mo de RAM, une fois.
- Le signal « exfiltration » des garde-fous (M1, décision de l'utilisateur) refuse toute sortie d'outil qui
  nomme l'exfiltration : la tactique TA0010 et ses techniques restent illisibles par le pack.
  L'assouplir demanderait un ADR et l'accord de l'utilisateur (backlog).
- Nouvelle version d'ATT&CK : épinglage ajouté dans le code après lecture des métadonnées, puis
  `version` et `sha256: A_VERIFIER` remis par l'utilisateur, puis nouvelle commande.
- Réversible : supprimer `var/cyber/attack/` et retirer le plugin du pack.
