"""Filtre du rappel automatique (découpé de search.py, étape 12 du plan, sans rien changer) : un souvenir trouvé
est-il assez proche du message pour être montré ? Couverture des mots, mots vides, longs messages. search.py
réexporte tout : `search.accept_recall` et les autres noms restent valables."""
from __future__ import annotations

import re

from .common import fold, tokenize

LONG_BODY, LONG_COV = 400, 0.62
NEAR = 12  # mots : au-delà, deux termes du message ne parlent plus de la même chose dans le souvenir


def _near(node, vs, window=NEAR, strict=False) -> bool:
    """Deux termes différents du message à moins de `window` mots l'un de l'autre dans le souvenir ? Vrai aussi quand
    on ne retrouve pas deux termes (forme approchée hors texte) : dans le doute, la règle d'avant décide (`strict` : non).
    « qui a gagné la coupe du monde » ↛ « tout le monde » … 60 mots … « connecteurs coupés »."""
    last, found = {}, set()
    for i, t in enumerate(tokenize(f"{node['title']} {node.get('body') or ''}")):
        for q, forms in vs.items():
            if t in forms:
                found.add(q)
                if any(q2 != q and i - j <= window for q2, j in last.items()):
                    return True
                last[q] = i
    return len(found) < 2 and not strict


WORD = re.compile(r"[^\W\d_]+")

# Mots d'un message qui ne disent rien de son sujet, retirés de la requête du rappel (pas de l'index) : avant, ils
# comptaient comme des mots du message que le souvenir ne contenait pas (« mon ordi plante avec un écran bleu, c'était
# quoi la solution déjà ? » : « était », « déjà »). Formes écrites, sans accents ; jamais une date (« hier », « mois »).
FILLER = frozenset("""
deja presque mieux pendant apres avant depuis ensuite puis enfin finalement souvent parfois vraiment absolument habitude
actuellement moment suite cas genre dessus dessous quelque quelques plusieurs
etait etaient etais serait seraient sera seront soit sois avaient aurait auraient aura
peuvent pourrait pourrais pouvais pouvait voudrais voudrait voulais voulait sais sait savais savait savoir faudrait
fallait vais va vas allait aller viens vient venais venait crois croit croyais pense pensais connais connait
souviens souvient souvenais rappeler rappelle rappelles trouve trouves trouvait trouvais marchait marchaient
marchent hesite hesites hesitais cherche cherches cherchais
koi kel kelle pr pk pq bcp tjs dc ds ki jsp
""".split())


def drop_filler(text) -> str:
    """Le message sans ses mots de remplissage (FILLER) : la requête du rappel automatique."""
    return WORD.sub(lambda m: " " if fold(m.group()) in FILLER else m.group(), str(text or ""))


def _head_hit(node, qterms) -> bool:
    head = set(tokenize(f"{node['title']} {' '.join(node.get('tags') or [])} {(node.get('meta') or {}).get('keys') or ''}"))
    return any(q in head or (len(q) >= 5 and any(h.startswith(q[:5]) for h in head)) for q in qterms)


def accept_recall(r, min_cov, min_score=0.0, query=None) -> bool:
    """Filtre anti-bruit du rappel automatique : assez de termes du message ET une bonne part de leur poids
    (un seul mot en commun avec un long message ne suffit jamais). Un long souvenir attrape des mots au hasard
    (« coupe du monde » → « coupé ») : sans couverture forte, son titre ou ses étiquettes doivent parler du sujet."""
    return not recall_refusal(r, min_cov, min_score, query)


def recall_refusal(r, min_cov, min_score=0.0, query=None) -> str:
    """Pourquoi le filtre du rappel écarte ce résultat ('' : accepté) : la règle d'`accept_recall` elle-même, donc
    le diagnostic (`brain recall --pourquoi`) ne peut pas s'en écarter. Un message long qui échoue à la règle
    ordinaire passe encore par celle des messages longs (`_long_refusal`)."""
    why = _short_refusal(r, min_cov, min_score, query)
    if not why or query is None or r.get("node") is None or r["nq"] < LONG_NQ:
        return why
    other = _long_refusal(r, query)
    return f"{why} ; message long : {other}" if other else ""


# Règle des messages longs (LONG_NQ mots porteurs de sens ou plus). Un tel message décrit la situation avant de poser
# sa question : la couverture d'un message court lui est hors de portée (avant, aucun des 6 messages de trois phrases du
# banc d'essai ne rappelait rien, même quand le bon souvenir était classé premier). Le souvenir passe quand la preuve est
# forte et ramassée : 2 mots du message trouvés tels quels (pas une forme approchée), proches l'un de l'autre, dont un
# dans le titre ou les mots-clés, un score d'au moins LONG_SCORE, et un message qui parle surtout du monde du cerveau :
# au plus 1 mot sur 3 qu'aucun souvenir ne contient tel quel (« Ma cousine passe un entretien d'embauche pour un poste
# d'infirmière » n'est pas l'entretien de l'utilisateur, « une série sur Netflix » n'est pas sa série de vidéos).
# Jamais une règle ni le profil : l'index du démarrage les montre déjà, et leurs mots de consigne (« proposer un plan »,
# « expliquer simplement ») se retrouvent dans bien des demandes.
LONG_NQ, LONG_SCORE = 5, 10.0
AT_START = ("feedback", "user")


def _long_refusal(r, query) -> str:
    """Pourquoi la règle des messages longs écarte ce résultat ('' : accepté)."""
    node, vs = r["node"], r.get("vars") or {}
    if node["type"] in AT_START:
        return "règle ou profil, déjà dans l'index du démarrage"
    if r.get("strong", r["matched"]) < 2:
        return "moins de 2 mots retrouvés tels quels"
    if r["score"] < LONG_SCORE:
        return f"score {r['score']} < {LONG_SCORE}"
    if 3 * r.get("unknown", 0) > r["nq"]:
        return f"{r['unknown']} mots sur {r['nq']} inconnus du cerveau : le message parle d'autre chose"
    if not _head_hit(node, set(tokenize(query))):
        return "ni le titre ni les mots-clés ne parlent du sujet"
    if not _near(node, vs, strict=True):
        return f"mots retrouvés à plus de {NEAR} mots l'un de l'autre"
    return ""


def _short_refusal(r, min_cov, min_score=0.0, query=None) -> str:
    """La règle ordinaire : assez de mots du message, une bonne part de leur poids, un score suffisant."""
    nq = r["nq"]
    need = 1 if nq == 1 else 2 if nq <= 4 else 3
    if r["matched"] < need:
        return f"trop peu de mots du message retrouvés ({r['matched']}/{nq}, il en faut {need})"
    if nq > 1 and r["matched"] - r.get("loose", 0) < need:  # « postulé » n'est pas « poste » : 3 trigrammes communs
        return (f"trop peu de mots du message retrouvés ({r['matched'] - r.get('loose', 0)}/{nq} sans ceux qui ne "
                f"ressemblent que par des morceaux, il en faut {need})")
    if r.get("cov", 0) < min_cov:
        return f"couverture {r.get('cov', 0):.3f} < min_cov {min_cov} : les mots retrouvés pèsent peu dans le message"
    if r["score"] < min_score:
        return f"score {r['score']} < min_score {min_score}"
    node = r.get("node")
    if query is not None and node is not None and len(node.get("body") or "") >= LONG_BODY and r.get("cov", 0) < LONG_COV:
        return "" if _head_hit(node, set(tokenize(query))) else \
            f"long souvenir, couverture {r.get('cov', 0):.3f} < {LONG_COV} et ni le titre ni les mots-clés ne parlent du sujet"
    # Termes épars : message pas entièrement retrouvé, titre muet, et ses mots semés loin les uns des autres → coïncidence
    # (342 rappels réels rejoués : 9 inutiles coupés, aucun utile perdu ; tous les mots retrouvés → la règle d'avant).
    if query is not None and node is not None and 2 <= r["matched"] < r["nq"] and r.get("vars") \
            and not _head_hit(node, set(tokenize(query))) and not _near(node, r["vars"]):
        return f"mots épars : retrouvés à plus de {NEAR} mots l'un de l'autre, titre muet (coïncidence probable)"
    return ""
