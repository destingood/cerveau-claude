"""`cerveau finance sync`: one fetch, one transaction, one journal entry (ADR-012, ADR-017, R11)."""

from __future__ import annotations

import itertools
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from core.audit import AuditJournal
from core.config.loader import DataQuality
from core.finance.model import FxRate, Instrument, PriceRow, RateObservation
from core.finance.providers import StaticProvider
from core.finance.store import FinanceStore
from core.finance.sync import (
    default_start,
    import_instruments,
    reference_currencies,
    sync,
)
from interfaces.cli import finance as finance_cli
from interfaces.cli.main import app

runner = CliRunner()
FETCHED = datetime(2026, 10, 20, 12, tzinfo=UTC)
RECORDED = datetime(2026, 1, 2, tzinfo=UTC)
SETTINGS = DataQuality(
    max_staleness_sessions=1,
    min_quality_score_above_N1=0.9,
    outlier_robust_z=3.5,
    max_unexplained_move=0.3,
)
ACME = Instrument(
    instrument_id="FICT-ACME",
    valid_from=date(2020, 1, 1),
    name="Acme fictive",
    asset_class="equity",
    currency="EUR",
    mic="XPAR",
    sector="Industrie",
    country="FR",
)
GLOBEX = ACME.model_copy(
    update={"instrument_id": "FICT-GLOBEX", "currency": "USD", "mic": "XNYS", "country": "US"}
)


def ticking(start: datetime = FETCHED) -> Callable[[], datetime]:
    moments = (start + timedelta(seconds=n) for n in itertools.count())
    return lambda: next(moments)


def close(session: date, value: float, instrument: Instrument = ACME) -> PriceRow:
    return PriceRow(
        instrument_id=instrument.instrument_id,
        session=session,
        close=value,
        currency=instrument.currency,
        source="csv",
        published_at=datetime.combine(session, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=18),
    )


def store_with(*instruments: Instrument) -> FinanceStore:
    store = FinanceStore.memory()
    store.add_instruments(instruments or (ACME,), recorded_at=RECORDED)
    return store


def run(store: FinanceStore, *records: Any, start: datetime = FETCHED) -> Any:
    return sync(
        store,
        StaticProvider(list(records), source="csv"),
        clock=ticking(start),
        quality=SETTINGS,
        window_sessions=250,
    )


# --- core.finance.sync ------------------------------------------------------------------------


def test_a_sync_ingests_once_and_scores_the_instruments_it_touched() -> None:
    store = store_with()
    result = run(store, close(date(2026, 10, 15), 101), close(date(2026, 10, 16), 102))
    assert (result.received, result.report.inserted, result.redated) == (2, 2, 0)
    assert result.fetched_at == FETCHED and result.ingested_at > result.fetched_at
    [quality] = result.quality
    assert quality.instrument_id == "FICT-ACME" and quality.strict
    assert quality.as_of == result.ingested_at
    assert len(store.quality_history("FICT-ACME")) == 1
    payload = result.journal_payload()
    assert payload["inserted"] == 2 and set(payload["quality"]) == {"FICT-ACME"}
    assert "102" not in json.dumps(payload)  # counts and scores, never the values


def test_a_revision_is_dated_at_the_fetch_that_saw_it() -> None:
    store = store_with()
    first = close(date(2026, 10, 16), 102)
    run(store, close(date(2026, 10, 15), 101), first)
    later = FETCHED + timedelta(days=1)
    result = run(store, close(date(2026, 10, 15), 101), close(date(2026, 10, 16), 103), start=later)
    assert (result.report.revised, result.report.unchanged, result.redated) == (1, 1, 1)
    *_, revised = store.revisions(PriceRow, {"instrument_id": "FICT-ACME"})
    assert revised.record.close == 103 and revised.revision == 2
    assert revised.record.published_at == later  # not the close time it claims
    # Before the second fetch, the store still answers with the first value (R10).
    assert store.closes("FICT-ACME", as_of=later - timedelta(seconds=1)).iloc[-1] == 102


def test_an_instrument_gone_from_the_reference_is_reported_not_scored() -> None:
    delisted = ACME.model_copy(update={"valid_to": date(2026, 10, 17)})
    store = store_with(delisted)
    result = run(store, close(date(2026, 10, 16), 102))
    assert result.report.inserted == 1 and result.quality == []
    assert "instrument inconnu" in result.not_assessed["FICT-ACME"]


def test_rates_are_ingested_without_a_quality_score() -> None:
    store = store_with()
    fx = FxRate(
        currency="USD",
        session=date(2026, 10, 16),
        rate=1.165,
        source="ecb",
        published_at=datetime(2026, 10, 16, 15, tzinfo=UTC),
    )
    result = run(store, fx)
    assert result.report.inserted == 1 and result.quality == [] and result.not_assessed == {}


def test_instruments_are_imported_in_one_transaction(tmp_path: Path) -> None:
    path = tmp_path / "referentiel.csv"
    path.write_text(
        "identifiant;nom;classe;devise;place;secteur;pays;debut\n"
        "FICT-ACME;Acme fictive;action;EUR;XPAR;Industrie;FR;01/01/2020\n"
        "FICT-GLOBEX;Globex fictive;action;USD;XNYS;Industrie;US;01/01/2020\n",
        encoding="utf-8",
    )
    store = FinanceStore.memory()
    first = import_instruments(store, path, recorded_at=RECORDED)
    again = import_instruments(store, path, recorded_at=FETCHED)
    assert (first.report.inserted, again.report.inserted, again.report.unchanged) == (2, 0, 2)
    assert first.parameters["kind"] == "referentiel" and len(first.parameters["sha256"]) == 64
    assert reference_currencies(store.instruments(as_of=FETCHED)) == ["USD"]


def test_the_default_start_goes_back_from_the_oldest_last_session() -> None:
    store = store_with()
    run(
        store,
        FxRate(
            currency="USD",
            session=date(2026, 10, 16),
            rate=1.165,
            source="ecb",
            published_at=datetime(2026, 10, 16, 15, tzinfo=UTC),
        ),
        RateObservation(
            series_id="estr",
            session=date(2026, 10, 15),
            value_pct=1.928,
            source="ecb",
            published_at=datetime(2026, 10, 16, 7, tzinfo=UTC),
        ),
    )
    series = {"EURUSD": partial(store.fx_rates, "USD"), "estr": partial(store.rates, "estr")}
    assert default_start(series, FETCHED + timedelta(hours=1)) == date(2026, 10, 1)
    with pytest.raises(ValueError, match="EURGBP : rien en base"):
        default_start({"EURGBP": partial(store.fx_rates, "GBP")}, FETCHED)


# --- CLI --------------------------------------------------------------------------------------

EXR = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-15,1.1623\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-10-16,1.1650\n"
    "EXR.D.GBP.EUR.SP00.A,D,GBP,EUR,SP00,A,2026-10-16,0.8720\n"
)
EST = "KEY,TIME_PERIOD,OBS_VALUE\nEST.B.EU000A2X2A25.WT,2026-10-16,1.931\n"


@pytest.fixture
def cli(tmp_path: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    monkeypatch.setattr(finance_cli, "now", lambda: FETCHED)
    store, journal = tmp_path / "finance.db", tmp_path / "audit" / "journal.jsonl"

    def invoke(*args: str) -> Any:
        options = ["--store", str(store), "--journal", str(journal), "--config-dir"]
        return runner.invoke(app, ["finance", "sync", *args, *options, str(config_dir)])

    invoke.store, invoke.journal = store, journal  # type: ignore[attr-defined]
    return invoke


def entries(journal: Path) -> list[tuple[str, dict[str, Any]]]:
    audit = AuditJournal(journal)
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [(e["event"], audit.read_payload(e["payload_ref"])) for e in lines]


def serve_ecb(
    monkeypatch: pytest.MonkeyPatch, seen: list[httpx.Request], status: int = 200
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, text=EXR if "/EXR/" in request.url.path else EST)

    monkeypatch.setattr(finance_cli, "ecb_transport", lambda: httpx.MockTransport(handler))


def write_reference(tmp_path: Path) -> Path:
    path = tmp_path / "referentiel.csv"
    path.write_text(
        "identifiant,nom,classe,devise,place,secteur,pays,debut\n"
        "FICT-ACME,Acme fictive,action,EUR,XPAR,Industrie,FR,2020-01-01\n"
        "FICT-GLOBEX,Globex fictive,action,USD,XNYS,Industrie,US,2020-01-01\n",
        encoding="utf-8",
    )
    return path


def test_cli_imports_the_reference_then_closes_and_journals_each(cli: Any, tmp_path: Path) -> None:
    imported = cli("instruments", str(write_reference(tmp_path)))
    assert imported.exit_code == 0, imported.output
    assert "csv : 2 enregistrement(s) reçu(s) — 2 nouveau(x)" in imported.output
    prices = tmp_path / "cours.csv"
    prices.write_text(
        "date,identifiant,cloture,devise\n"
        "2026-10-15,FICT-ACME,101.5,EUR\n2026-10-16,FICT-ACME,102,EUR\n",
        encoding="utf-8",
    )
    synced = cli("prices", str(prices))
    assert synced.exit_code == 0, synced.output
    assert "Qualité des séries (score strict, ADR-016) :" in synced.output
    assert "  · FICT-ACME : " in synced.output
    assert "Journalisé : requête finance-sync-" in synced.output
    events = entries(cli.journal)
    assert [(e, p["command"]) for e, p in events] == [
        ("TOOL_CALL", "finance sync instruments"),
        ("TOOL_CALL", "finance sync prices"),
    ]
    assert events[1][1]["inserted"] == 2 and events[1][1]["parameters"]["file"] == "cours.csv"


def test_cli_refuses_a_whole_file_and_journals_why(cli: Any, tmp_path: Path) -> None:
    cli("instruments", str(write_reference(tmp_path)))
    prices = tmp_path / "cours.csv"
    prices.write_text(
        "date,identifiant,cloture,devise\n2026-10-15,FICT-ACME,101,EUR\n2026-10-16,FICT-X,1,EUR\n",
        encoding="utf-8",
    )
    refused = cli("prices", str(prices))
    assert refused.exit_code == 1
    assert "Refus : cours.csv, ligne 3 : instrument absent" in refused.output
    assert "Rien n'est enregistré" in refused.output
    event, payload = entries(cli.journal)[-1]
    assert event == "ERROR" and "ligne 3" in payload["error"]
    with FinanceStore.open(cli.store) as store:
        assert store.closes("FICT-ACME", as_of=FETCHED).empty


def test_cli_syncs_the_ecb_for_the_reference_currencies(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []
    serve_ecb(monkeypatch, seen)
    cli("instruments", str(write_reference(tmp_path)))
    first = cli("ecb", "--start", "2026-10-01", "--currency", "gbp")
    assert first.exit_code == 0, first.output
    assert "ecb : 4 enregistrement(s) reçu(s) — 4 nouveau(x)" in first.output
    assert seen[0].url.path.endswith("/data/EXR/D.GBP+USD.EUR.SP00.A")
    assert seen[0].url.params["endPeriod"] == "2026-10-20"
    # Without --start, it goes back two weeks from the last session stored.
    again = cli("ecb", "--currency", "GBP")
    assert again.exit_code == 0, again.output
    assert "0 nouveau(x), 0 révisé(s), 4 inchangé(s)" in again.output
    assert seen[-1].url.params["startPeriod"] == "2026-10-02"
    _, payload = entries(cli.journal)[-1]
    assert payload["source"] == "ecb" and payload["parameters"]["currencies"] == ["GBP", "USD"]


def test_cli_asks_for_a_start_on_an_empty_store(cli: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    serve_ecb(monkeypatch, seen)
    refused = cli("ecb")
    assert refused.exit_code == 1 and "estr : rien en base, préciser --start" in refused.output
    assert seen == []


def test_cli_journals_an_ecb_failure_and_stores_nothing(
    cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve_ecb(monkeypatch, [], status=503)
    refused = cli("ecb", "--start", "2026-10-01")
    assert refused.exit_code == 1 and "réponse HTTP 503" in refused.output
    event, payload = entries(cli.journal)[-1]
    assert (event, payload["command"]) == ("ERROR", "finance sync ecb")
    with FinanceStore.open(cli.store) as store:
        assert store.rates("estr", as_of=FETCHED).empty


def test_cli_does_not_reach_a_disabled_source(
    cli: Any, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = config_dir / "data_sources.yaml"
    text = sources.read_text(encoding="utf-8")
    assert text.count("enabled: true                     # D2") == 1
    sources.write_text(
        text.replace("enabled: true                     # D2", "enabled: false"), encoding="utf-8"
    )
    seen: list[httpx.Request] = []
    serve_ecb(monkeypatch, seen)
    blocked = cli("ecb", "--start", "2026-10-01")
    assert blocked.exit_code == 2 and "Bloqué (R7)" in blocked.output
    assert seen == [] and not cli.journal.exists()


def test_cli_refuses_a_store_of_a_newer_schema_and_journals_it(cli: Any, tmp_path: Path) -> None:
    FinanceStore.open(cli.store).close()
    newer = sqlite3.connect(cli.store)
    newer.execute("INSERT INTO schema_version VALUES (99, '2026-10-18T12:00:00Z')")
    newer.commit()
    newer.close()
    path = tmp_path / "cours.csv"
    path.write_text("date,identifiant,cloture,devise\n", encoding="utf-8")
    refused = cli("prices", str(path))
    assert refused.exit_code == 1 and "Refus : base au schéma 99" in refused.output
    [(event, payload)] = entries(cli.journal)
    assert (event, payload["command"]) == ("ERROR", "finance sync prices")
