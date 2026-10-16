"""Garde anti-secrets : aucune clé, aucun jeton, aucun mot de passe ne doit entrer dans le cerveau.

Tout ce qui est écrit (ajout, modification, import) passe par mask() : un secret reconnu est remplacé par
« «type masqué» » et la commande le signale. `doctor` et `consolidate` contrôlent aussi l'existant."""
from __future__ import annotations

import re

_RULES = [
    ("clé API Anthropic/OpenAI", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    ("jeton Shopify", r"\bshp(?:at|ss|ca|pa)_[A-Fa-f0-9]{20,}"),
    ("jeton GitHub", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    ("jeton Slack", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("clé AWS", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("clé Google", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("jeton OAuth Google", r"\bya29\.[0-9A-Za-z_-]{20,}"),
    ("clé Stripe", r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}"),
    ("jeton JWT", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("clé privée", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    ("secret", r"\b(?i:api[_ -]?key|client[_ -]?secret|secret|access[_ -]?token|token|jeton|bearer)\s*[:=]\s*['\"]?"
               r"(?=[A-Za-z0-9_\-./+]*\d)[A-Za-z0-9_\-./+]{16,}"),
    # (?i:…) seulement sur le mot-clé : la valeur doit contenir un chiffre, un symbole ou une majuscule
    # (« mot de passe : jamais dans le cerveau » n'est pas un secret)
    ("mot de passe", r"\b(?i:mot de passe|mdp|password|passwd|pwd)(?:[:=]['\"]?[^\s'\"]{4,}"
                     r"|\s*[:=]\s*['\"]?(?=\S*(?:[\dA-Z_]|[^\w\s]))[^\s'\"]{6,})"),
]
RULES = [(label, re.compile(rx)) for label, rx in _RULES]


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w+])(?:\+33\s?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}(?!\d)")


def redact_contacts(text) -> str:
    """Coordonnées de tiers (e-mails, téléphones) et secrets retirés d'un texte avant de l'enregistrer au journal."""
    text = _EMAIL.sub("«e-mail»", str(text or ""))
    text = _PHONE.sub("«téléphone»", text)
    return mask(text)[0]


def find(text) -> list:
    """Types de secrets présents dans un texte (sans les afficher)."""
    return [label for label, rx in RULES if rx.search(str(text or ""))]


def mask(text):
    """→ (texte avec secrets masqués, [types trouvés])."""
    found = []
    text = str(text or "")
    for label, rx in RULES:
        def rep(m, label=label):
            found.append(label)
            return f"«{label} masqué»"
        text = rx.sub(rep, text)
    return text, found
