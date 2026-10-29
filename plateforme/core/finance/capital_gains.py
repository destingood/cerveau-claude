"""The sales of a calendar year, exported for the user's own records (plan of phase 2, F9).

For each sale of a security the export gives the weighted average price of the position it came
from (account by account, as the book keeps it), the fees and the gross gain, in the trade
currency and in euros at the ECB reference rate of the trade date. It states what the ledger
says; it is not a tax computation. The tax rules (art. 150-0 D of the CGI) are ``A_VERIFIER`` in
``config/compliance.yaml`` and nothing here applies them: no allowance, no offset of losses, no
tax and no return (R7, R16).

Amounts stay exact decimals until they are written. Each amount is then rounded to the cent
(half up), the gain being the difference of the rounded amounts, so every row adds up as printed;
the euro amounts are converted from the exact ones before rounding.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from core.finance.model import local_date
from core.finance.portfolio import EUR, RealizedGain, build_book
from core.finance.store import FinanceStore

NOTICE = (
    "règles fiscales A_VERIFIER (art. 150-0 D du CGI, à confirmer avec sa source) : aucun calcul "
    "d'impôt ni de déclaration"
)
ASSUMPTIONS = (
    "prix moyen pondéré compte par compte, frais d'achat compris, comme le livre [Hypothèse]",
    "produit net et prix de revient convertis au taux de référence BCE de la date de cession "
    "(le dernier publié avant si la BCE n'en publie pas ce jour-là) [Hypothèse]",
    "montants arrondis au centime (demi supérieur) ; plus-value = produit net − prix de revient "
    "arrondis",
)
COLUMNS = (
    "date_cession",
    "compte",
    "instrument",
    "devise",
    "quantite",
    "prix_unitaire",
    "frais",
    "produit_net",
    "pmp",
    "prix_de_revient",
    "plus_value",
    "taux_bce",
    "date_taux_bce",
    "produit_net_eur",
    "prix_de_revient_eur",
    "plus_value_brute_eur",
    "origine",
    "regles_fiscales",
)
CENT = Decimal("0.01")
PMP_DIGITS = Decimal("0.0001")


class CapitalGainsError(Exception):
    """The export cannot be made: it is refused whole, never partial (R12)."""


def default_export_dir(root: Path) -> Path:
    return root / "var" / "finance" / "exports"


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Disposal:
    """One sale, in its currency and in euros (units of the currency per euro: ``rate``)."""

    sale: RealizedGain
    rate: Decimal
    rate_date: date | None  # None for a sale in euros

    @property
    def proceeds(self) -> Decimal:
        return cents(self.sale.proceeds)

    @property
    def cost(self) -> Decimal:
        return cents(self.sale.cost)

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost

    @property
    def average_price(self) -> Decimal:
        """The weighted average price of the position just before the sale."""
        return (self.sale.cost / self.sale.quantity).quantize(PMP_DIGITS, rounding=ROUND_HALF_UP)

    @property
    def proceeds_eur(self) -> Decimal:
        return cents(self.sale.proceeds / self.rate)

    @property
    def cost_eur(self) -> Decimal:
        return cents(self.sale.cost / self.rate)

    @property
    def gain_eur(self) -> Decimal:
        return self.proceeds_eur - self.cost_eur


@dataclass(frozen=True)
class CapitalGains:
    year: int
    as_of: datetime
    until: date  # the last day the export covers: 31 December, or the reading date
    rules: str  # compliance › fiscal.regime_plus_values, as written by the user
    disposals: list[Disposal]
    warnings: list[str]

    @property
    def gain_eur(self) -> Decimal:
        return sum((d.gain_eur for d in self.disposals), Decimal(0))

    def journal_payload(self) -> dict[str, Any]:
        """Counts and identifiers only: the journal never receives an amount (R11)."""
        return {
            "year": self.year,
            "until": self.until.isoformat(),
            "sales": len(self.disposals),
            "accounts": sorted({d.sale.account for d in self.disposals}),
            "instruments": sorted({d.sale.instrument_id for d in self.disposals}),
            "warnings": len(self.warnings),
        }


def disposal(sale: RealizedGain, rate: Decimal, rate_date: date | None) -> Disposal:
    if rate <= 0:
        raise CapitalGainsError(f"{sale.where} : taux BCE non positif pour {sale.currency}")
    return Disposal(sale, rate, rate_date)


def capital_gains(
    store: FinanceStore, *, year: int, as_of: datetime, rules: str, strict: bool = False
) -> CapitalGains:
    """The sales of ``year`` known at ``as_of``, each converted at the ECB rate of its date."""
    today = local_date(as_of)
    if year > today.year:
        raise CapitalGainsError(f"l'année {year} n'a pas commencé au {today:%d/%m/%Y}")
    until = min(date(year, 12, 31), today)
    warnings: list[str] = []
    if until < date(year, 12, 31):
        warnings.append(f"année en cours : cessions connues au {until:%d/%m/%Y}")
    book = build_book(store, as_of=as_of, strict=strict, day=until)
    disposals: list[Disposal] = []
    for sale in sorted(book.realized, key=lambda s: s.trade_date):  # stable: ledger order
        if sale.trade_date.year != year:
            continue
        if sale.currency == EUR:
            disposals.append(disposal(sale, Decimal(1), None))
            continue
        known = store.fx_rates(sale.currency, as_of=as_of, end=sale.trade_date, strict=strict)
        if known.empty:
            raise CapitalGainsError(
                f"{sale.where} : aucun taux BCE connu pour {sale.currency} au "
                f"{sale.trade_date:%d/%m/%Y} (cession {sale.instrument_id}, compte "
                f"{sale.account}) : lancer `cerveau finance sync ecb`"
            )
        rate_date = known.index[-1].date()
        if rate_date != sale.trade_date:
            warnings.append(
                f"{sale.where} : pas de taux BCE {sale.currency} le {sale.trade_date:%d/%m/%Y}, "
                f"taux du {rate_date:%d/%m/%Y} retenu [Hypothèse]"
            )
        disposals.append(disposal(sale, Decimal(repr(float(known.iloc[-1]))), rate_date))
    return CapitalGains(year, as_of, until, rules, disposals, warnings)


def _number(value: Decimal) -> str:
    """A plain decimal with a comma, as the `;` files this project reads (no exponent)."""
    return f"{value:f}".replace(".", ",")


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str) -> str:
    """A text cell a spreadsheet shows as written: a leading quote keeps a formula from running
    (a file name or an account typed by the user may start with « = » or « @ »)."""
    return f"'{value}" if value.startswith(FORMULA_START) else value


def to_csv(export: CapitalGains) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for d in export.disposals:
        s = d.sale
        writer.writerow(
            (
                s.trade_date.isoformat(),
                _text(s.account),
                _text(s.instrument_id),
                _text(s.currency),
                _number(s.quantity),
                _number(s.price),
                _number(s.fees),
                _number(d.proceeds),
                _number(d.average_price),
                _number(d.cost),
                _number(d.gain),
                _number(d.rate),
                "" if d.rate_date is None else d.rate_date.isoformat(),
                _number(d.proceeds_eur),
                _number(d.cost_eur),
                _number(d.gain_eur),
                _text(s.where),
                _text(export.rules),
            )
        )
    return buffer.getvalue()


def write_export(export: CapitalGains, directory: Path) -> tuple[Path, str]:
    """Write ``plus-values-AAAA.csv`` (UTF-8 with BOM, for a spreadsheet) in ``directory``,
    replacing an earlier export of the same year; return its path and SHA-256."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"plus-values-{export.year}.csv"
    data = to_csv(export).encode("utf-8-sig")
    partial = path.with_name(f"{path.name}.partiel")
    partial.write_bytes(data)
    os.replace(partial, path)
    return path, hashlib.sha256(data).hexdigest()


__all__ = [
    "ASSUMPTIONS",
    "COLUMNS",
    "NOTICE",
    "CapitalGains",
    "CapitalGainsError",
    "Disposal",
    "capital_gains",
    "default_export_dir",
    "disposal",
    "to_csv",
    "write_export",
]
