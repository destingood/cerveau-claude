"""Tolérance de la recherche : synonymes métier FR/EN, clé phonétique française et fautes de frappe.

On écrit vite, souvent en phonétique (« elle les atin pas », « boutik », « shopfy ») : un mot inconnu de l'index est
rapproché des mots connus qui se prononcent pareil ou qui n'en diffèrent que d'une lettre. Les synonymes, eux,
élargissent toujours la requête (« commande » trouve aussi « order », « rdv » trouve « agenda »)."""
from __future__ import annotations

import re

from .common import fold, stem, tokenize

# Groupes de synonymes (formes simples ; elles passent par fold + stem comme l'index).
_GROUPS = """
boutique shop store magasin ecommerce e-commerce
commande order commandes
vente ventes sale sales vendre
achat achats purchase acheter buy
produit produits product products
client clients customer customers acheteur buyer
panier cart checkout
paiement payment payer
livraison livraisons shipping expedition delivery colis transporteur
prix price tarif tarifs cout cost
facture factures invoice invoices facturation
remboursement refund retour retours return
stock inventaire inventory
fournisseur supplier fournisseurs suppliers
promo promotion reduction discount coupon remise
avis review reviews temoignage
annonce annonces listing leboncoin
image images photo photos visuel visuels picture
mail email e-mail courriel gmail mails emails
agenda calendrier calendar rdv rendez-vous reunion meeting
pc ordinateur computer machine
bios uefi
jeton token tokens
tache taches task tasks todo
erreur erreurs error errors bug bugs plantage crash probleme problemes
automatisation automatisations automation automatiser script scripts
referencement seo
publicite pub ads campagne campagnes
abonnement subscription
cerveau brain
session sessions conversation
fichier fichiers file files document documents
dossier dossiers folder folders repertoire directory
site website page pages
connecteur connecteurs connector connectors mcp
plugin plugins extension extensions
compte account comptes
mot-de-passe password
traduction translate traduire
video videos
article articles blog guide guides
theme themes template
"""

SYN: dict[str, set] = {}
for _line in _GROUPS.strip().splitlines():
    _keys = {stem(fold(w)) for w in _line.split() if len(fold(w)) >= 2}
    for _k in _keys:
        SYN.setdefault(_k, set()).update(_keys - {_k})

# Faux amis : noms propres qui contiennent un mot métier sans en avoir le sens. Le magasin d'applications de Windows
# (« Microsoft Store », « iTunes du Store ») n'est pas la boutique, « C:\Program Files » n'est pas un fichier. La recherche
# exacte les trouve toujours (« Microsoft Store ») ; seuls les synonymes (« boutique » → « store ») les ignorent.
_FAUX_AMIS = re.compile(r"\b(?:Microsoft|Windows|App|Play|Web|Games|Steam|Xbox|Galaxy|[Dd]u|[Ll]e|[Aa]u)\s+Store\b|"
                        r"\b(?:Program|Common) Files\b")


def faux_amis(text) -> list:
    """Mots métier pris dans un faux ami (« pas celui du Store » → ["store"]) : à ne pas compter comme synonymes."""
    return [t for m in _FAUX_AMIS.finditer(text or "") for t in tokenize(m.group(0)) if t in SYN]

# Clé phonétique (français d'abord, correcte pour l'anglais courant). Ordre des règles important.
_PHON = [
    (re.compile(r"[^a-z]"), ""),
    (re.compile(r"ph"), "f"),
    (re.compile(r"gn"), "n"),
    (re.compile(r"sch|sh|ch"), "x"),
    (re.compile(r"(ain|ein|aim|in|im|un|um|yn|ym)(?![aeiouy])"), "1"),
    (re.compile(r"(an|am|en|em)(?![aeiouy])"), "2"),
    (re.compile(r"(on|om)(?![aeiouy])"), "3"),
    (re.compile(r"qu|q|ck|k"), "k"),
    (re.compile(r"c(?=[eiy])"), "s"),
    (re.compile(r"c"), "k"),
    (re.compile(r"eau|au"), "o"),
    (re.compile(r"ou|oo"), "u"),
    (re.compile(r"ai|ei|ay|ey"), "e"),
    (re.compile(r"(?<=[aeiouy])s(?=[aeiouy])"), "z"),
    (re.compile(r"y"), "i"),
    (re.compile(r"w"), "v"),
    (re.compile(r"h"), ""),
    (re.compile(r"(.)\1+"), r"\1"),
    (re.compile(r"(?<=.)(er|ez|et)$"), "e"),
    (re.compile(r"(?<=..)[estdxp]$"), ""),
]


def phon(token: str) -> str:
    """« atteint » et « atin » → « at1 » ; « boutique » et « boutik » → « butik »."""
    s = fold(token)
    for rx, rep in _PHON:
        s = rx.sub(rep, s)
    return s


def deletes(word: str) -> set:
    return {word[:i] + word[i + 1:] for i in range(len(word))}


def within_one(a: str, b: str) -> bool:
    """Distance d'édition ≤ 1 (insertion, suppression, substitution ou inversion de deux lettres voisines)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


_SUFFIXES = ("issements", "issement", "ationnels", "ationnel", "ations", "ation", "itions", "ition", "ements", "ement",
             "ments", "ment", "ances", "ance", "ences", "ence", "iques", "ique", "ables", "able", "euses", "euse",
             "eurs", "eur", "ees", "ee", "es", "er", "ez", "e", "s")


def root(token: str) -> str:
    """Famille de mots : « réinstallation », « réinstallé », « réinstaller » → « reinstal »."""
    s = fold(token)
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) - len(suf) >= 4:
            s = s[: -len(suf)]
            break
    if len(s) >= 5 and s[-1] == s[-2]:
        s = s[:-1]
    return s


# Terminaisons d'une autre forme du même mot (« tester » → « test », « créer » → « crée », « réelle » → « réel »,
# « loaded » → « load ») : seul un début de mot de 4 lettres suivi de l'une d'elles compte comme troncature
# (« boutique » ne se réduit pas à « bout »).
INFLEXIONS = frozenset(("e", "ee", "r", "er", "ez", "nt", "ent", "x", "le", "d", "ed", "ing"))
