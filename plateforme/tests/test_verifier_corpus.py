"""The corpus of the `verifier` tool of the MCP bridge (plan B1.1, audit of 20/11, G-1 and G-10).

21 drafts that invent a number or a date, each with the tool outputs of its session, must be
refused; 18 correct drafts must be accepted. The audit's own 39 drafts were not kept: this corpus
rebuilds them (the three known examples first) and adds the other ways to launder a number.

Baseline, measured on 26/11/2026 on the code before B1.1 (``Bridge.verify(draft)``, without the
date of the day nor the user's citations): 5 of 21 invented drafts refused, 9 of 18 correct
drafts accepted (the audit measured 5/21 and 11/18 on its own corpus). After B1.1: 21/21, 18/18.
The floors below can only go up (R9).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from core.audit import AuditJournal
from core.verification.figures import Figure, amount, count, percent, plain, price
from core.verification.trace import tool_output
from interfaces.mcp_server.server import MAX_CITATION_CHARS, MAX_CITATIONS, Bridge, build_server

REFUSED_FLOOR = 21  # of 21: baseline 5
ACCEPTED_FLOOR = 18  # of 18: baseline 9
TODAY = datetime(2026, 11, 26, 10, 30, tzinfo=timezone(timedelta(hours=1)))


def fig(figure: Figure) -> dict[str, Any]:
    return figure.model_dump()


RISK = {  # finance_risk › risk_report, as the plugin shapes it
    "portefeuille": "principal",
    "lu_le": "2026-11-25T18:00:00+01:00",
    "total_eur": fig(amount("total_eur", Decimal("1254300"), "EUR")),
    "methode": {
        "fenetre": fig(count("methode/fenetre", 500, "séances")),
        "confiance": [fig(percent("methode/confiance/99", 0.99))],
    },
    "var": [
        {
            "methode": "historique",
            "confiance": fig(percent("var/historique/99/1/confiance", 0.99)),
            "horizon": fig(count("var/historique/99/1/horizon", 1, "séances")),
            "var_eur": fig(amount("var/historique/99/1/eur", Decimal("23456.78"), "EUR")),
            "var_pct": fig(percent("var/historique/99/1/pct", 0.0187)),
            "cvar_eur": fig(amount("var/historique/99/1/cvar_eur", Decimal("31002.40"), "EUR")),
            "cvar_pct": fig(percent("var/historique/99/1/cvar_pct", 0.0247)),
        }
    ],
    "volatilite": {
        "quotidienne": fig(percent("volatilite/quotidienne", 0.009)),
        "annualisee": fig(percent("volatilite/annualisee", 0.1432)),
    },
    "drawdown": {
        "maximum": fig(percent("drawdown/maximum", -0.151)),
        "actuel": fig(percent("drawdown/actuel", -0.032)),
    },
    "beta": {
        "portefeuille": fig(plain("beta/portefeuille", 0.87, "beta")),
        "seances": fig(count("beta/seances", 250, "séances")),
    },
    "avertissements": ["Historique court pour FICT-C : 180 séances."],
}
PERF = {  # finance_report › performance_report
    "periode": {
        "debut": "2025-11-25",
        "fin": "2026-11-25",
        "jours": fig(count("periode/jours", 365, "jours")),
    },
    "valeurs": {
        "fin_eur": fig(amount("valeurs/fin_eur", Decimal("1254300"), "EUR")),
        "gain_eur": fig(amount("valeurs/gain_eur", Decimal("101420.35"), "EUR")),
        "frais_eur": fig(amount("valeurs/frais_eur", Decimal("-1240.50"), "EUR")),
    },
    "mesures": {
        "twr": fig(percent("mesures/twr", 0.088)),
        "volatilite": fig(percent("mesures/volatilite", 0.0962)),
        "sharpe": fig(plain("mesures/sharpe", 1.12, "ratio")),
        "perte_max": fig(percent("mesures/perte_max", -0.0931)),
    },
}
MARKET = {  # finance_data › market_data, with a loose number (a fraction) left by the source
    "instruments": [
        {
            "id": "FICT-A",
            "cloture": fig(price("FICT-A/cloture/2026-11-25", Decimal("182.4"), "EUR")),
            "derniere_seance": "2026-11-25",
            "age_jours": fig(count("FICT-A/age_jours", 1, "jours")),
            "rendement_dividende": 0.031,
        }
    ]
}
PAGE = {  # web_research › web_read
    "url": "https://presse.example/marches/cloture",
    "final_url": "https://presse.example/marches/cloture",
    "content_type": "text/html",
    "title": "Bourse de Paris : le CAC 40 termine en hausse",
    "published": "2026-11-24",
    "text": (
        "Le CAC 40 a clôturé lundi à 7 412,35 points, en hausse de 0,8 %. Les fonds monétaires "
        "ont collecté 10 milliards d'euros en octobre. Le taux du Livret A reste fixé à 2,4 % "
        "depuis le 1er août 2026. Un gérant interrogé estime à 18 % la volatilité implicite."
    ),
    "truncated": False,
    "retrieved_at": "2026-11-25T21:12:00+01:00",
}
SEARCH = {  # web_research › web_search
    "query": "taux OAT 10 ans et inflation en octobre",
    "provider": "moteur",
    "results": [
        {
            "rank": 1,
            "title": "Le rendement de l'OAT à 10 ans atteint 3,12 %",
            "url": "https://presse.example/oat",
            "snippet": "Le taux de l'emprunt d'État français à 10 ans a touché 3,12 % mardi.",
            "age": "il y a 2 jours",
        },
        {
            "rank": 2,
            "title": "Inflation : 1,8 % sur un an en octobre",
            "url": "https://stats.example/inflation",
            "snippet": "Selon l'Insee, les prix ont augmenté de 1,8 % sur un an en octobre.",
            "age": None,
        },
    ],
}
LEGAL = {  # legifrance › legi_article
    "id": "LEGIARTI000032041571",
    "numero": "1240",
    "texte": "Code civil",
    "contenu": (
        "Tout fait quelconque de l'homme, qui cause à autrui un dommage, oblige celui par la "
        "faute duquel il est arrivé à le réparer."
    ),
    "en_vigueur_depuis": "2016-10-01",
}
OUTPUTS = {
    "risk_report": RISK,
    "performance_report": PERF,
    "market_data": MARKET,
    "web_read": PAGE,
    "web_search": SEARCH,
    "legi_article": LEGAL,
}


@dataclass(frozen=True)
class Case:
    name: str
    draft: str
    tools: tuple[str, ...]  # the session's calls, in order
    user: tuple[str, ...] = ()  # citations_utilisateur

    def __str__(self) -> str:
        return self.name


INVENTED = [
    # The three examples of the audit.
    Case(
        "apostrophes : trois morceaux pris ailleurs",
        "Ton portefeuille vaut 10'000'000 €.",
        ("risk_report", "web_search", "web_read"),
    ),
    Case("zéro avec une échelle", "Ton exposition aux obligations est de 0 Md€.", ("risk_report",)),
    Case(
        "chiffre d'une page présenté comme une VaR",
        "La VaR à 99 % sur une séance de ton portefeuille est de 7 412,35 €.",
        ("risk_report", "web_read"),
    ),
    # Separators and glued pieces.
    Case(
        "apostrophes typographiques",
        "Tes liquidités atteignent 3’500’000 €.",
        ("risk_report", "web_search", "web_read"),
    ),
    Case(
        "espace de chiffre (U+2007)",
        "Ton portefeuille vaut 10 000 000 €.",
        ("risk_report", "web_search", "web_read"),
    ),
    Case(
        "chiffres coupés par du gras",
        "Tu as **1**0 000 € de liquidités disponibles.",
        ("risk_report", "web_search", "web_read"),
    ),
    Case(
        "chiffres coupés par une espace sans chasse",
        "FICT-A représente 1​00 % de ton portefeuille.",
        ("risk_report", "web_search", "web_read"),
    ),
    Case(
        "exposant collé",
        "Les fonds monétaires gèrent 10⁶ € de tes avoirs.",
        ("web_search", "web_read"),
    ),
    # Scales and rounding.
    Case(
        "zéro sans échelle",
        "Les frais de la période sont de 0 €.",
        ("performance_report", "web_read"),
    ),
    Case(
        "arrondi qui change d'ordre de grandeur",
        "Ton bêta est de 1, comme le marché.",
        ("risk_report",),
    ),
    Case(
        "échelle multipliée par mille",
        "Les frais payés cette année s'élèvent à 1 240,50 k€.",
        ("performance_report",),
    ),
    # Percent and fraction.
    Case(
        "fraction lue comme un pourcentage",
        "Le dividende de FICT-A rapporte 0,031 % par an.",
        ("market_data",),
    ),
    # Signs.
    Case(
        "signe contraire d'une figure",
        "Ton TWR sur un an est de -8,80 %.",
        ("performance_report",),
    ),
    Case(
        "signe contraire d'une page",
        "Le CAC 40 a reculé de 0,8 % lundi.",
        ("web_read",),
    ),
    # A figure given as another metric.
    Case(
        "TWR présenté comme une volatilité",
        "La volatilité annualisée de ton portefeuille est de 8,80 %.",
        ("performance_report",),
    ),
    Case(
        "CVaR présentée comme une VaR",
        "Ta VaR historique sur une séance est de 31 002,40 €.",
        ("risk_report",),
    ),
    Case(
        "bêta présenté comme un ratio de Sharpe",
        "Le ratio de Sharpe de ton portefeuille est de 0,87.",
        ("risk_report",),
    ),
    # Search results presented as computed metrics.
    Case(
        "résultat de recherche présenté comme un Sharpe",
        "Ton ratio de Sharpe est de 3,12.",
        ("performance_report", "web_search"),
    ),
    Case(
        "résultat de recherche présenté comme une perte maximale",
        "Ta perte maximale sur un an est de 1,8 %.",
        ("performance_report", "web_search"),
    ),
    # The user's citations, which Claude writes itself.
    Case(
        "citation de l'utilisateur présentée comme une VaR",
        "Ta VaR à 99 % est de 50 000 €.",
        ("risk_report",),
        ("ma VaR est de 50 000 € je crois",),
    ),
    Case(
        "citation de l'utilisateur arrondie",
        "Tu as 12 300 € sur ton Livret A.",
        (),
        ("j'ai 12 345 € sur mon Livret A",),
    ),
]
CORRECT = [
    Case(
        "date du jour",
        "Au 26/11/2026, ton portefeuille vaut 1 254 300,00 €.",
        ("risk_report",),
    ),
    Case(
        "jour et mois du jour",
        "Ce 26 novembre, en novembre 2026, ta VaR historique est de 23 456,78 €.",
        ("risk_report",),
    ),
    Case(
        "« Étape 2 »",
        "Étape 2 : relire la VaR à 99 % sur une séance, 23 456,78 €.",
        ("risk_report",),
    ),
    Case(
        "« phase 3 » et « chapitre 5 »",
        "Phase 3 du plan, chapitre 5 : la volatilité annualisée est de 14,32 %.",
        ("risk_report",),
    ),
    Case(
        "« section 4 » et « étapes 2 et 3 »",
        "Section 4, étapes 2 et 3 : le bêta est de 0,87 sur 250 séances.",
        ("risk_report",),
    ),
    Case(
        "montant de l'utilisateur",
        "Avec tes 25 000 € sur le Livret A, rémunéré à 2,4 % [1], tu gardes ton épargne de "
        "précaution.",
        ("web_read",),
        ("J'ai 25 000 € sur mon Livret A, je veux en garder une partie.",),
    ),
    Case(
        "pourcentage et date de l'utilisateur",
        "Tu vises 4 % par an jusqu'au 31 décembre 2030, avec un TWR de 8,80 % cette année.",
        ("performance_report",),
        ("Je vise 4 % par an jusqu'au 31 décembre 2030.",),
    ),
    Case(
        "nombres de l'utilisateur répétés",
        "Tu veux placer 5 000 € par an pendant 10 ans.",
        (),
        ("je veux placer 5 000 € par an pendant 10 ans", "et rien de plus"),
    ),
    Case(
        "chiffres cités tels quels",
        "Ta VaR historique à 99 % sur une séance est de 23 456,78 €, soit 1,87 % du "
        "portefeuille ; la CVaR est de 31 002,40 €.",
        ("risk_report",),
    ),
    Case(
        "arrondi dans le même ordre de grandeur",
        "Ta volatilité annualisée est d'environ 14 %.",
        ("risk_report",),
    ),
    Case(
        "arrondi à la puissance de dix supérieure",
        "La volatilité de ton portefeuille sur un an est d'environ 10 %.",
        ("performance_report",),
    ),
    Case(
        "page web citée",
        "Selon la presse [1], le CAC 40 a clôturé à 7 412,35 points, en hausse de 0,8 %.",
        ("web_read",),
    ),
    Case(
        "résultat de recherche cité",
        "L'Insee [2] mesure une hausse des prix de 1,8 % sur un an en octobre.",
        ("web_search",),
    ),
    Case(
        "échelle juste",
        "Les fonds monétaires ont collecté 10 Md€ en octobre [1].",
        ("web_read",),
    ),
    Case(
        "apostrophes suisses",
        "Ton portefeuille vaut 1'254'300 €.",
        ("risk_report",),
    ),
    Case(
        "article de loi",
        "L'article 1240 du Code civil, en vigueur depuis le 01/10/2016, fonde ta demande.",
        ("legi_article",),
    ),
    Case(
        "mesures de deux appels",
        "Ton ratio de Sharpe est de 1,12 et ton TWR de 8,80 % ; ta perte maximale est de "
        "15,10 % et ton bêta de 0,87.",
        ("performance_report", "risk_report"),
    ),
    Case(
        "prix et dividende",
        "FICT-A a clôturé à 182,40 € le 25/11/2026, avec un dividende de 3,1 % par an.",
        ("market_data",),
    ),
]


def session(case: Case, tmp_path: Path) -> Bridge:
    bridge = Bridge(journal=AuditJournal(tmp_path / "journal.jsonl"), clock=lambda: TODAY)
    seen: dict[str, int] = {}
    for tool in case.tools:
        seen[tool] = seen.get(tool, 0) + 1
        bridge.outputs.append(tool_output(f"{tool}#{seen[tool]}", tool, OUTPUTS[tool]))
    return bridge


def verdict(case: Case, tmp_path: Path) -> dict[str, Any]:
    return session(case, tmp_path).verify(case.draft, case.user)


def test_the_corpus_has_21_invented_and_18_correct_drafts() -> None:
    assert (len(INVENTED), len(CORRECT)) == (21, 18)
    assert len({case.name for case in [*INVENTED, *CORRECT]}) == 39


def test_the_scores_reach_their_floors(tmp_path: Path) -> None:
    refused = [c for c in INVENTED if not verdict(c, tmp_path)["ok"]]
    accepted = [c for c in CORRECT if verdict(c, tmp_path)["ok"]]
    assert len(refused) >= REFUSED_FLOOR, [str(c) for c in INVENTED if c not in refused]
    assert len(accepted) >= ACCEPTED_FLOOR, [str(c) for c in CORRECT if c not in accepted]


@pytest.mark.parametrize("case", INVENTED, ids=str)
def test_an_invented_draft_is_refused(case: Case, tmp_path: Path) -> None:
    result = verdict(case, tmp_path)
    assert result["ok"] is False, result
    assert result["sans_source"] or result["signe_contraire"]


@pytest.mark.parametrize("case", CORRECT, ids=str)
def test_a_correct_draft_is_accepted(case: Case, tmp_path: Path) -> None:
    result = verdict(case, tmp_path)
    assert result["ok"] is True, result
    assert result["sans_source"] == result["signe_contraire"] == []


def test_the_user_numbers_stay_visible(tmp_path: Path) -> None:
    case = next(c for c in CORRECT if c.name == "pourcentage et date de l'utilisateur")
    result = verdict(case, tmp_path)
    assert result["utilisateur"] == [
        {"valeur": "4 %", "source": "utilisateur"},
        {"valeur": "31 décembre 2030", "source": "utilisateur"},
    ]
    assert [row["valeur"] for row in result["verifies"]] == ["8,80 %"]


def test_each_check_is_journaled_without_numbers_or_text(tmp_path: Path) -> None:
    case = next(c for c in CORRECT if c.name == "montant de l'utilisateur")
    bridge = session(case, tmp_path)
    bridge.verify(case.draft, case.user)
    bridge.verify("Ton portefeuille vaut 10'000'000 € au 26/11/2026.")
    lines = bridge.log.path.read_text(encoding="utf-8").splitlines()
    payloads = [bridge.log.read_payload(json.loads(line)["payload_ref"]) for line in lines]
    assert [p["verification"] for p in payloads] == [
        {
            "ok": True,
            "nombres": 2,
            "dates": 0,
            "traces": 1,
            "utilisateur": 1,
            "sans_source": 0,
            "signe_contraire": 0,
            "citations_utilisateur": 1,
        },
        {
            "ok": False,
            "nombres": 1,
            "dates": 1,
            "traces": 1,
            "utilisateur": 0,
            "sans_source": 1,
            "signe_contraire": 0,
            "citations_utilisateur": 0,
        },
    ]
    written = json.dumps(payloads, ensure_ascii=False)
    for secret in ("25 000", "25 000", "Livret", "10'000'000", "2026"):
        assert secret not in written  # neither numbers nor text (R6, R11)


def test_the_tool_takes_the_user_citations_and_bounds_them(tmp_path: Path) -> None:
    case = next(c for c in CORRECT if c.name == "nombres de l'utilisateur répétés")
    bridge = session(case, tmp_path)

    async def go() -> Any:
        async with Client(build_server(bridge)) as client:
            listed = {tool.name: tool for tool in (await client.list_tools()).tools}
            alone = await client.call_tool("verifier", {"brouillon": case.draft})
            quoted = await client.call_tool(
                "verifier",
                {"brouillon": case.draft, "citations_utilisateur": list(case.user)},
            )
            return listed["verifier"], alone, quoted

    tool, alone, quoted = asyncio.run(go())
    assert "citations_utilisateur" in tool.input_schema["properties"]
    assert (alone.structured_content or {})["ok"] is False
    assert (quoted.structured_content or {})["ok"] is True
    assert len(bridge.log.path.read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(ToolError):
        bridge.verify(case.draft, ["5 000 €"] * (MAX_CITATIONS + 1))
    with pytest.raises(ToolError):
        bridge.verify(case.draft, ["5" * (MAX_CITATION_CHARS + 1)])
