"""The yearly export of the sales (plan of phase 2, F9): by hand, refusals, properties, CLI."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from core.audit import AuditJournal
from core.finance.capital_gains import (
    COLUMNS,
    NOTICE,
    CapitalGainsError,
    capital_gains,
    default_export_dir,
    disposal,
    to_csv,
    write_export,
)
from core.finance.fixtures import REFERENCE_READ_AT, reference_store
from core.finance.model import FxRate, Instrument
from core.finance.portfolio import RealizedGain, build_book, import_transactions
from core.finance.store import FinanceStore
from interfaces.cli import finance as finance_cli
from interfaces.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 1, 12, 20, tzinfo=UTC)
HEADER = "date,compte,type,identifiant,quantite,prix,devise,frais,montant,libelle"
# Worked out by hand in test_the_sales_of_a_year_by_hand.
LEDGER = (
    "2025-03-03,CTO,depot,,20000.00,,EUR,,,",
    "2025-03-03,CTO,depot,,10000.00,,USD,,,",
    "2025-03-03,PEA,depot,,5000.00,,EUR,,,",
    "2025-03-03,CTO,achat,FICT-ACME,30,100,EUR,6,,",
    "2025-03-03,PEA,achat,FICT-ACME,10,200,EUR,0,,",
    "2025-03-04,CTO,achat,FICT-ACME,10,120,EUR,4,,",
    "2025-03-05,CTO,achat,FICT-USCO,20,150,USD,5,,",
    "2025-06-10,CTO,vente,FICT-ACME,15,130,EUR,5,,",
    "2025-09-15,CTO,vente,FICT-USCO,8,170,USD,3,,",
    "2025-12-26,CTO,vente,FICT-USCO,2,160,USD,2,,",
    "2026-01-06,CTO,vente,FICT-ACME,25,90,EUR,5,,",
)
# No ECB fixing on 26 December (TARGET closed): the sale of that day takes the one of the 24th.
RATES = {date(2025, 9, 15): 1.175, date(2025, 12, 24): 1.16}
runner = CliRunner()


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def instrument(instrument_id: str, currency: str, mic: str, country: str) -> Instrument:
    return Instrument.model_validate(
        {
            "instrument_id": instrument_id,
            "valid_from": date(2020, 1, 1),
            "name": f"{instrument_id} (fictif)",
            "asset_class": "equity",
            "currency": currency,
            "mic": mic,
            "sector": "Industrie",
            "country": country,
        }
    )


def fill(
    store: FinanceStore,
    tmp_path: Path,
    *lines: str,
    rates: dict[date, float] = RATES,
    late: dict[date, datetime] | None = None,
) -> FinanceStore:
    """Instruments, USD rates published at 15:00 UTC the same day (or as ``late`` says), and
    ``lines`` imported at NOW."""
    store.add_instruments(
        [
            instrument("FICT-ACME", "EUR", "XPAR", "FR"),
            instrument("FICT-USCO", "USD", "XNYS", "US"),
        ],
        recorded_at=utc(2020, 1, 1),
    )
    if rates:
        store.ingest(
            [
                FxRate(
                    currency="USD",
                    session=day,
                    rate=rate,
                    source="fixtures",
                    published_at=(late or {}).get(day, utc(day.year, day.month, day.day, 15)),
                )
                for day, rate in rates.items()
            ],
            ingested_at=NOW,
        )
    path = tmp_path / "operations.csv"
    path.write_text("\n".join((HEADER, *lines)) + "\n", encoding="utf-8")
    import_transactions(store, path, "cerveau", imported_at=NOW)
    return store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FinanceStore]:
    s = fill(FinanceStore.memory(), tmp_path, *LEDGER)
    yield s
    s.close()


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


# By hand ----------------------------------------------------------------------------------------


def test_the_sales_of_a_year_by_hand(store: FinanceStore) -> None:
    export = capital_gains(store, year=2025, as_of=NOW, rules="A_VERIFIER")
    assert export.until == date(2025, 12, 31)
    acme, usco, late = export.disposals
    # ACME on CTO: 30 at 100 + 6 fees, 10 at 120 + 4 fees: 4 210 for 40, i.e. 105,25 a share.
    # The PEA buys at 200 do not move it: the average stays account by account.
    assert (acme.sale.account, acme.sale.instrument_id) == ("CTO", "FICT-ACME")
    assert acme.average_price == Decimal("105.2500")
    assert (acme.proceeds, acme.cost, acme.gain) == (
        Decimal("1945.00"),  # 15 × 130 − 5
        Decimal("1578.75"),  # 4 210 × 15 / 40
        Decimal("366.25"),
    )
    assert (acme.rate, acme.rate_date) == (Decimal(1), None)
    assert (acme.proceeds_eur, acme.cost_eur, acme.gain_eur) == (
        Decimal("1945.00"),
        Decimal("1578.75"),
        Decimal("366.25"),
    )
    # USCO: 20 at 150 + 5 fees, 3 005 USD; 8 sold at 170 − 3 at 1,175 USD for one euro.
    assert usco.average_price == Decimal("150.2500")
    assert (usco.proceeds, usco.cost, usco.gain) == (
        Decimal("1357.00"),
        Decimal("1202.00"),
        Decimal("155.00"),
    )
    assert (usco.rate, usco.rate_date) == (Decimal("1.175"), date(2025, 9, 15))
    assert (usco.proceeds_eur, usco.cost_eur, usco.gain_eur) == (
        Decimal("1154.89"),  # 1 357 / 1,175 = 1 154,8936…
        Decimal("1022.98"),  # 1 202 / 1,175 = 1 022,9787…
        Decimal("131.91"),
    )
    # 2 more on 26 December: 1 803 USD left for 12, 300,5 removed; the rate of the 24th.
    assert (late.proceeds, late.cost, late.gain) == (
        Decimal("318.00"),
        Decimal("300.50"),
        Decimal("17.50"),
    )
    assert (late.rate, late.rate_date) == (Decimal("1.16"), date(2025, 12, 24))
    assert (late.proceeds_eur, late.cost_eur, late.gain_eur) == (
        Decimal("274.14"),  # 318 / 1,16 = 274,1379…
        Decimal("259.05"),  # 300,5 / 1,16 = 259,0517…
        Decimal("15.09"),
    )
    assert export.gain_eur == Decimal("513.25")
    assert export.warnings == [
        "operations.csv, ligne 11 : pas de taux BCE USD le 26/12/2025, taux du 24/12/2025 "
        "retenu [Hypothèse]"
    ]


def test_the_csv_by_hand(store: FinanceStore) -> None:
    text = to_csv(capital_gains(store, year=2025, as_of=NOW, rules="A_VERIFIER"))
    header, acme, usco, late = rows(text)
    assert tuple(header) == COLUMNS
    assert usco == [
        "2025-09-15",
        "CTO",
        "FICT-USCO",
        "USD",
        "8",
        "170",
        "3",
        "1357,00",
        "150,2500",
        "1202,00",
        "155,00",
        "1,175",
        "2025-09-15",
        "1154,89",
        "1022,98",
        "131,91",
        "operations.csv, ligne 10",
        "A_VERIFIER",
    ]
    assert acme[11:13] == ["1", ""]
    assert late[12] == "2025-12-24"
    assert text.endswith("\r\n") and text.count("\r\n") == 4


def test_the_years_partition_the_sales(store: FinanceStore) -> None:
    book = build_book(store, as_of=NOW)
    counts = [
        len(capital_gains(store, year=year, as_of=NOW, rules="A_VERIFIER").disposals)
        for year in (2024, 2025, 2026)
    ]
    assert counts == [0, 3, 1] and sum(counts) == len(book.realized)


def test_the_year_in_progress_is_flagged(store: FinanceStore) -> None:
    export = capital_gains(store, year=2026, as_of=NOW, rules="A_VERIFIER")
    assert export.until == date(2026, 1, 12)
    (sale,) = export.disposals
    assert (sale.proceeds, sale.cost, sale.gain) == (
        Decimal("2245.00"),  # 25 × 90 − 5
        Decimal("2631.25"),  # what is left of 4 210 after 1 578,75
        Decimal("-386.25"),
    )
    assert export.warnings == ["année en cours : cessions connues au 12/01/2026"]


def test_a_year_without_a_sale_gives_the_header_only(store: FinanceStore) -> None:
    export = capital_gains(store, year=2024, as_of=NOW, rules="A_VERIFIER")
    assert export.disposals == [] and export.gain_eur == 0
    assert rows(to_csv(export)) == [list(COLUMNS)]


def test_the_reference_portfolio_sold_delta_in_2025(tmp_path: Path) -> None:
    path = reference_store(tmp_path / "finance.db")
    with FinanceStore.open(path, read_only=True) as db:
        export = capital_gains(db, year=2025, as_of=REFERENCE_READ_AT, rules="A_VERIFIER")
    (sale,) = export.disposals
    assert (sale.sale.account, sale.sale.instrument_id) == ("PEA-FICTIF", "FICT-DELTA")
    assert (sale.average_price, sale.proceeds, sale.cost, sale.gain_eur) == (
        Decimal("38.7545"),  # 1 550,18 / 40
        Decimal("1039.10"),  # 40 × 26,10 − 4,90
        Decimal("1550.18"),
        Decimal("-511.08"),
    )


# Refusals ---------------------------------------------------------------------------------------


def test_a_year_not_yet_begun_is_refused(store: FinanceStore) -> None:
    with pytest.raises(CapitalGainsError, match="l'année 2027 n'a pas commencé au 12/01/2026"):
        capital_gains(store, year=2027, as_of=NOW, rules="A_VERIFIER")


def test_an_unknown_rate_refuses_the_whole_export(tmp_path: Path) -> None:
    with fill(FinanceStore.memory(), tmp_path, *LEDGER, rates={}) as s:
        with pytest.raises(CapitalGainsError) as refused:
            capital_gains(s, year=2025, as_of=NOW, rules="A_VERIFIER")
        # The euro sales alone would have passed: the export is refused whole (R12).
        assert capital_gains(s, year=2026, as_of=NOW, rules="A_VERIFIER").disposals
    assert str(refused.value) == (
        "operations.csv, ligne 10 : aucun taux BCE connu pour USD au 15/09/2025 (cession "
        "FICT-USCO, compte CTO) : lancer `cerveau finance sync ecb`"
    )


def test_a_rate_published_after_the_reading_is_not_used(tmp_path: Path) -> None:
    """R10: read on 16 September, the sale of the 15th is known but not yet its fixing."""
    rates = {date(2025, 9, 12): 1.17, **RATES}
    late = {date(2025, 9, 15): utc(2025, 9, 17, 15)}
    with fill(FinanceStore.memory(), tmp_path, *LEDGER, rates=rates, late=late) as s:
        before = capital_gains(s, year=2025, as_of=utc(2025, 9, 16, 12), rules="A_VERIFIER")
        after = capital_gains(s, year=2025, as_of=NOW, rules="A_VERIFIER")
    sale = before.disposals[-1]
    assert (sale.sale.trade_date, sale.rate, sale.rate_date) == (
        date(2025, 9, 15),
        Decimal("1.17"),
        date(2025, 9, 12),
    )
    assert before.until == date(2025, 9, 16)
    assert "taux du 12/09/2025 retenu [Hypothèse]" in before.warnings[-1]
    assert after.disposals[1].rate == Decimal("1.175")


def test_a_rate_that_is_not_positive_is_refused() -> None:
    with pytest.raises(CapitalGainsError, match="taux BCE non positif pour USD"):
        disposal(sale(Decimal(1), Decimal(1), Decimal(1), "USD"), Decimal(0), date(2025, 1, 2))


# Properties -------------------------------------------------------------------------------------


def sale(quantity: Decimal, proceeds: Decimal, cost: Decimal, currency: str) -> RealizedGain:
    return RealizedGain(
        account="CTO",
        instrument_id="FICT-USCO",
        trade_date=date(2025, 9, 15),
        currency=currency,
        quantity=quantity,
        price=Decimal(1),
        fees=Decimal(0),
        proceeds=proceeds,
        cost=cost,
        where="operations.csv, ligne 2",
    )


amounts = st.decimals(min_value=Decimal(0), max_value=Decimal(10**9), places=6)


@settings(max_examples=300, deadline=None)
@given(
    quantity=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal(10**6), places=4),
    proceeds=amounts,
    cost=amounts,
    rate=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal(10**5), places=4),
    euro=st.booleans(),
)
def test_every_row_adds_up_and_stays_within_half_a_cent(
    quantity: Decimal, proceeds: Decimal, cost: Decimal, rate: Decimal, euro: bool
) -> None:
    rate = Decimal(1) if euro else rate
    d = disposal(sale(quantity, proceeds, cost, "EUR" if euro else "USD"), rate, None)
    half = Decimal("0.005")
    assert d.gain == d.proceeds - d.cost and d.gain_eur == d.proceeds_eur - d.cost_eur
    assert abs(d.proceeds - proceeds) <= half and abs(d.cost - cost) <= half
    assert abs(d.proceeds_eur - proceeds / rate) <= half
    assert abs(d.cost_eur - cost / rate) <= half
    assert abs(d.gain_eur - (proceeds - cost) / rate) <= 2 * half
    assert abs(d.average_price * quantity - cost) <= Decimal("0.00005") * quantity
    if euro:
        assert (d.proceeds_eur, d.cost_eur, d.gain_eur) == (d.proceeds, d.cost, d.gain)


# Command line -----------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CERVEAU_HOME in a temporary folder, its store filled with LEDGER."""
    monkeypatch.setattr(finance_cli, "now", lambda: NOW)
    root = tmp_path / "home"
    monkeypatch.setenv("CERVEAU_HOME", str(root))
    with FinanceStore.open(root / "var" / "finance" / "finance.db") as s:
        fill(s, tmp_path, *LEDGER)
    return root


def plus_values(home: Path, *args: str) -> Any:
    options = ["--config-dir", str(REPO_ROOT / "config")]
    return runner.invoke(app, ["finance", "plus-values", *args, *options])


def files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def journal_entries(home: Path) -> list[tuple[str, dict[str, Any], str]]:
    journal = home / "var" / "audit" / "journal.jsonl"
    audit = AuditJournal(journal)
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [
        (e["event"], audit.read_payload(e["payload_ref"]), json.dumps(e, ensure_ascii=False))
        for e in lines
    ]


def test_cli_writes_the_export_under_var_finance_exports_and_nowhere_else(home: Path) -> None:
    db = home / "var" / "finance" / "finance.db"
    before, digest = files(home), hashlib.sha256(db.read_bytes()).hexdigest()
    result = plus_values(home, "--annee", "2025")
    assert result.exit_code == 0, result.output
    export = default_export_dir(home) / "plus-values-2025.csv"
    written = files(home) - before
    assert {p for p in written if p.parts[:2] != ("var", "audit")} == {export.relative_to(home)}
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest  # read only
    data = export.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert len(rows(data.decode("utf-8-sig"))) == 4
    assert "plus-values-2025.csv : 3 cession(s) du 01/01/2025 au 31/12/2025" in result.output
    assert "Somme des plus-values brutes : 513,25 EUR" in result.output
    assert "taux du 24/12/2025 retenu [Hypothèse]" in result.output
    assert f"Attention : {NOTICE}." in result.output
    ((event, payload, raw),) = journal_entries(home)
    assert event == "TOOL_CALL"
    assert payload == {
        "command": "finance plus-values",
        "year": 2025,
        "until": "2025-12-31",
        "sales": 3,
        "accounts": ["CTO"],
        "instruments": ["FICT-ACME", "FICT-USCO"],
        "warnings": 1,
        "file": "plus-values-2025.csv",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    for amount in ("366", "513", "1357", "1945"):  # the journal never receives an amount
        assert amount not in json.dumps(payload) and amount not in raw


def test_cli_replaces_the_export_of_the_same_year(home: Path) -> None:
    assert plus_values(home, "--annee", "2026").exit_code == 0
    second = plus_values(home, "--annee", "2026")
    assert second.exit_code == 0, second.output
    assert sorted(p.name for p in default_export_dir(home).iterdir()) == ["plus-values-2026.csv"]
    assert "Avertissement : année en cours : cessions connues au 12/01/2026." in second.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--annee", "2027"], "l'année 2027 n'a pas commencé au 12/01/2026"),
        (["--annee", "2025", "--store", "absente.db"], "base finance absente (absente.db)"),
    ],
)
def test_cli_refusals_write_nothing_and_are_journaled(
    home: Path, args: list[str], message: str
) -> None:
    result = plus_values(home, *args)
    assert result.exit_code == 1
    assert message in result.output and "Aucun export écrit" in result.output
    assert not default_export_dir(home).exists()
    ((event, payload, _),) = journal_entries(home)
    assert event == "ERROR" and message in payload["error"]


def test_cli_rejects_a_year_out_of_range(home: Path) -> None:
    result = plus_values(home, "--annee", "0")
    assert result.exit_code == 2
    assert not default_export_dir(home).exists()


def test_write_export_leaves_no_partial_file(store: FinanceStore, tmp_path: Path) -> None:
    export = capital_gains(store, year=2025, as_of=NOW, rules="A_VERIFIER")
    path, digest = write_export(export, tmp_path / "exports")
    assert [p.name for p in (tmp_path / "exports").iterdir()] == ["plus-values-2025.csv"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
