"""The standard strategy report: nine sections in French, in Markdown and JSON (ADR-027, §17).

Every number is a :class:`~core.verification.figures.Figure` whose id starts with the tool that
computed it (``moteur/final/sharpe``, ``dsr/valeur``…): ``TOOLS`` maps each prefix to its module
(R1). Texts that are no measure (dates, parameters, fingerprints) name their tool too. The JSON
has no number outside a Figure; its SHA-256, taken on the bytes written, is what the audit
journal and an approval cite. The report never estimates what the protocol did not compute: a
missing measure says why (R12).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from core.config.loader import CrisisWindow, ResearchConfig
from core.finance.model import TRIAL_ORIGINS, canonical_json
from core.finance.research.engine import BacktestMeasures
from core.finance.research.execution import Costs
from core.finance.research.protocol import ProtocolResult, Verdict
from core.finance.research.registry import CostsKind, DataKind, StrategySpec
from core.finance.research.view import MarketHistory
from core.finance.store import RecordedTrial
from core.verification.figures import Figure, amount, count, percent, plain

FORMAT = "rapport-strategie/1"
NOTICE = "aide à la décision personnelle, pas un conseil en investissement (R16)"
SYNTHETIC = (
    "Démonstration sur données synthétiques : l'effet du jeu est planté. Ce rapport vérifie le "
    "protocole, pas une stratégie ; aucune conclusion d'investissement ne peut en sortir."
)
FICTITIOUS_COSTS = (
    "Frais fictifs : aucun courtier ne les pratique ; les frais réels restent A_DEFINIR "
    "(D13 de la phase 2)."
)
TOOLS = {
    "registre": "core.finance.research.registry (entrée du registre des stratégies)",
    "donnees": "core.finance.research.view.MarketHistory (base locale, révisions comprises)",
    "protocole": "core.finance.research.protocol.run_protocol (ADR-026)",
    "moteur": "core.finance.research.engine (moteur maison, ADR-024 et ADR-025)",
    "dsr": "core.finance.research.overfitting.deflated_sharpe (Bailey et López de Prado)",
    "pbo": "core.finance.research.overfitting.pbo (CSCV)",
    "journal": "core.finance.store.FinanceStore.trials (journal des essais, append-only)",
    "frais": "core.finance.research.execution.Costs",
    "crises": "fenêtres de crise : config/risk.yaml › historical_stress, ou le jeu synthétique",
    "config": "config/research.yaml, lu par core.config.loader",
}
LIMITS = (
    "Étiquettes : [Parité] pour la méthode du protocole (walk-forward, DSR, PBO, frais "
    "multipliés, crises, §10.6) ; [Hypothèse] pour chaque convention listée ci-dessous. Aucun "
    "chiffre de ce rapport n'est une prévision.",
    "Écarts backtest/live : ordres exécutés à la clôture de la séance suivante, sans place de "
    "cotation réelle, sans file d'ordres, sans exécution partielle ni suspension de cotation ; "
    "aucune latence ; aucun état persistant entre deux décisions hors de la vue point-in-time.",
    "Non modélisé : impôts (PFU, PEA), liquidité et impact de marché au-delà du glissement fixe, "
    "change (EUR seul, ADR-024), rémunération des liquidités (nulle).",
    "Un protocole réussi sur un échantillon passé ne garantit rien après un changement de régime.",
)
QUALITY = (
    "non évaluée : le protocole lit chaque série telle qu'elle a été publiée (vue point-in-time), "
    "sans score de qualité, et les seuils de config/data_sources.yaml restent A_DEFINIR (D12)"
)
# The figures §8 shows beside each gate, by id; an id the report did not compute is skipped.
GATE_FIGURES = {
    "r10": ("protocole/invariance/jours", "protocole/invariance/configurations", "protocole/r10"),
    "dsr": ("dsr/valeur", "config/gates/dsr_min", "dsr/essais"),
    "pbo": ("pbo/valeur", "config/gates/pbo_max"),
    "stabilite": (
        "protocole/walk_forward/sharpe",
        "moteur/final/sharpe",
        "config/gates/final_to_walk_forward_sharpe_min",
    ),
    "reference": (
        "moteur/final/sharpe",
        "protocole/reference/sharpe",
        "protocole/partition/final/rendements",
        "config/gates/benchmark_min_sessions",
    ),
    "frais": ("moteur/final_stresse/sharpe", "config/gates/cost_stress_multiplier"),
    "crises": ("protocole/crises/mesurees",),
}
STATUS = {"reussie": "réussie", "echouee": "échouée", "non evaluable": "non évaluable"}
VERDICT = {"reussi": "réussi", "echoue": "échoué", "incomplet": "incomplet"}


class ReportError(ValueError):
    """A report that cannot be built from the protocol it is given."""


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Row(_Out):
    """A measure and its value; ``outil`` is a key of TOOLS and the prefix of a Figure's id."""

    mesure: str
    valeur: Figure | str
    outil: str

    @model_validator(mode="after")
    def _traced(self) -> Row:
        if self.outil not in TOOLS:
            raise ValueError(f"outil inconnu : {self.outil}")
        if isinstance(self.valeur, Figure) and self.valeur.id.split("/")[0] != self.outil:
            raise ValueError(f"{self.valeur.id} n'est pas calculé par {self.outil}")
        return self


class Section(_Out):
    titre: str
    lignes: list[Row]
    notes: list[str] = []


class GateRecord(_Out):
    """A gate as the protocol returned it, its detail included (English decimals)."""

    cle: str
    libelle: str
    statut: str
    detail: str


class StrategyReport(_Out):
    format: Literal["rapport-strategie/1"]
    strategie: str
    nom: str
    genere_le: AwareDatetime
    avertissements: list[str]
    notice: str
    verdict: Verdict
    donnees: DataKind
    frais: CostsKind
    code_sha256: str
    grille_sha256: str
    outils: dict[str, str]
    portes: list[GateRecord]
    sections: list[Section]


@dataclass
class _Figures:
    """Every figure of the report by id, with its first label, so §8 cites the very same."""

    found: dict[str, tuple[str, Figure]]

    def row(self, label: str, figure: Figure) -> Row:
        _, known = self.found.setdefault(figure.id, (label, figure))
        if known != figure:
            raise ReportError(f"{figure.id} : deux valeurs dans le même rapport")
        return Row(mesure=label, valeur=figure, outil=figure.id.split("/")[0])


def _text(label: str, value: str, tool: str) -> Row:
    return Row(mesure=label, valeur=value, outil=tool)


def _span(first: date, last: date) -> str:
    return f"{first.isoformat()} → {last.isoformat()}"


def _ratio(figure_id: str, value: float, decimals: int = 2) -> Figure:
    return plain(figure_id, value, "ratio", decimals)


def _hypothesis(figs: _Figures, spec: StrategySpec, code: str, grid: str, points: int) -> Section:
    rows = [
        _text("Nom", spec.nom, "registre"),
        _text("Hypothèse", spec.hypothese, "registre"),
        _text("Règle", spec.regle, "registre"),
        _text("Module", f"{spec.module} › {spec.classe}", "registre"),
        _text("Fréquence", spec.frequence, "registre"),
        _text("Statut", spec.statut, "registre"),
        *[
            _text(f"Grille › {name}", ", ".join(canonical_json(v) for v in values), "registre")
            for name, values in spec.grille.items()
        ],
        *[
            _text("Contrainte", f"{c.parametre} < {c.inferieur_a}", "registre")
            for c in spec.contraintes
        ],
        figs.row(
            "Configurations essayées", count("registre/configurations", points, "configurations")
        ),
        _text("Empreinte du code (SHA-256)", code, "registre"),
        _text("Empreinte de la grille (SHA-256)", grid, "registre"),
    ]
    return Section(titre="1. Hypothèse et règle", lignes=rows)


def _data(
    figs: _Figures,
    spec: StrategySpec,
    result: ProtocolResult,
    history: MarketHistory,
    config: ResearchConfig,
) -> Section:
    split = result.partition
    first, last = split.development[0], split.final[1]
    cutoff = config.execution.decision_cutoff_utc
    rows = [
        _text("Nature", spec.donnees, "registre"),
        _text("Source", spec.source, "registre"),
        _text("Période demandée", _span(spec.periode.debut, spec.periode.fin), "registre"),
        _text("Séances communes de l'univers", _span(first, last), "protocole"),
        _text("Heure limite de décision (UTC)", cutoff.strftime("%H:%M"), "config"),
    ]
    for instrument_id in history.instruments:
        found = history.publications(instrument_id, start=first, end=last, cutoff=cutoff)
        base = f"donnees/{instrument_id}"
        rows += [
            figs.row(
                f"{instrument_id} › séances", count(f"{base}/seances", found.sessions, "séances")
            ),
            figs.row(
                f"{instrument_id} › séances corrigées",
                count(f"{base}/corrigees", found.corrected, "séances"),
            ),
            figs.row(
                f"{instrument_id} › premières publications après l'heure limite",
                count(f"{base}/tardives", found.late, "séances"),
            ),
            figs.row(
                f"{instrument_id} › opérations sur titres",
                count(f"{base}/operations", found.actions, "opérations"),
            ),
        ]
    final_returns = split.final_sessions - 1
    rows += [
        _text("Développement", _span(*split.development), "protocole"),
        figs.row(
            "Développement › séances",
            count(
                "protocole/partition/developpement/seances", split.development_sessions, "séances"
            ),
        ),
        figs.row(
            "Embargo",
            count("protocole/partition/embargo/seances", split.embargo_sessions, "séances"),
        ),
        _text("Échantillon final", _span(*split.final), "protocole"),
        figs.row(
            "Échantillon final › séances",
            count("protocole/partition/final/seances", split.final_sessions, "séances"),
        ),
        figs.row(
            "Échantillon final › rendements",
            count("protocole/partition/final/rendements", final_returns, "rendements"),
        ),
        figs.row(
            "Invariance par troncature › jours vérifiés",
            count("protocole/invariance/jours", len(result.invariance_days), "jours"),
        ),
        figs.row(
            "Invariance par troncature › configurations",
            count("protocole/invariance/configurations", len(result.grid), "configurations"),
        ),
        figs.row(
            "Invariance par troncature › écarts",
            count("protocole/r10", len(result.breaches), "écarts"),
        ),
        _text("Qualité des données", QUALITY, "donnees"),
    ]
    notes = [
        "Point-in-time (R10) : chaque décision lit les clôtures publiées avant l'heure limite de "
        "sa séance, dans leur dernière révision connue alors, ajustées des opérations annoncées "
        "alors ; les exécutions et les valorisations utilisent la dernière révision.",
        "Invariance par troncature : la décision recalculée sur un historique coupé à la date de "
        "décision doit être identique ; un écart fait échouer le protocole sans inscrire d'essai.",
    ]
    return Section(titre="2. Données", lignes=rows, notes=notes)


def _costs(
    figs: _Figures, costs: Costs, kind: CostsKind, initial_cash: float, config: ResearchConfig
) -> Section:
    rows = [
        _text("Nature", kind, "frais"),
        _text("Nom", costs.name, "frais"),
        figs.row("Commission (part du montant)", percent("frais/commission", costs.commission)),
        figs.row("Commission minimale par ordre", amount("frais/minimum", costs.minimum, "EUR")),
        figs.row("Glissement (part du cours)", percent("frais/glissement", costs.slippage)),
        _text("Arrondi des montants", costs.rounding, "frais"),
        figs.row(
            "Multiplicateur du test de frais",
            plain(
                "config/gates/cost_stress_multiplier",
                config.gates.cost_stress_multiplier,
                "fois",
                2,
            ),
        ),
        figs.row("Capital initial", amount("registre/capital_initial", initial_cash, "EUR")),
    ]
    notes = ["Les frais de change sont sans effet : les moteurs n'acceptent que l'euro (ADR-024)."]
    return Section(titre="3. Frais et glissement", lignes=rows, notes=notes)


def _trials(figs: _Figures, result: ProtocolResult, trials: Sequence[RecordedTrial]) -> Section:
    origins = Counter(row.trial.origin for row in trials)
    version = sum(1 for row in trials if row.trial.code_sha256 == result.code_sha256)
    rows = [
        figs.row(
            "Essais de la famille (N)", count("journal/essais/famille", len(trials), "essais")
        ),
        figs.row(
            "Essais de cette version du code", count("journal/essais/version", version, "essais")
        ),
        *[
            figs.row(f"Origine « {o} »", count(f"journal/essais/{o}", origins[o], "essais"))
            for o in TRIAL_ORIGINS
        ],
    ]
    notes = [
        "N compte toutes les origines, criblage et Copilot compris : le DSR le déflate (ADR-026)."
    ]
    found = result.evaluation
    if found is not None:
        rows += [
            figs.row(
                "Inscrits par ce protocole",
                count("protocole/essais_inscrits", found.trials_recorded, "essais"),
            ),
            figs.row(
                "Lectures antérieures de l'échantillon final (cette version)",
                count("protocole/lectures_finales", found.final_readings_before, "lectures"),
            ),
        ]
        if found.final_readings_before:
            notes.append(
                "L'échantillon final de cette version a déjà été lu : il n'est plus tout à fait "
                "hors échantillon."
            )
    return Section(titre="4. Essais et leur origine", lignes=rows, notes=notes)


def _measures(figs: _Figures, base: str, title: str, m: BacktestMeasures) -> list[Row]:
    def ratio(label: str, key: str, value: float | None) -> Row:
        if value is None:
            return _text(f"{title} › {label}", "non défini (aucune dispersion)", "moteur")
        return figs.row(f"{title} › {label}", _ratio(f"{base}/{key}", value))

    drawdown = m.drawdown
    return [
        figs.row(f"{title} › rendements", count(f"{base}/rendements", m.sessions, "rendements")),
        figs.row(f"{title} › rendement total", percent(f"{base}/rendement_total", m.total_return)),
        figs.row(
            f"{title} › rendement annualisé", percent(f"{base}/rendement_annuel", m.annual_return)
        ),
        figs.row(f"{title} › volatilité annualisée", percent(f"{base}/volatilite", m.volatility)),
        ratio("Sharpe annualisé", "sharpe", m.sharpe),
        ratio("Sortino annualisé", "sortino", m.sortino),
        figs.row(f"{title} › perte maximale", percent(f"{base}/perte_max", drawdown.depth)),
        _text(f"{title} › pic → creux", _span(drawdown.peak, drawdown.trough), "moteur"),
        ratio("Calmar", "calmar", m.calmar),
        figs.row(f"{title} › rotation annualisée", _ratio(f"{base}/rotation", m.turnover)),
        figs.row(
            f"{title} › transactions", count(f"{base}/transactions", m.trades, "transactions")
        ),
        figs.row(f"{title} › frais payés", amount(f"{base}/frais", m.fees, "EUR")),
        figs.row(f"{title} › exposition moyenne", percent(f"{base}/exposition", m.mean_exposure)),
    ]


def _not_evaluated(title: str, result: ProtocolResult) -> Section:
    failed = "; ".join(f"{g.label} : {g.detail}" for g in result.gates if g.status == "echouee")
    return Section(
        titre=title,
        lignes=[_text("Résultat", f"non évalué : {failed or 'protocole interrompu'}", "protocole")],
    )


def _results(figs: _Figures, result: ProtocolResult) -> Section:
    title = "5. Walk-forward et échantillon final, face à la référence"
    found = result.evaluation
    if found is None:
        return _not_evaluated(title, result)
    rows = [
        _text(
            "Configuration retenue (meilleur Sharpe de développement)",
            canonical_json(found.chosen),
            "protocole",
        ),
        *_measures(figs, "moteur/developpement", "Développement", found.development),
    ]
    for k, fold in enumerate(found.folds, start=1):
        rows += [
            _text(f"Pli {k} › apprentissage", _span(*fold.train), "protocole"),
            _text(f"Pli {k} › test", _span(*fold.test), "protocole"),
            _text(f"Pli {k} › configuration", canonical_json(fold.params), "protocole"),
        ]
    walk = found.walk_forward_sharpe
    rows.append(
        _text("Walk-forward › Sharpe annualisé", "non défini (aucune dispersion)", "protocole")
        if walk is None
        else figs.row(
            "Walk-forward › Sharpe annualisé", _ratio("protocole/walk_forward/sharpe", walk)
        )
    )
    rows += _measures(figs, "moteur/final", "Final", found.final)
    rows.append(_text("Référence", found.benchmark_label or "aucune", "protocole"))
    if found.benchmark_sharpe is not None:
        rows.append(
            figs.row(
                "Référence › Sharpe annualisé (final)",
                _ratio("protocole/reference/sharpe", found.benchmark_sharpe),
            )
        )
    notes = [
        "Walk-forward ancré : chaque pli choisit la configuration au meilleur Sharpe sur les "
        "blocs passés, puis la teste sur le bloc suivant ; le Sharpe chaîne ces tests.",
    ]
    return Section(titre=title, lignes=rows, notes=notes)


def _overfitting(figs: _Figures, result: ProtocolResult, config: ResearchConfig) -> Section:
    title = "6. DSR, PBO et sensibilité aux frais"
    found = result.evaluation
    if found is None:
        return _not_evaluated(title, result)
    gates = config.gates
    rows: list[Row] = []
    dsr = found.dsr
    if dsr is None or dsr.value is None:
        rows.append(_text("DSR", f"non évaluable : {found.dsr_reason or 'non défini'}", "dsr"))
    else:
        rows.append(figs.row("DSR", plain("dsr/valeur", dsr.value, "score", 4)))
    if dsr is not None:
        rows += [
            figs.row("DSR › essais (N)", count("dsr/essais", dsr.trials, "essais")),
            figs.row(
                "DSR › variance des Sharpe (V)", plain("dsr/variance", dsr.variance, "variance", 8)
            ),
            figs.row("DSR › Sharpe quotidien", _ratio("dsr/sharpe_quotidien", dsr.sharpe, 4)),
            figs.row("DSR › asymétrie", plain("dsr/asymetrie", dsr.skewness, "coefficient", 4)),
            figs.row(
                "DSR › aplatissement", plain("dsr/aplatissement", dsr.kurtosis, "coefficient", 4)
            ),
            figs.row("DSR › rendements (T)", count("dsr/rendements", dsr.sessions, "rendements")),
            figs.row("DSR › Sharpe maximal attendu (SR₀)", _ratio("dsr/seuil", dsr.threshold, 4)),
        ]
    rows.append(
        figs.row("DSR › minimum exigé", plain("config/gates/dsr_min", gates.dsr_min, "score", 4))
    )
    found_pbo = found.pbo
    if found_pbo.value is None:
        rows.append(_text("PBO", f"non évaluable : {found_pbo.reason or 'non défini'}", "pbo"))
    else:
        rows.append(figs.row("PBO", plain("pbo/valeur", found_pbo.value, "score", 4)))
    rows += [
        figs.row(
            "PBO › partitions (S)", count("pbo/partitions", found_pbo.partitions, "partitions")
        ),
        figs.row(
            "PBO › combinaisons", count("pbo/combinaisons", found_pbo.combinations, "combinaisons")
        ),
        figs.row(
            "PBO › configurations",
            count("pbo/configurations", found_pbo.configurations, "configurations"),
        ),
        figs.row("PBO › rendements gardés", count("pbo/rendements", found_pbo.rows, "rendements")),
        figs.row("PBO › rendements écartés", count("pbo/ecartes", found_pbo.dropped, "rendements")),
        figs.row(
            "PBO › maximum toléré (exclu)", plain("config/gates/pbo_max", gates.pbo_max, "score", 4)
        ),
    ]
    stressed = found.final_stressed
    rows += [
        (
            _text("Final à frais normaux › Sharpe", "non défini", "moteur")
            if found.final.sharpe is None
            else figs.row(
                "Final à frais normaux › Sharpe", _ratio("moteur/final/sharpe", found.final.sharpe)
            )
        ),
        (
            _text("Final à frais multipliés › Sharpe", "non défini", "moteur")
            if stressed.sharpe is None
            else figs.row(
                "Final à frais multipliés › Sharpe",
                _ratio("moteur/final_stresse/sharpe", stressed.sharpe),
            )
        ),
        figs.row(
            "Final à frais multipliés › frais payés",
            amount("moteur/final_stresse/frais", stressed.fees, "EUR"),
        ),
        figs.row(
            "Stabilité › ratio minimal final / walk-forward",
            _ratio(
                "config/gates/final_to_walk_forward_sharpe_min",
                gates.final_to_walk_forward_sharpe_min,
            ),
        ),
        figs.row(
            "Référence › rendements finals minimaux",
            count(
                "config/gates/benchmark_min_sessions", gates.benchmark_min_sessions, "rendements"
            ),
        ),
    ]
    notes = [
        "DSR : probabilité que le vrai Sharpe dépasse le maximum attendu de N essais sans "
        "talent, compte tenu de T, de l'asymétrie et de l'aplatissement (unités quotidiennes).",
        "PBO : part des combinaisons CSCV où la meilleure configuration en apprentissage finit "
        "sous la médiane en test.",
    ]
    return Section(titre=title, lignes=rows, notes=notes)


def _crises(figs: _Figures, result: ProtocolResult, crises: Mapping[str, CrisisWindow]) -> Section:
    title = "7. Périodes de crise"
    found = result.evaluation
    if found is None:
        return _not_evaluated(title, result)
    rows: list[Row] = []
    for measure in found.crises:
        window = crises.get(measure.key)
        if window is not None:
            rows.append(
                _text(
                    f"{measure.label} › fenêtre",
                    f"{window.start} → {window.end} ; source : {window.source}",
                    "crises",
                )
            )
        if measure.reason is not None:
            rows.append(_text(f"{measure.label} › mesure", measure.reason, "protocole"))
            continue
        base = f"protocole/crises/{measure.key}"
        for who, ret, depth in (
            ("stratégie", measure.strategy_return, measure.strategy_drawdown),
            ("référence", measure.benchmark_return, measure.benchmark_drawdown),
        ):
            key = "strategie" if who == "stratégie" else "reference"
            if ret is not None:
                rows.append(
                    figs.row(
                        f"{measure.label} › {who} › rendement",
                        percent(f"{base}/{key}/rendement", ret),
                    )
                )
            if depth is not None:
                rows.append(
                    figs.row(
                        f"{measure.label} › {who} › perte maximale",
                        percent(f"{base}/{key}/perte_max", depth),
                    )
                )
    measured = sum(1 for m in found.crises if m.reason is None)
    rows.append(figs.row("Crises mesurées", count("protocole/crises/mesurees", measured, "crises")))
    notes = [
        "Chaque crise se mesure de la dernière séance avant son début à sa fin, sur la "
        "fenêtre entière."
    ]
    return Section(titre=title, lignes=rows, notes=notes)


def _verdict(figs: _Figures, result: ProtocolResult) -> Section:
    rows = [_text("Verdict", VERDICT[result.verdict], "protocole")]
    for gate in result.gates:
        rows.append(_text(gate.label, STATUS[gate.status], "protocole"))
        for figure_id in GATE_FIGURES.get(gate.key, ()):
            if figure_id in figs.found:
                label, figure = figs.found[figure_id]
                rows.append(figs.row(f"{gate.label} › {label}", figure))
    notes = [
        "Verdict : « échoué » si une porte échoue, sinon « incomplet » si une porte n'est pas "
        "évaluable, sinon « réussi ». Seul « réussi » rend une stratégie promouvable, et "
        "seulement sur données et frais réels, par une approbation écrite par Lucas (ADR-027).",
        "Le détail brut de chaque porte, tel que le protocole l'a rendu, est dans le JSON "
        "(portes).",
    ]
    return Section(titre="8. Verdict et portes", lignes=rows, notes=notes)


def _limits(spec: StrategySpec, result: ProtocolResult) -> Section:
    notes = list(LIMITS)
    if spec.donnees == "synthetiques":
        notes.append(SYNTHETIC)
    notes += [f"[Hypothèse] {h}" for h in result.hypotheses]
    notes.append(NOTICE)
    return Section(titre="9. Limites", lignes=[], notes=notes)


def build_report(
    spec: StrategySpec,
    result: ProtocolResult,
    *,
    history: MarketHistory,
    costs: Costs,
    costs_kind: CostsKind,
    initial_cash: float,
    config: ResearchConfig,
    crises: Mapping[str, CrisisWindow],
    trials: Sequence[RecordedTrial],
    grid_sha256: str,
    generated_at: datetime,
) -> StrategyReport:
    """The nine sections from a finished protocol; ``trials`` is the family's journal after it."""
    if result.strategy_id != spec.id:
        raise ReportError(f"protocole de {result.strategy_id}, rapport de {spec.id}")
    if set(history.instruments) != set(spec.univers):
        raise ReportError("l'historique ne couvre pas exactement l'univers du registre")
    figs = _Figures({})
    warnings = []
    if spec.donnees == "synthetiques":
        warnings.append(SYNTHETIC)
    if costs_kind == "fictifs":
        warnings.append(FICTITIOUS_COSTS)
    sections = [
        _hypothesis(figs, spec, result.code_sha256, grid_sha256, len(result.grid)),
        _data(figs, spec, result, history, config),
        _costs(figs, costs, costs_kind, initial_cash, config),
        _trials(figs, result, trials),
        _results(figs, result),
        _overfitting(figs, result, config),
        _crises(figs, result, crises),
    ]
    sections += [_verdict(figs, result), _limits(spec, result)]
    return StrategyReport(
        format=FORMAT,
        strategie=spec.id,
        nom=spec.nom,
        genere_le=generated_at,
        avertissements=warnings,
        notice=NOTICE,
        verdict=result.verdict,
        donnees=spec.donnees,
        frais=costs_kind,
        code_sha256=result.code_sha256,
        grille_sha256=grid_sha256,
        outils=dict(TOOLS),
        portes=[
            GateRecord(cle=g.key, libelle=g.label, statut=g.status, detail=g.detail)
            for g in result.gates
        ],
        sections=sections,
    )


def report_json(report: StrategyReport) -> str:
    payload = report.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report_markdown(report: StrategyReport) -> str:
    lines = [f"# Rapport de stratégie — {report.nom} (`{report.strategie}`)", ""]
    lines += [f"> **Avertissement** : {w}" for w in report.avertissements]
    if report.avertissements:
        lines.append("")
    lines += [
        f"- Généré le : {report.genere_le.astimezone(UTC).isoformat()}",
        f"- Verdict : **{VERDICT[report.verdict]}**",
        f"- Données : {report.donnees} ; frais : {report.frais}",
        f"- Empreinte du code : `{report.code_sha256}`",
        f"- Empreinte de la grille : `{report.grille_sha256}`",
        f"- {report.notice}",
        "",
    ]
    for section in report.sections:
        lines += [f"## {section.titre}", ""]
        if section.lignes:
            lines += ["| Mesure | Valeur | Calculé par |", "|---|---|---|"]
            for row in section.lignes:
                if isinstance(row.valeur, Figure):
                    value, tool = row.valeur.display, f"`{row.valeur.id}`"
                else:
                    value, tool = row.valeur, row.outil
                lines.append(f"| {_cell(row.mesure)} | {_cell(value)} | {tool} |")
            lines.append("")
        lines += [f"- {note}" for note in section.notes]
        if section.notes:
            lines.append("")
    lines += ["## Outils", "", "| Préfixe | Outil |", "|---|---|"]
    lines += [f"| `{key}` | {_cell(tool)} |" for key, tool in report.outils.items()]
    return "\n".join(lines) + "\n"


def default_reports_dir(root: Path) -> Path:
    """Where ``cerveau strategy protocol`` writes: var/finance/research/reports/."""
    return root / "var" / "finance" / "research" / "reports"


def latest_report(strategy_id: str, directory: Path) -> tuple[Path, StrategyReport] | None:
    """A strategy's last report by generation time; an unreadable one refuses the lookup."""
    found: list[tuple[datetime, int, str, Path, StrategyReport]] = []
    for path in directory.glob(f"{strategy_id}-*.json"):
        try:
            report = StrategyReport.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            first = str(exc).splitlines()[0]
            raise ReportError(f"rapport {path.name} illisible : {first}") from exc
        if report.strategie != strategy_id:
            raise ReportError(f"rapport {path.name} : il porte sur {report.strategie}")
        # A second report of the day is ``<id>-<date>-2``: a longer name comes later.
        found.append((report.genere_le, len(path.name), path.name, path, report))
    if not found:
        return None
    *_, path, report = max(found, key=lambda item: item[:3])
    return path, report


@dataclass(frozen=True)
class WrittenReport:
    markdown: Path
    json: Path
    sha256: str  # of the JSON bytes written


def write_report(report: StrategyReport, directory: Path) -> WrittenReport:
    """``<id>-<date>.md`` and ``.json``; a second report of the day gets ``-2``, never lost."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{report.strategie}-{report.genere_le.astimezone(UTC).date().isoformat()}"
    body = report_json(report).encode("utf-8")
    text = report_markdown(report).encode("utf-8")
    suffix = 1
    while True:
        name = stem if suffix == 1 else f"{stem}-{suffix}"
        md, js = directory / f"{name}.md", directory / f"{name}.json"
        if not md.exists() and not js.exists():
            break
        suffix += 1
    with js.open("xb") as handle:
        handle.write(body)
    with md.open("xb") as handle:
        handle.write(text)
    return WrittenReport(md, js, hashlib.sha256(body).hexdigest())
