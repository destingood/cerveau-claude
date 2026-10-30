"""Banc d'essai intégré : `brain bench` mesure la qualité et le coût du cerveau sur SES propres souvenirs.

- Rappel : pour chaque souvenir, une requête faite de ses mots les plus distinctifs, puis la même avec une faute de
  frappe et une variante phonétique (déterministes, donc reproductibles). On mesure s'il sort dans les 3 premiers
  (hit@3) et si le hook de message l'injecterait (« rappel auto »).
- Faux rappels : 16 messages sans rapport (météo, recette, calcul…) ne doivent rien injecter.
- Vitesse : temps réels des hooks, lancés comme Claude Code les lance.
- Tokens : ce que coûte chaque démarrage de session (bloc CLAUDE.md + description de la skill + injection)."""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import sys
import time

from . import search
from .common import BRAIN_PY, CLAUDE_HOME, STOPWORDS, est_tokens, fold, load_config, tokenize
from .store import Brain

OFF_TOPIC = ["quelle heure est-il à Tokyo maintenant ?", "donne moi une recette de crêpes", "traduis ce texte en anglais stp",
             "combien font 12 fois 8", "écris un poème sur la mer", "quel temps fera-t-il demain à paris",
             "explique moi la photosynthèse", "c'est quoi la capitale de l'australie", "fais une blague",
             "ok merci c'est parfait", "vsy continue", "corrige l'orthographe de ce paragraphe",
             "liste les planètes du système solaire", "qui a gagné la coupe du monde 1998", "convertis 30 euros en dollars",
             "raconte moi une histoire courte"]
_PHON_SWAPS = (("qu", "k"), ("ph", "f"), ("eau", "o"), ("ai", "e"), ("ss", "s"), ("ll", "l"), ("tt", "t"), ("é", "e"),
               ("è", "e"), ("ç", "s"))


def _typo(word):
    """Faute de frappe déterministe : une lettre du milieu disparaît."""
    return word if len(word) < 5 else word[: len(word) // 2] + word[len(word) // 2 + 1:]


def _phonetic(word):
    w = fold(word)
    for a, b in _PHON_SWAPS:
        if a in w:
            return w.replace(a, b, 1)
    return w[:-1] if len(w) > 5 and w.endswith("e") else w


def queries(brain):
    """(id, requête propre, requête avec faute, requête phonétique) pour chaque souvenir."""
    nodes = [n for n in brain.active() if n["type"] != "project"]
    df = {}
    for n in nodes:
        for t in set(tokenize(n["title"])):
            df[t] = df.get(t, 0) + 1
    out = []
    for n in nodes:
        words = []
        for w in re.findall(r"[^\W\d_][^\W_]{2,}", n["title"]):
            t = tokenize(w)
            if t and fold(w) not in STOPWORDS and t[0] not in [x[1] for x in words]:
                words.append((df.get(t[0], 1), t[0], w))
        if len(words) < 2:
            continue
        words.sort(key=lambda x: (x[0], -len(x[2])))
        pick = [w for _, _, w in words[:3]]
        longest = max(range(len(pick)), key=lambda i: len(pick[i]))
        typo = list(pick)
        typo[longest] = _typo(pick[longest])
        phon = list(pick)
        phon[longest] = _phonetic(pick[longest])
        out.append((n["id"], " ".join(pick), " ".join(typo), " ".join(phon)))
    return out


def body_queries(brain):
    """(id, requête) faite des 3 mots les plus rares du CONTENU absents du titre : on parle rarement d'un souvenir
    avec les mots exacts de son titre."""
    nodes = [n for n in brain.active() if n["type"] != "project" and len(n.get("body") or "") >= 60]
    df = {}
    for n in nodes:
        for t in set(tokenize(n.get("body", ""))):
            df[t] = df.get(t, 0) + 1
    out = []
    for n in nodes:
        title = set(tokenize(f"{n['title']} {' '.join(n.get('tags') or [])}"))
        words = {}
        for w in re.findall(r"[^\W\d_][^\W_]{3,}", n.get("body", "")):
            t = tokenize(w)
            if t and t[0] not in title and fold(w) not in STOPWORDS and t[0] not in words:
                words[t[0]] = (df.get(t[0], 1), -len(w), w)
        pick = [v[2] for v in sorted(words.values())[:3]]
        if len(pick) == 3:
            out.append((n["id"], " ".join(pick)))
    return out


def recall_quality(brain):
    from .hooks import recall_query
    rc = load_config()["recall"]
    res = {}
    qs = queries(brain)
    bq = [(i, q, q, q) for i, q in body_queries(brain)]
    for label, col, items in (("propre", 1, qs), ("faute", 2, qs), ("phonétique", 3, qs), ("contenu", 1, bq)):
        hit3 = auto = 0
        for q in items:
            r = search.search_memories(brain, recall_query(q[col]), limit=10, expand=False)
            ids = [x["node"]["id"] for x in r]
            hit3 += q[0] in ids[:3]
            qq = recall_query(q[col])
            auto += any(x["node"]["id"] == q[0] and search.accept_recall(x, rc["min_cov"], rc["min_score"], query=qq)
                        for x in r[:5])
        res[label] = (hit3, auto, len(items))
    fp = 0
    for q in OFF_TOPIC:
        qq = recall_query(q)
        r = search.search_memories(brain, qq, limit=10, expand=False)
        fp += any(search.accept_recall(x, rc["min_cov"], rc["min_score"], query=qq) for x in r)
    res["hors sujet"] = (fp, len(OFF_TOPIC))
    return res


def _hook_cmd():
    try:
        hooks = json.loads((CLAUDE_HOME / "settings.json").read_text(encoding="utf-8")).get("hooks", {})
        cmd = hooks["UserPromptSubmit"][0]["hooks"][0]["command"]
        return cmd.rsplit(" hook ", 1)[0]
    except Exception:
        return f'"{sys.executable}" -I -S "{BRAIN_PY}"'


def latency(brain, reps=5):
    base = _hook_cmd()
    proj = next((p for p in brain.projects() if os.path.isdir((p.get("meta") or {}).get("path", ""))), None)
    cwd = (proj.get("meta") or {}).get("path") if proj else os.getcwd()
    env = dict(os.environ)
    out = {}
    for label, event, payload in (("démarrage", "session-start", {"cwd": cwd}),
                                  ("message", "prompt", {"cwd": cwd, "prompt": "les ecriture shopfy marche pas en mode auto"}),
                                  ("fin de tâche", "stop", {"cwd": cwd, "transcript_path": "absent.jsonl"})):
        ts = []
        for _ in range(reps):
            data = json.dumps(dict(payload, session_id=f"bench-{time.time_ns()}")).encode()
            t = time.perf_counter()
            subprocess.run(f"{base} hook {event}", input=data, capture_output=True, shell=True, env=env, cwd=cwd)
            ts.append((time.perf_counter() - t) * 1000)
        out[label] = statistics.median(ts)
    for f in (CLAUDE_HOME.parent / ".claude" / "brain" / "state" / "sessions").glob("bench-*.json") if False else []:
        pass
    from .common import SESSIONS_DIR
    for f in SESSIONS_DIR.glob("bench-*.json"):
        try:
            f.unlink()
        except OSError:
            pass
    return out, proj["id"] if proj else None


def token_costs(brain):
    from . import index as idx
    from .install import CLAUDE_BLOCK, SKILL
    tok = est_tokens
    desc = re.search(r"(?m)^description: (.*)$", SKILL)
    fixed = tok(CLAUDE_BLOCK) + tok(desc.group(1) if desc else "")
    rows = [("hors projet", tok(idx.session_context(brain, os.path.expanduser("~"))[0]))]
    for p in brain.projects():
        path = (p.get("meta") or {}).get("path")
        if path:
            rows.append((p["id"], tok(idx.session_context(brain, path)[0])))
    return fixed, rows


# ------------------------------------------------------------------------------------ scénarios (monde fictif)
SCN_UPDATES = [  # (type, titre, avant, après) : le second doit REMPLACER le premier
    ("fact", "Délai de livraison du fournisseur Kyoto", "Le fournisseur Kyoto livre en 12 jours ouvrés.",
     "Le fournisseur Kyoto livre désormais en 7 jours ouvrés."),
    ("fact", "Code promo de la newsletter", "Le code NEWS15 donne 15 % de remise sur la première commande.",
     "Le code NEWS20 donne 20 % de remise sur la première commande."),
    ("fact", "Paiement en 3 fois", "Le paiement en 3 fois est activé sur la boutique.",
     "Le paiement en 3 fois n'est plus proposé sur la boutique."),
    ("fact", "Hébergeur des images produits", "Les images produits sont hébergées sur Cloudinary.",
     "Les images produits sont maintenant hébergées sur le CDN de Shopify."),
    ("fact", "Horaires du support client", "Le support répond de 9 h à 18 h du lundi au vendredi.",
     "Le support répond de 8 h à 20 h du lundi au samedi."),
    ("decision", "Transporteur par défaut", "Les colis partent en Colissimo suivi.",
     "Les colis partent en Mondial Relay depuis le changement de tarif."),
    ("fact", "Thème de la boutique", "La boutique tourne sur le thème Dawn.", "La boutique est passée au thème Impulse."),
    ("fact", "Abonnement à la plateforme", "La boutique est sur le plan Basic à 36 € par mois.",
     "La boutique est passée au plan Grow à 105 € par mois."),
    ("decision", "Jour d'envoi de la newsletter", "La newsletter part chaque lundi matin.",
     "La newsletter part désormais chaque jeudi matin."),
    ("fact", "Automatisations Make de la boutique", "Les automatisations Make sont arrêtées.",
     "Les automatisations Make sont relancées."),
    ("fact", "Adresse de retour des colis", "Les retours vont à l'entrepôt de Lyon.",
     "Les retours vont désormais à l'entrepôt de Lille."),
    ("decision", "Seuil de livraison gratuite", "Livraison offerte dès 49 € d'achat.", "Livraison offerte dès 39 € d'achat."),
]
SCN_KEEP = [  # (type, titre avant, avant, titre après, après) : le second ne doit PAS remplacer le premier
    ("fact", "Délai de livraison du fournisseur Kyoto", "Le fournisseur Kyoto livre en 12 jours ouvrés.",
     "Délai de livraison du fournisseur Osaka", "Le fournisseur Osaka livre en 5 jours ouvrés."),
    ("fact", "Audit SEO du 15/10", "Audit SEO : 23 pages sans meta description.",
     "Audit SEO du 20/10", "Audit SEO : 14 pages sans meta description."),
    ("fact", "Code promo de la newsletter", "Le code NEWS15 donne 15 % de remise.",
     "Code promo Black Friday", "Le code BF30 donne 30 % de remise."),
    ("fact", "Horaires du support client", "Le support répond de 9 h à 18 h.",
     "Horaires de l'entrepôt", "L'entrepôt est ouvert de 7 h à 15 h."),
    ("fact", "Paiement en 3 fois", "Le paiement en 3 fois est activé sur la boutique.",
     "Paiement en 3 fois", "Le paiement en 3 fois est géré par Alma."),
    ("fact", "Thème de la boutique", "La boutique tourne sur le thème Dawn.",
     "Thème de la boutique", "Le thème Dawn a été personnalisé avec une police japonaise."),
    ("decision", "Jour d'envoi de la newsletter", "La newsletter part chaque lundi matin.",
     "Fréquence des publications Instagram", "Un post Instagram part chaque lundi matin."),
    ("decision", "Seuil de livraison gratuite", "Livraison offerte dès 49 € d'achat.",
     "Seuil de livraison gratuite en Belgique", "Livraison offerte dès 59 € en Belgique."),
]
SCN_TEMPORAL = [  # (type, titre, contenu, question) — le souvenir est daté au milieu de la plage visée
    ("fact", "Appel avec le fournisseur de thé", "Hausse de 8 % annoncée au 1er janvier.",
     "qu'est-ce que le fournisseur a dit hier ?"),
    ("fact", "Shooting des coffrets", "Photos des coffrets refaites sur fond blanc pour les fiches produit.",
     "on a fait quoi la semaine dernière pour les photos ?"),
    ("decision", "Campagne Meta Ads lancée", "Campagne lancée sur le coffret découverte, budget 10 € par jour.",
     "c'était quoi la campagne lancée il y a 6 semaines ?"),
    ("todo", "Salon du thé à Paris", "Stand réservé pour le salon du thé le 12/11, prévoir 40 coffrets.",
     "qu'est-ce qui est prévu le 12/11 ?"),
    ("learning", "Bug du panier sur mobile", "Le bouton d'ajout au panier disparaissait sur iPhone : corrigé en "
     "retirant le bandeau collant.", "c'était quoi le problème réglé avant-hier ?"),
    ("fact", "Bilan des ventes", "Ventes du mois : 12 commandes, panier moyen 41 €.", "le bilan du mois dernier ?"),
]
TEMPORAL_DECOYS = [  # même sujet, autre époque (150 jours plus tôt) : seul le canal des dates départage
    ("fact", "Appel avec le fournisseur de thé", "Le fournisseur confirme les délais habituels, prix inchangés."),
    ("fact", "Shooting des coffrets", "Premières photos des coffrets prises au smartphone, à refaire."),
    ("decision", "Campagne Meta Ads lancée", "Campagne test lancée sur le mousseur, budget 5 € par jour."),
    ("todo", "Salon du thé à Paris", "Se renseigner sur les salons du thé en région parisienne."),
    ("learning", "Bug du panier sur mobile", "Le panier se vidait sur Android : cache du thème vidé."),
    ("fact", "Bilan des ventes", "Ventes du trimestre : 30 commandes, panier moyen 38 €."),
]
SCN_HOPS = [  # (A, B, question) : la réponse demande les deux souvenirs, reliés par un nom propre
    (("Fabrication du coffret Hōjicha", "Le coffret Hōjicha est fabriqué par l'atelier Sato à Uji."),
     ("Fermeture estivale de l'atelier Sato", "L'atelier Sato ferme tout le mois d'août pour congés."),
     "le coffret Hōjicha sera-t-il disponible cet été ?"),
    (("Application d'avis clients", "Les avis clients de la boutique sont gérés avec l'app Judge.me."),
     ("Tarif de Judge.me", "Judge.me facture 15 $ par mois pour le plan Awesome."),
     "combien coûte l'outil des avis clients ?"),
    (("Logiciel de comptabilité", "La compta de la boutique est tenue dans le logiciel Tiime."),
     ("Export FEC depuis Tiime", "Tiime exporte le fichier FEC à chaque fin de mois."),
     "comment récupérer le FEC de la compta ?"),
    (("Piles du mousseur électrique", "Le mousseur électrique est livré avec deux piles AA."),
     ("Fournisseur des piles AA", "Les piles AA sont commandées chez Energizer Pro par lots de 100."),
     "chez qui on commande les piles du mousseur ?"),
]
SCN_BROAD_PROJECT = ("Boutique Sakura Bento", "Boutique en ligne de boîtes bento japonaises en bois, lancée en septembre "
                                              "sur Shopify.")
SCN_BROAD = {  # deux sujets éparpillés en souvenirs : (type, titre, contenu, importance) — importance ≥ 4 = fait clé
    "sakura": [
        ("fact", "Ventes de la boutique Sakura", "Sakura Bento a reçu 34 commandes depuis le lancement, panier moyen 41 €.", 5),
        ("fact", "Stock des bentos Sakura", "Il reste 120 boîtes bento en stock, réassort prévu fin novembre.", 4),
        ("decision", "Prix du bento Hanami", "Le bento Hanami passe à 29 € pour relancer les ventes.", 4),
        ("fact", "Fournisseur des bentos Sakura", "Les boîtes bento sont fabriquées par l'atelier Kobe Craft, délai 15 jours.", 3),
        ("fact", "Campagne Instagram Sakura", "La campagne Instagram des bentos tourne à 8 € par jour pour 2 ventes par semaine.", 3),
        ("learning", "Photos des bentos Sakura", "Les photos de bentos sur fond bois convertissent mieux que sur fond blanc.", 3),
        ("decision", "Livraison des bentos Sakura", "Les bentos partent en point relais, livraison offerte dès 50 €.", 3),
        ("fact", "Avis clients des bentos", "Les bentos ont 4,7 sur 5 sur 23 avis ; les clients aiment le couvercle en bambou.", 3),
        ("learning", "Bentos arrivés fendus", "Deux bentos sont arrivés fendus : emballage renforcé au papier bulle.", 2),
        ("todo", "Traduire les fiches bento en anglais", "Traduire les fiches produit des bentos pour l'ouverture à l'export.", 3),
    ],
    "japon": [  # sujet global, sans projet
        ("fact", "Vols du voyage au Japon", "Vol Paris-Osaka réservé pour le voyage au Japon : aller le 3 avril, retour le 20.", 5),
        ("decision", "Budget du voyage au Japon", "Budget du voyage au Japon fixé à 3 500 € tout compris.", 4),
        ("fact", "Ryokan du voyage à Kyoto", "Ryokan réservé à Kyoto pour le voyage au Japon, du 5 au 9 avril.", 4),
        ("fact", "Visite des producteurs à Uji", "Pendant le voyage au Japon, visite de deux producteurs de thé à Uji le 7 avril.", 3),
        ("learning", "Wi-Fi de poche au Japon", "Pour le voyage au Japon, un routeur Wi-Fi de poche revient moins cher qu'une "
                                              "carte SIM.", 2),
        ("todo", "Commander le JR Pass", "Commander le JR Pass du voyage au Japon un mois avant le départ.", 3),
    ],
}
SCN_BROAD_Q = [("où en est la boutique Sakura ?", "sakura"), ("fais-moi le point sur les bentos", "sakura"),
               ("les bentos", "sakura"), ("on en est où pour le voyage au Japon ?", "japon"),
               ("quoi de neuf sur le voyage ?", "japon")]
SCN_BROAD_PRECISE = [("combien coûte le bento Hanami ?", "Prix du bento Hanami"), ("le ryokan à Kyoto", "Ryokan du voyage à Kyoto"),
                     ("photos des bentos sur fond bois", "Photos des bentos Sakura"), ("JR Pass", "Commander le JR Pass")]
NEAR_MISS = ["combien coûte un abonnement Netflix ?", "quel est le délai de livraison d'Amazon Prime ?",
             "comment configurer le wifi de ma box ?", "quel est le prix du bitcoin aujourd'hui ?",
             "à quelle heure ferme la poste ?", "c'est quoi un bon thème WordPress ?",
             "comment faire un export Excel en CSV ?", "quel transporteur pour une lettre recommandée ?"]


def _world(brain):
    """Copie en mémoire du cerveau : les scénarios s'y jouent, rien n'est jamais enregistré."""
    import copy
    return Brain(copy.deepcopy(brain.data))


def _ids(world, query, k, fuse, today=None):
    """Souvenirs classés (la fiche d'une question large n'est pas un souvenir : comptée à part)."""
    r = search.search_memories(world, query, limit=k, expand=False, use_cache=False, fuse=fuse, today=today)
    return [x["node"]["id"] for x in r if x.get("via") != "fiche"][:k]


def _fiche_first(world, query):
    r = search.search_memories(world, query, limit=8, expand=False, use_cache=False, fuse=True)
    return (r[0], r[1:]) if r and r[0].get("via") == "fiche" else (None, r)


def broad(brain):
    """Questions larges (monde fictif, avec le vrai cerveau autour) : la fiche du bon sujet arrive-t-elle en tête ?
    → dict : fiche en tête / questions, souvenirs du sujet résumés par la fiche et sa pureté, pureté des dix premiers
      souvenirs sans fiche (« dix faits épars »), tokens de l'une et des autres, fiches à tort sur des questions précises."""
    from . import fiches
    w = _world(brain)
    proj = w.add("project", *SCN_BROAD_PROJECT, source="bench", meta={"path": "Z:\\banc-essai\\sakura"}, nid="banc-sakura")
    topic = {"sakura": {proj["id"]}}
    for name, items in SCN_BROAD.items():
        topic.setdefault(name, set())
        for t, title, body, imp in items:
            n = w.add(t, title, body, importance=imp, project=proj["id"] if name == "sakura" else None, source="bench")
            topic[name].add(n["id"])
    out = {"first": 0, "n": len(SCN_BROAD_Q), "covered": 0, "pure": 0, "cited": 0, "list_on": 0, "list_n": 0,
           "tok_fiche": 0, "tok_list": 0}
    for q, name in SCN_BROAD_Q:
        f, _ = _fiche_first(w, q)
        if f:
            cited = fiches.cited(f["fiche"])
            if len(cited & topic[name]) * 2 > len(cited):
                out["first"] += 1
                out["covered"] += len(cited & topic[name])
                out["pure"] += len(cited & topic[name])
                out["cited"] += len(cited)
                out["tok_fiche"] += math.ceil(len(f["node"]["body"]) / 3.6)
        r = search.search_memories(w, q, limit=10, expand=False, use_cache=False, fuse=False)  # avant : dix souvenirs
        out["list_on"] += sum(1 for x in r if x["node"]["id"] in topic[name])
        out["list_n"] += len(r)
        out["tok_list"] += sum(math.ceil(len(f"{i}. [{x['node']['type']}] {x['node']['title']} — "
                                             f"{x['node'].get('body', '')[:260]} `{x['node']['id']}`") / 3.6)
                               for i, x in enumerate(r, 1))
    out["wrong"] = sum(1 for q, _ in SCN_BROAD_PRECISE if _fiche_first(w, q)[0])
    out["n_precise"] = len(SCN_BROAD_PRECISE)
    return out


def scenarios(brain, today=None):
    import datetime as _dt
    from . import dates, reconcile
    today = today or _dt.date.today()
    res = {}
    w = _world(brain)
    upd = 0
    for t, title, v1, v2 in SCN_UPDATES:
        old = w.add(t, title, v1, source="bench")
        dec = reconcile.decide(w, t, title, v2, None)
        if dec["action"] == "update" and dec["target"]["id"] == old["id"]:
            new = w.add(t, title, v2, source="bench")
            w.supersede(new["id"], old["id"])
            top = _ids(w, title, 3, True)
            upd += bool(top) and top[0] == new["id"] and old["id"] not in top
    false_upd = 0
    for t, t1, b1, t2, b2 in SCN_KEEP:
        w2 = _world(brain)
        old = w2.add(t, t1, b1, source="bench")
        false_upd += reconcile.decide(w2, t, t2, b2, None)["action"] == "update"
    res["mise à jour"] = (upd, len(SCN_UPDATES), false_upd, len(SCN_KEEP))
    w = _world(brain)
    placed = []
    for t, title, body in TEMPORAL_DECOYS:
        decoy = w.add(t, title, body, source="bench")
        decoy["created"] = decoy["updated"] = f"{(today - _dt.timedelta(days=150)).isoformat()}T10:00:00"
    for t, title, body, q in SCN_TEMPORAL:
        node = w.add(t, title, body, source="bench")
        rng = dates.query_range(q, today)
        when = (rng[0] + (rng[1] - rng[0]) / 2) if rng and t != "todo" else today
        node["created"] = node["updated"] = f"{when.isoformat()}T10:00:00"
        placed.append((node["id"], q))
    res["temporel"] = (sum(nid in _ids(w, q, 1, True, today) for nid, q in placed),
                       sum(nid in _ids(w, q, 1, False, today) for nid, q in placed), len(placed))
    w = _world(brain)
    pairs = []
    for (ta, ba), (tb, bb), q in SCN_HOPS:
        a, b = w.add("fact", ta, ba, source="bench"), w.add("fact", tb, bb, source="bench")
        pairs.append((a["id"], b["id"], q))
    res["deux souvenirs"] = (sum(a in _ids(w, q, 5, True) and b in _ids(w, q, 5, True) for a, b, q in pairs),
                             sum(a in _ids(w, q, 5, False) and b in _ids(w, q, 5, False) for a, b, q in pairs),
                             len(pairs))
    from .hooks import recall_query
    rc = load_config()["recall"]
    fp = 0
    for q in NEAR_MISS:
        qq = recall_query(q)
        r = search.search_memories(w, qq, limit=10, expand=False, use_cache=False)
        fp += any(search.accept_recall(x, rc["min_cov"], rc["min_score"], query=qq) for x in r)
    res["abstention"] = (fp, len(NEAR_MISS))
    qs = queries(brain)
    res["q hit@1"] = (sum(bool(i) and i[0] == q[0] for q in qs for i in [_ids(brain, q[1], 1, True)]),
                      sum(bool(i) and i[0] == q[0] for q in qs for i in [_ids(brain, q[1], 1, False)]), len(qs))
    res["question large"] = broad(brain)
    res["fiche à tort"] = (sum(1 for q in qs if _fiche_first(brain, q[1])[0])
                           + sum(1 for _, _, _, q in SCN_TEMPORAL if _fiche_first(brain, q)[0]), len(qs) + len(SCN_TEMPORAL))
    return res


def run(quick=False):
    brain = Brain.load()
    lines = ["🧠 Banc d'essai du cerveau", ""]
    q = recall_quality(brain)
    n = q["propre"][2]
    lines.append(f"Rappel sur tes {n} souvenirs (requêtes générées depuis leurs titres) :")
    for label in ("propre", "faute", "phonétique", "contenu"):
        h, a, tot = q[label]
        lines.append(f"  {label:11} hit@3 {100 * h / max(1, tot):5.1f} % · rappel auto {100 * a / max(1, tot):5.1f} %"
                     + (" (mots du contenu, pas du titre)" if label == "contenu" else ""))
    fp, tot = q["hors sujet"]
    lines.append(f"  hors sujet  faux rappels {fp}/{tot}")
    s = scenarios(brain)
    pct = lambda a, b: f"{100 * a / max(1, b):.0f} %"  # noqa: E731
    u, nu, fu, nk = s["mise à jour"]
    t1, t0, nt = s["temporel"]
    h1, h0, nh = s["deux souvenirs"]
    a1, na = s["abstention"]
    q1, q0, nq = s["q hit@1"]
    lines += ["", "Scénarios (monde fictif ajouté en mémoire, rien n'est écrit) :",
              f"  mise à jour     {u}/{nu} faits remplacés (l'ancien archivé et daté) · {fu}/{nk} faux remplacements",
              f"  temporel        hit@1 {pct(t1, nt)} (texte seul : {pct(t0, nt)}) — « hier », « le 12/11 », « il y a 6 semaines », avec leurres d'une autre époque",
              f"  deux souvenirs  {h1}/{nh} réponses réunies dans les 5 premiers (texte seul : {h0}/{nh})",
              f"  abstention      faux rappels {a1}/{na} sur des questions proches mais absentes de la mémoire",
              f"  `q` hit@1       {pct(q1, nq)} (texte seul : {pct(q0, nq)})"]
    b = s["question large"]
    fw, fn = s["fiche à tort"]
    per = max(1, b["first"])
    lines += [f"  question large  fiche du bon sujet en tête {b['first']}/{b['n']} (avant : 0/{b['n']}) — « où en est… », "
              f"« le point sur… » : {b['covered'] / per:.1f} souvenirs du sujet résumés ({pct(b['pure'], b['cited'])} "
              f"du sujet) en ≈ {b['tok_fiche'] // per} tokens",
              f"                  avant : dix souvenirs, dont {pct(b['list_on'], b['list_n'])} du sujet, ≈ "
              f"{b['tok_list'] // b['n']} tokens · fiches à tort : {b['wrong']}/{b['n_precise']} questions précises, "
              f"{fw}/{fn} de tes requêtes `q` et temporelles"]
    fixed, rows = token_costs(brain)
    lines += ["", f"Tokens à chaque démarrage : {fixed} fixes (bloc CLAUDE.md + description de la skill) + injection :"]
    lines += [f"  {name:14} {t:5d} tokens" for name, t in rows]
    if not quick:
        lat, pid = latency(brain)
        lines += ["", f"Vitesse des hooks (médiane, lancés comme Claude Code, projet {pid or '-'}) :"]
        lines += [f"  {k:13} {v:6.0f} ms" for k, v in lat.items()]
    return "\n".join(lines)
