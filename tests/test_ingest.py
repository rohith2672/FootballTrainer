from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.ingestion import ingest
from src.ingestion.ingest import (
    default_couk_seasons,
    default_fdorg_seasons,
    fdorg_match_records,
    ingest_couk,
    ingest_matches,
    ingest_teams,
)
from src.models import Match, Team
from tests._pgtest import db_session  # noqa: F401  (fixture; skips without TEST_DATABASE_URL)

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

FINISHED_PAYLOAD = {
    "matches": [
        {
            "id": 9900001,
            "utcDate": "2021-08-14T14:00:00Z",
            "status": "FINISHED",
            "homeTeam": {"name": "__TestHome FC"},
            "awayTeam": {"name": "__TestAway FC"},
            "score": {"fullTime": {"home": 2, "away": 1}},
        },
        {
            "id": 9900002,
            "utcDate": "2021-08-21T14:00:00Z",
            "status": "FINISHED",
            "homeTeam": {"name": "__TestAway FC"},
            "awayTeam": {"name": "__TestHome FC"},
            "score": {"fullTime": {"home": 0, "away": 0}},
        },
    ]
}

MIXED_PAYLOAD = {
    "matches": [
        *FINISHED_PAYLOAD["matches"],
        {
            "id": 9900099,
            "utcDate": "2021-09-01T14:00:00Z",
            "status": "SCHEDULED",
            "homeTeam": {"name": "__TestHome FC"},
            "awayTeam": {"name": "__TestAway FC"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
        {
            "id": 9900098,
            "utcDate": "2021-09-02T14:00:00Z",
            "status": "TIMED",
            "homeTeam": {"name": "__TestHome FC"},
            "awayTeam": {"name": "__TestAway FC"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
    ]
}

TEAMS_PAYLOAD = {
    "teams": [
        {"id": 99001, "name": "__TestHome FC"},
        {"id": 99002, "name": "__TestAway FC"},
    ]
}


class _Session:
    """Minimal session stand-in for tests that mock out the upsert layer."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------

def test_fdorg_records_only_finished_and_canonical_as_given():
    records = fdorg_match_records(MIXED_PAYLOAD, "PL", 2021)
    assert [r["provider_id"] for r in records] == [9900001, 9900002]
    first = records[0]
    assert first["home_team"] == "__TestHome FC"
    assert first["result"] == "H" and records[1]["result"] == "D"
    assert first["season"] == 2021 and first["league"] == "PL" and first["source"] == "fdorg"
    assert first["kickoff"] == first["date"] == datetime(2021, 8, 14, 14, 0, tzinfo=timezone.utc)
    assert str(first["match_day"]) == "2021-08-14"


def test_fdorg_records_use_regulation_score_for_shootouts():
    payload = {
        "matches": [
            {
                "id": 1, "utcDate": "2025-03-12T20:00:00Z", "status": "FINISHED",
                "homeTeam": {"name": "Arsenal FC"}, "awayTeam": {"name": "PSV"},
                "score": {
                    "duration": "PENALTY_SHOOTOUT",
                    "fullTime": {"home": 6, "away": 5},
                    "regularTime": {"home": 1, "away": 1},
                },
            }
        ]
    }
    (rec,) = fdorg_match_records(payload, "CL", 2024)
    assert (rec["home_goals"], rec["away_goals"], rec["result"]) == (1, 1, "D")


def test_default_seasons():
    today = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert default_couk_seasons(today) == list(range(2016, 2027))  # 10 completed + current (2026)
    assert default_fdorg_seasons("CL", today) == [2025, 2026]
    assert default_fdorg_seasons("PL", today) == [2026]
    spring = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert default_fdorg_seasons("PL", spring) == [2026]


def test_run_dispatch_and_default_leagues(monkeypatch):
    calls = {}
    monkeypatch.setattr(ingest, "ingest_couk", lambda *a, **k: calls.setdefault("couk", a) and {"x": 1})
    monkeypatch.setattr(ingest, "ingest_fdorg", lambda *a, **k: calls.setdefault("fdorg", a) and {"y": 1})

    summary = ingest.run(source="couk")
    assert set(summary) == {"couk"} and calls["couk"][0] == ingest.DOMESTIC_LEAGUES

    calls.clear()
    summary = ingest.run(source="all", seasons=[2024])
    assert set(summary) == {"couk", "fdorg"}
    assert calls["fdorg"][0] == ingest.ALL_LEAGUES and calls["fdorg"][1] == [2024]

    with pytest.raises(ValueError):
        ingest.run(source="nope")


def test_cli_argument_parsing(monkeypatch):
    seen = {}
    monkeypatch.setattr(ingest, "run", lambda **kw: seen.update(kw) or {})
    ingest.main(["--source", "fdorg", "--leagues", "PL", "CL", "--seasons", "2024", "2025"])
    assert seen["source"] == "fdorg"
    assert seen["leagues"] == ["PL", "CL"] and seen["seasons"] == [2024, 2025]
    assert seen["download"] is True

    seen.clear()
    ingest.main(["--no-download"])
    assert seen["source"] == "all" and seen["leagues"] is None and seen["download"] is False

    with pytest.raises(SystemExit):
        ingest.main(["--source", "bogus"])


def test_ingest_couk_parses_and_stores_without_network(tmp_path, monkeypatch):
    csv_text = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS\n"
        "E0,12/08/2023,15:00,Man United,Wolves,1,0,H,14,9\n"
        "E0,13/08/2023,16:30,Chelsea,Everton,2,2,D,,\n"
    )
    (tmp_path / "E0_2324.csv").write_text(csv_text, encoding="utf-8")

    stored = []

    def fake_upsert(session, records):
        stored.extend(records)
        return {"inserted": len(records), "updated": 0, "unchanged": 0}

    monkeypatch.setattr(ingest, "upsert_matches", fake_upsert)
    monkeypatch.setattr(ingest, "upsert_teams", lambda *a, **k: 0)
    monkeypatch.setattr(ingest.csv_history, "download_season",
                        lambda *a, **k: pytest.fail("must not download"))

    session = _Session()
    totals = ingest_couk(["PL", "CL"], [2023], raw_dir=tmp_path, download=False, session=session)

    assert totals["files"] == 1 and totals["rows"] == 2 and totals["inserted"] == 2
    assert [r["home_team"] for r in stored] == ["Manchester United FC", "Chelsea FC"]
    assert session.commits == 1 and session.rollbacks == 0


def test_ingest_couk_downloads_missing_and_survives_failures(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr(ingest, "_DOWNLOAD_PAUSE_SECONDS", 0)
    monkeypatch.setattr(ingest, "upsert_matches", lambda s, r: {"inserted": len(r), "updated": 0, "unchanged": 0})
    monkeypatch.setattr(ingest, "upsert_teams", lambda *a, **k: 0)

    downloaded = []

    def fake_download(season, div, dest):
        downloaded.append((season, div))
        if season == 2022:
            raise requests.HTTPError("404")
        (tmp_path / f"{div}_{season % 100}{(season + 1) % 100}.csv").write_text(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,01/09/2023,Arsenal,Fulham,3,0,H\n"
        )

    monkeypatch.setattr(ingest.csv_history, "download_season", fake_download)
    totals = ingest_couk(["PL"], [2022, 2023], raw_dir=tmp_path, download=True, session=_Session())
    assert downloaded == [(2022, "E0"), (2023, "E0")]
    assert totals["errors"] == 1 and totals["files"] == 1 and totals["rows"] == 1


def test_api_client_upcoming_includes_timed():
    from src.ingestion import api_client

    with patch.object(api_client, "_get", return_value={}) as mock_get:
        api_client.get_upcoming_matches("PL")
    assert mock_get.call_args.kwargs["params"]["status"] == "SCHEDULED,TIMED"


# ---------------------------------------------------------------------------
# Database tests (isolated schema in TEST_DATABASE_URL; skipped otherwise)
# ---------------------------------------------------------------------------

def test_ingest_returns_summary(db_session):
    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        result = ingest_matches(league="PL", seasons=[2021], session=db_session)

    assert result["fetched"] == 2
    assert result["inserted"] == 2
    assert result["skipped"] == 0
    assert {t.name for t in db_session.query(Team).all()} == {"__TestHome FC", "__TestAway FC"}


def test_ingest_idempotent(db_session):
    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        first = ingest_matches(league="PL", seasons=[2021], session=db_session)
        second = ingest_matches(league="PL", seasons=[2021], session=db_session)

    assert first["inserted"] == 2
    assert second["inserted"] == 0 and second["updated"] == 0
    assert second["skipped"] == 2
    assert db_session.query(Match).count() == 2


def test_ingest_skips_non_finished(db_session):
    with patch("src.ingestion.ingest.get_matches", return_value=MIXED_PAYLOAD):
        result = ingest_matches(league="PL", seasons=[2021], session=db_session)

    assert result["fetched"] == 2
    assert result["inserted"] == 2


def test_ingest_result_encoding(db_session):
    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        ingest_matches(league="PL", seasons=[2021], session=db_session)

    home_win = db_session.query(Match).filter_by(provider_id=9900001).one()
    draw = db_session.query(Match).filter_by(provider_id=9900002).one()
    assert home_win.result == "H"
    assert draw.result == "D"
    assert home_win.source == "fdorg" and home_win.match_day.isoformat() == "2021-08-14"


def test_ingest_teams(db_session):
    with patch("src.ingestion.ingest.get_teams", return_value=TEAMS_PAYLOAD):
        ingest_teams(league="PL", session=db_session)
        ingest_teams(league="PL", session=db_session)  # idempotent

    names = {t.name for t in db_session.query(Team).all()}
    assert names == {"__TestHome FC", "__TestAway FC"}


def test_couk_rows_merge_onto_fdorg_rows(db_session, tmp_path):
    fdorg_payload = {
        "matches": [
            {
                "id": 5001, "utcDate": "2023-08-12T14:00:00Z", "status": "FINISHED",
                "homeTeam": {"name": "Manchester United FC"},
                "awayTeam": {"name": "Wolverhampton Wanderers FC"},
                "score": {"fullTime": {"home": 1, "away": 0}},
            }
        ]
    }
    (tmp_path / "E0_2324.csv").write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,PSCH,PSCD,PSCA\n"
        "E0,12/08/2023,15:00,Man United,Wolves,1,0,H,14,9,1.8,3.9,4.6\n"
    )
    with patch("src.ingestion.ingest.get_matches", return_value=fdorg_payload):
        ingest_matches(league="PL", seasons=[2023], session=db_session)
    totals = ingest_couk(["PL"], [2023], raw_dir=tmp_path, download=False, session=db_session)

    assert totals["updated"] == 1 and totals["inserted"] == 0
    (m,) = db_session.query(Match).all()
    assert m.provider_id == 5001 and m.home_shots == 14 and m.odds_source == "pinnacle_close"

    again = ingest_couk(["PL"], [2023], raw_dir=tmp_path, download=False, session=db_session)
    assert again["unchanged"] == 1 and again["updated"] == 0
