"""Analyse d'un appel de vente ou d'un jeu de rôle, à partir de sa transcription : des repères chiffrés pour le débrief.

Usage :
  python appel.py <transcription.txt> [--moi "Nom"] [--json]

La transcription : une réplique par ligne, « Nom : texte » (un horodatage devant est accepté : « [00:01:12] Nom :
texte », « 00:01 Nom: texte »). Les lignes sans nom continuent la réplique d'avant. --moi : le nom du vendeur dans la
transcription ; sans lui, « Moi », « Vendeur », « Vendeuse » ou « Vous » s'il y en a un, sinon la première personne
qui parle.

Repères calculés (mots comptés, pas le temps) : part de parole du vendeur, questions posées (ouvertes ou fermées),
plus long monologue, reformulations, mots de remplissage, objections du client et la réponse qui a suivi, prochaine
étape proposée en fin d'appel. Ce sont des repères pour en parler, pas une note : aucun seuil « idéal » n'est
affirmé. Aucun accès réseau ; rien n'est gardé."""
import json
import re
import sys
from pathlib import Path

LINE = re.compile(r"^\s*(?:\[?\(?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\)?\]?\s*[-–]?\s*)?"
                  r"([A-ZÀ-ÖØ-Þa-zß-öø-ÿ][\wÀ-ÖØ-öø-ÿ' .-]{0,30}?)\s*:\s+(.*)$")
SELLER = ("moi", "vendeur", "vendeuse", "vous", "commercial", "commerciale", "conseiller", "conseillère")
OPEN = re.compile(r"\b(?:comment|pourquoi|qu'est-ce|qu’est-ce|quel|quelle|quels|quelles|combien|où|quand|de quoi|"
                  r"en quoi|à quoi|racontez|raconte|expliquez|explique|dites-moi|dis-moi|parlez-moi|parle-moi|"
                  r"décrivez|qu'attendez)\b", re.I)  # une question qui ne se répond pas par oui ou non
FILLERS = ("euh", "heu", "hum", "ben", "bah", "du coup", "en fait", "voilà", "genre", "tu vois", "vous voyez",
           "en gros", "j'veux dire")
REFORMULE = re.compile(r"si je comprends bien|si j'ai bien compris|si je résume|si je reformule|vous voulez dire|"
                       r"donc pour vous|en gros, vous|ce que j'entends|autrement dit|c'est bien ça", re.I)
NEXT = re.compile(r"je vous propose|on se cale|on se rappelle|rendez-vous|rdv|je vous envoie|on fixe|je vous le prépare|"
                  r"je vous la prépare|lequel vous préférez|laquelle vous préférez|on signe|je vous rappelle|"
                  r"quand est-ce qu'on|on part sur|je passe la commande|on valide|prochaine étape", re.I)
OBJECTIONS = (("prix", r"trop cher|c'est cher|hors budget|pas le budget|moins cher|ailleurs c'est"),
              ("réflexion", r"je vais réfléchir|je vais y réfléchir|laissez-moi réfléchir|je reviendrai|je repasserai"),
              ("décideur", r"j'en parle à|je dois en parler|voir avec (?:mon|ma|mes)|c'est pas moi qui décide"),
              ("moment", r"pas le moment|pas maintenant|plus tard|rappelez-moi dans"),
              ("concurrent", r"déjà un fournisseur|on a déjà|on travaille déjà avec|je suis déjà chez"),
              ("intérêt", r"pas intéressée?|ça ne m'intéresse pas|envoyez-moi (?:un mail|une doc|la doc)"))


def words(text) -> list:
    return re.findall(r"[\wÀ-ÖØ-öø-ÿ'’-]+", text.lower())


def parse(text) -> list:
    """→ [(qui, réplique)] ; une ligne sans « Nom : » prolonge la réplique d'avant."""
    turns = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE.match(raw)
        if m and len(m.group(1).split()) <= 3:
            turns.append([m.group(1).strip(), m.group(2).strip()])
        elif turns:
            turns[-1][1] += " " + raw.strip()
    return [tuple(t) for t in turns]


def seller_of(turns, given=None) -> str:
    names = list(dict.fromkeys(t[0] for t in turns))
    if given:
        hit = next((n for n in names if n.lower() == given.lower()), None)
        if not hit:
            raise SystemExit(f"✗ « {given} » ne parle pas dans la transcription (personnes : {', '.join(names)})")
        return hit
    return next((n for n in names if n.lower() in SELLER), names[0])


def analyse(turns, me) -> dict:
    total = {w: 0 for w, _ in turns}
    questions, opened, monologue, run, fillers = [], 0, 0, 0, {}
    reform, objections, mine = [], [], []
    for i, (who, text) in enumerate(turns):
        n = len(words(text))
        total[who] += n
        if who == me:
            mine.append(text)
            run += n
            monologue = max(monologue, run)
            for q in re.findall(r"[^.?!]*\?", text):
                q = q.strip()
                if q:
                    questions.append(q)
                    opened += bool(OPEN.search(q))
            low = f" {' '.join(words(text))} "
            for f in FILLERS:
                c = low.count(f" {f} ")
                if c:
                    fillers[f] = fillers.get(f, 0) + c
            if REFORMULE.search(text):
                reform.append(text)
        else:
            run = 0
            for kind, rx in OBJECTIONS:
                if re.search(rx, text, re.I):
                    answer = next((t for w, t in turns[i + 1:] if w == me), "")
                    objections.append({"type": kind, "client": text, "reponse": answer})
                    break
    all_words = sum(total.values()) or 1
    my_words = total.get(me, 0)
    tail = " ".join(mine[-max(1, len(mine) // 5):]) if mine else ""
    return {"vendeur": me, "repliques": len(turns), "mots": all_words, "part_de_parole": round(100 * my_words / all_words),
            "questions": len(questions), "questions_ouvertes": opened, "exemples_questions": questions[:5],
            "plus_long_monologue_mots": monologue, "reformulations": len(reform), "remplissage": fillers,
            "objections": objections, "prochaine_etape": bool(NEXT.search(tail)),
            "fin_de_l_appel": tail[-200:]}


def show(r) -> str:
    L = [f"📞 Appel analysé : {r['repliques']} répliques, {r['mots']} mots ; vendeur : {r['vendeur']}",
         f"  Part de parole du vendeur : {r['part_de_parole']} % des mots",
         f"  Questions posées : {r['questions']} (dont {r['questions_ouvertes']} ouvertes)",
         f"  Plus long monologue : {r['plus_long_monologue_mots']} mots d'affilée",
         f"  Reformulations : {r['reformulations']}",
         "  Mots de remplissage : " + (", ".join(f"« {k} » ×{v}" for k, v in sorted(r["remplissage"].items(),
                                                                                    key=lambda kv: -kv[1]))
                                       or "aucun repéré")]
    for o in r["objections"]:
        L.append(f"  Objection ({o['type']}) : « {o['client'][:120]} »")
        L.append(f"    → réponse : « {o['reponse'][:160]} »" if o["reponse"] else "    → aucune réponse du vendeur ensuite")
    L.append("  Prochaine étape proposée en fin d'appel : " + ("oui" if r["prochaine_etape"] else "non repérée"))
    L.append("→ Des repères pour le débrief (fiche 08), pas une note : les relire avec la transcription.")
    return "\n".join(L)


def main(argv) -> int:
    pos = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] == "--moi")]
    if not pos or "--help" in argv:
        print(__doc__.strip())
        return 0 if "--help" in argv else 1
    path = Path(pos[0])
    if not path.is_file():
        print(f"✗ transcription introuvable : {path}")
        return 1
    turns = parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    if len({w for w, _ in turns}) < 2:
        print("✗ il faut au moins deux personnes, une réplique par ligne au format « Nom : texte »")
        return 1
    me = seller_of(turns, argv[argv.index("--moi") + 1] if "--moi" in argv and argv.index("--moi") + 1 < len(argv)
                   else None)
    r = analyse(turns, me)
    print(json.dumps(r, ensure_ascii=False, indent=1) if "--json" in argv else show(r))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
