"""Portfolio files read into the CERVEAU format: transactions and position statements (ADR-018).

A broker's export is external content (R5), read with the rules of ADR-017: bounded size, known
columns, every field validated, an error that names the line without echoing the value, and the
file read whole or refused whole. Amounts stay exact decimals from the file's text.

- transactions: ``date, compte, type, identifiant, quantite, prix, devise, frais`` and optionally
  ``montant, libelle``; the ``identifiant``, ``prix`` and ``frais`` columns may be empty where
  the type has nothing to put in them;
- statement: ``date, compte, nature, identifiant, quantite``, one date per file.

Only the ``cerveau`` format exists: each broker gets its adapter once Lucas names it (D4) and
it is tested on a real, anonymised export.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from core.finance.model import StatementLine, Transaction
from core.finance.providers.base import ProviderError, Reference
from core.finance.providers.csv_files import CsvLayout, CsvTable, _Rows, parse_date, read_table

TRANSACTIONS = CsvLayout(
    ("date", "compte", "type", "identifiant", "quantite", "prix", "devise", "frais"),
    ("montant", "libelle"),
)
STATEMENT = CsvLayout(("date", "compte", "nature", "identifiant", "quantite"))
TRANSACTION_KINDS = {
    "achat": "buy",
    "vente": "sell",
    "dividende": "dividend",
    "frais": "fee",
    "depot": "deposit",
    "dépôt": "deposit",
    "retrait": "withdrawal",
    "change": "fx",
}
NATURES = {"titre": "security", "especes": "cash", "espèces": "cash"}
# Plain decimals: no exponent, no thousands separator, 15 digits before the point and 10 after.
_DECIMAL = re.compile(r"^-?\d{1,15}(\.\d{1,10})?$")
_INSTRUMENT_KINDS = ("buy", "sell", "dividend")

TransactionReader = Callable[
    [Path, Reference, date], tuple[CsvTable, list[tuple[int, Transaction]]]
]


def parse_decimal(text: str, decimal_comma: bool, *, signed: bool = False) -> Decimal:
    if decimal_comma:
        text = text.replace(",", ".")
    elif "," in text:
        raise ValueError("virgule décimale : séparer les colonnes par « ; »")
    if not _DECIMAL.match(text) or (text.startswith("-") and not signed):
        raise ValueError(
            "nombre attendu : chiffres et séparateur décimal, sans exposant, "
            "15 chiffres avant la virgule et 10 après au plus"
        )
    return Decimal(text)


def _not_empty(table: CsvTable) -> None:
    if not table.rows:
        raise ProviderError(f"{table.name} : aucune ligne")


def read_cerveau(
    path: Path, reference: Reference, today: date
) -> tuple[CsvTable, list[tuple[int, Transaction]]]:
    """Transactions in file order; ``today`` is the Paris date of the import."""
    table = read_table(path, TRANSACTIONS)
    _not_empty(table)
    rows = _Rows(table)

    def number(fields: dict[str, str], column: str) -> Decimal | None:
        text = fields.get(column)
        return None if text is None else parse_decimal(text, table.decimal_comma)

    def convert(fields: dict[str, str]) -> Transaction:
        kind = fields["type"].lower()
        if kind not in TRANSACTION_KINDS:
            raise ValueError(f"type attendu : {', '.join(TRANSACTION_KINDS)}")
        trade_date = parse_date(fields["date"])
        if trade_date > today:
            raise ValueError("opération datée dans le futur")
        transaction = Transaction.model_validate(
            {
                "trade_date": trade_date,
                "account": fields["compte"],
                "kind": TRANSACTION_KINDS[kind],
                "asset": fields.get("identifiant"),
                "quantity": number(fields, "quantite"),
                "price": number(fields, "prix"),
                "currency": fields["devise"],
                "fees": number(fields, "frais") or Decimal(0),
                "amount": number(fields, "montant"),
                "label": fields.get("libelle"),
            }
        )
        # The model requires an instrument for these kinds; a fee may name one.
        if transaction.asset is not None and transaction.kind in (*_INSTRUMENT_KINDS, "fee"):
            instrument = reference(transaction.asset, trade_date)
            if instrument is None:
                raise ValueError("instrument absent du référentiel à cette date")
            if transaction.kind != "fee" and instrument.currency != transaction.currency:
                raise ValueError("devise autre que celle de cet instrument au référentiel")
        return transaction

    return table, list(rows.build(convert))


def read_statement(
    path: Path, reference: Reference, today: date
) -> tuple[CsvTable, list[tuple[int, StatementLine]]]:
    """A broker's statement of positions on one date, in the CERVEAU format."""
    table = read_table(path, STATEMENT)
    _not_empty(table)
    rows = _Rows(table)

    def convert(fields: dict[str, str]) -> StatementLine:
        nature = fields["nature"].lower()
        if nature not in NATURES:
            raise ValueError(f"nature attendue : {', '.join(NATURES)}")
        statement_date = parse_date(fields["date"])
        if statement_date > today:
            raise ValueError("relevé daté dans le futur")
        line = StatementLine.model_validate(
            {
                "statement_date": statement_date,
                "account": fields["compte"],
                "nature": NATURES[nature],
                "asset": fields["identifiant"],
                "quantity": parse_decimal(fields["quantite"], table.decimal_comma, signed=True),
            }
        )
        if line.nature == "security" and reference(line.asset, statement_date) is None:
            raise ValueError("instrument absent du référentiel à la date du relevé")
        return line

    built = list(rows.build(convert))
    first_date = built[0][1].statement_date
    seen: set[tuple[str, str, str]] = set()
    for number, line in built:
        if line.statement_date != first_date:
            raise rows.error(number, "un relevé porte une seule date")
        key = (line.account, line.nature, line.asset)
        if key in seen:
            raise rows.error(number, "deux lignes pour la même position")
        seen.add(key)
    return table, built


FORMATS: dict[str, TransactionReader] = {"cerveau": read_cerveau}
