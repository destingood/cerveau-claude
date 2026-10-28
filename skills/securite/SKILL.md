---
name: securite
description: "Liste de contrôle sécurité avant de livrer ou de relire du code exposé (site, API, formulaire, upload, connexion, cookies, webhook, appel d'une URL reçue, XML, archive, prompt d'IA nourri de contenu externe) : par classe de faille, la règle et la bibliothèque sûre par défaut (Python, JS/TS, PHP, Go). Exemples : « sécurise ce code », « faille / XSS / injection SQL / CSRF », « est-ce que c'est sécurisé ». Ne pas utiliser pour un script local sans entrée extérieure."
---

# Sécurité : liste de contrôle du code exposé

Principe : prendre l'outil qui rend la faille impossible par défaut (protection intégrée du framework d'abord,
sinon une bibliothèque de la liste) plutôt que de compter sur la vigilance à chaque ligne. Le moins de code qui marche
vaut aussi ici : pas de bibliothèque en plus si le framework le fait déjà.

Source des bibliothèques : awesome-secure-defaults (github.com/tldrsec/awesome-secure-defaults, lue le 29/10/2026).
Vérifier qu'une bibliothèque est maintenue avant de l'ajouter. *(std)* = bibliothèque standard de Python, hors liste.

## 1. Repérer les entrées extérieures
Formulaire, paramètre d'URL, en-tête, cookie, fichier envoyé, webhook, réponse d'une API tierce, texte lu par une IA.
Pour chacune : où va-t-elle (base, HTML, chemin, URL appelée, commande, prompt) ? → la ligne du tableau.

## 2. Par classe de faille

| Faille | Règle | Sûr par défaut |
|---|---|---|
| Injection SQL | requêtes paramétrées ou ORM ; jamais de f-string ni de concaténation | paramètres du pilote (`?`, `%s`) ; Rails : safe-active-record |
| Injection de commande | liste d'arguments, jamais `shell=True` avec une entrée | `subprocess.run([...])` *(std)* |
| XSS | échappement automatique des gabarits ; HTML d'utilisateur → assainisseur à liste blanche | JS : DOMPurify ; Python : markupsafe, bleach ; PHP : symfony/html-sanitizer ; Go : bluemonday, safehtml ; Rust : ammonia ; TS : safevalues |
| Lien `href` reçu | n'accepter que `http(s)` et `mailto` | ui-box safeHref |
| SSRF (le serveur appelle une URL reçue) | refuser les IP locales et privées, après résolution DNS | Python : safehttpx ; Node : ssrf-req-filter ; Go : safeurl ; Ruby : ssrf_filter |
| Redirection ouverte | chemin relatif ou domaines listés seulement | TS : safe-redirect ; Ruby : redirect_safely, safe_redirect |
| Chemin de fichier | résoudre, puis vérifier qu'il reste dans le dossier permis (liens symboliques compris) | `Path.resolve()` + `is_relative_to()` *(std)* ; JS : is-path-inside-secure ; Go : safeopen |
| Archive zip ou tar | refuser `..`, chemins absolus et liens ; plafonner la taille | `tarfile` `filter="data"` *(std)* ; Go : safearchive |
| XML externe | jamais le parseur standard (XXE, bombe XML) | Python : defusedxml |
| Désérialisation | jamais `pickle`, `yaml.load` ni `unserialize` sur une donnée externe | JSON, `yaml.safe_load` ; modèles : safetensors ; Java : SerialKiller |
| Regex sur une entrée | pas de motif à retour arrière exponentiel (ReDoS) ; plafonner la longueur | RE2 ; JS : safe-regex |
| CSRF | jeton ou cookie `SameSite` sur toute action qui modifie | protection du framework, activée ; Go : gorilla/csrf, nosurf ; PHP : anti-csrf |
| Cookies, session | `Secure`, `HttpOnly`, `SameSite` ; signés ou chiffrés | JS : iron-session ; Go : securecookie |
| En-têtes HTTP | CSP, HSTS, `X-Content-Type-Options`, `frame-ancestors` | Node : helmet ; Python : secure ; Go : unrolled/secure ; .NET : NetEscapades.AspNetCore.SecurityHeaders |
| Cryptographie | ni algorithme maison ni mode à choisir ; mots de passe : bcrypt ou argon2 | Tink ; PHP : halite |
| Comparaison de secrets | en temps constant | `hmac.compare_digest` *(std)* ; PHP : constant_time_encoding |
| SVG reçu | servi comme image, nettoyé | svg-hush |
| GraphQL | profondeur, coût et introspection limités | graphql-armor |
| Prompt d'IA avec contenu externe | contenu délimité et marqué, ses consignes ignorées, outils au minimum | spotlighting-datamarking |
| Docker, CI | image minimale ; CI : sortie réseau filtrée | distroless, chainguard ; GitHub Actions : harden-runner |

## 3. Toujours
- Secrets : variables d'environnement ou coffre ; jamais dans le code, git, les journaux ni le cerveau ; `.env` dans
  `.gitignore`.
- Erreurs : message neutre pour l'utilisateur, détail dans le journal, sans secret.
- Dépendances : versions figées ; `pip-audit` ou `npm audit` avant de livrer.
- Moindre privilège : serveur local sur 127.0.0.1, clés aux droits minimaux.
- Ce qui n'a pas été vérifié (test, outil, doc) : le dire, ne pas l'affirmer.
