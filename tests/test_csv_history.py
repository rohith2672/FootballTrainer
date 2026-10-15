import csv
import io
from datetime import date, datetime, timezone

import pytest
import requests
import responses

from src.ingestion.csv_history import (
    COUK_DIVISIONS,
    couk_url,
    download_season,
    parse_couk_csv,
    select_odds,
)

BASE_COLS = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]


def make_csv(rows, columns, *, encoding="utf-8", bom=False, trailing=False) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns + ([""] * 2 if trailing else []))
    for r in rows:
        writer.writerow([r.get(c, "") for c in columns] + ([""] * 2 if trailing else []))
    if trailing:
        buf.write(",".join([""] * (len(columns) + 2)) + "\n")
        buf.write("\n")
    data = buf.getvalue().encode(encoding)
    return (b"\xef\xbb\xbf" + data) if bom else data


def write(tmp_path, data: bytes, name="E0_2324.csv"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def row(**kw):
    base = {"Div": "E0", "Date": "12/08/2023", "Time": "15:00", "HomeTeam": "Man United",
            "AwayTeam": "Wolves", "FTHG": "1", "FTAG": "0", "FTR": "H"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------

def test_divisions_and_url():
    assert COUK_DIVISIONS == {"E0": "PL", "SP1": "PD", "I1": "SA", "D1": "BL1", "F1": "FL1"}
    assert couk_url(2023, "E0") == "https://www.football-data.co.uk/mmz4281/2324/E0.csv"
    assert couk_url(1999, "SP1").endswith("/9900/SP1.csv")


def test_basic_parse_with_time_converts_uk_to_utc(tmp_path):
    data = make_csv(
        [
            row(),  # BST (UTC+1): 15:00 -> 14:00 UTC
            row(Date="14/01/2024", Time="17:30", HomeTeam="Arsenal", AwayTeam="Man City",
                FTHG="0", FTAG="0", FTR="D"),  # GMT
        ],
        BASE_COLS,
    )
    recs = parse_couk_csv(write(tmp_path, data), "E0", 2023)
    assert len(recs) == 2
    first, second = recs
    assert first["league"] == "PL" and first["season"] == 2023 and first["source"] == "couk"
    assert first["home_team"] == "Manchester United FC"
    assert first["away_team"] == "Wolverhampton Wanderers FC"
    assert first["date"] == datetime(2023, 8, 12, 14, 0, tzinfo=timezone.utc)
    assert first["kickoff"] == first["date"]
    assert first["match_day"] == date(2023, 8, 12)
    assert (first["home_goals"], first["away_goals"], first["result"]) == (1, 0, "H")
    assert second["date"] == datetime(2024, 1, 14, 17, 30, tzinfo=timezone.utc)
    assert second["result"] == "D"
    assert first["provider_id"] is None


def test_two_and_four_digit_years_and_missing_time_column(tmp_path):
    cols = [c for c in BASE_COLS if c != "Time"]
    data = make_csv(
        [row(Date="12/08/23"), row(Date="13/08/2023", HomeTeam="Chelsea", AwayTeam="Everton")],
        cols,
    )
    recs = parse_couk_csv(write(tmp_path, data), "E0", 2023)
    assert [r["match_day"] for r in recs] == [date(2023, 8, 12), date(2023, 8, 13)]
    assert all(r["kickoff"] is None for r in recs)
    assert recs[0]["date"] == datetime(2023, 8, 12, tzinfo=timezone.utc)


def test_empty_time_cell_means_no_kickoff(tmp_path):
    recs = parse_couk_csv(write(tmp_path, make_csv([row(Time="")], BASE_COLS)), "E0", 2023)
    assert recs[0]["kickoff"] is None


def test_bom_latin1_and_trailing_junk(tmp_path):
    bom = parse_couk_csv(
        write(tmp_path, make_csv([row()], BASE_COLS, bom=True, trailing=True), "bom.csv"),
        "E0", 2023,
    )
    assert len(bom) == 1 and bom[0]["home_team"] == "Manchester United FC"

    data = make_csv(
        [row(Div="D1", HomeTeam="Nürnberg", AwayTeam="Bayern Munich")],
        BASE_COLS, encoding="latin-1",
    )
    recs = parse_couk_csv(write(tmp_path, data, "D1_1516.csv"), "D1", 2015)
    assert recs[0]["league"] == "BL1"
    assert recs[0]["home_team"] == "1. FC Nürnberg"
    assert recs[0]["away_team"] == "FC Bayern München"


def test_unplayed_and_blank_rows_skipped(tmp_path):
    data = make_csv(
        [row(), row(FTHG="", FTAG="", FTR=""), row(Date=""), row(HomeTeam="")],
        BASE_COLS, trailing=True,
    )
    assert len(parse_couk_csv(write(tmp_path, data), "E0", 2023)) == 1


def test_result_derived_when_ftr_missing(tmp_path):
    data = make_csv([row(FTR="", FTHG="0", FTAG="2")], BASE_COLS)
    assert parse_couk_csv(write(tmp_path, data), "E0", 2023)[0]["result"] == "A"


SHOT_KEYS = ("home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target")


def test_shots_parsed_and_missing_are_none(tmp_path):
    cols = BASE_COLS + ["HS", "AS", "HST", "AST"]
    data = make_csv(
        [
            row(HS="14", AS="9", HST="5", AST="3"),
            row(HomeTeam="Chelsea", AwayTeam="Everton"),  # no shots at all
            row(HomeTeam="Fulham", AwayTeam="Leeds", HS="10", AS="", HST="4", AST=""),
        ],
        cols,
    )
    a, b, c = parse_couk_csv(write(tmp_path, data), "E0", 2023)
    assert tuple(a[k] for k in SHOT_KEYS) == (14, 9, 5, 3)
    assert all(b[k] is None for k in SHOT_KEYS)
    assert tuple(c[k] for k in SHOT_KEYS) == (10, None, 4, None)


def test_no_shot_or_odds_columns_at_all(tmp_path):
    rec = parse_couk_csv(write(tmp_path, make_csv([row()], BASE_COLS)), "E0", 2023)[0]
    assert rec["home_shots"] is None and rec["odds_source"] is None and rec["odds_home"] is None


ODDS_COLS = [
    "PSCH", "PSCD", "PSCA", "AvgCH", "AvgCD", "AvgCA", "B365CH", "B365CD", "B365CA",
    "PSH", "PSD", "PSA", "AvgH", "AvgD", "AvgA", "BbAvH", "BbAvD", "BbAvA",
    "B365H", "B365D", "B365A",
]


def triple(ch, cd, ca, h, d, a):
    return {ch: h, cd: d, ca: a}


@pytest.mark.parametrize(
    "cells, expected_source, expected_home",
    [
        (triple("PSCH", "PSCD", "PSCA", "2.10", "3.40", "3.60"), "pinnacle_close", 2.10),
        (triple("AvgCH", "AvgCD", "AvgCA", "2.00", "3.30", "3.50"), "avg_close", 2.00),
        (triple("B365CH", "B365CD", "B365CA", "1.95", "3.50", "3.80"), "b365_close", 1.95),
        (triple("PSH", "PSD", "PSA", "2.20", "3.30", "3.40"), "pinnacle", 2.20),
        (triple("AvgH", "AvgD", "AvgA", "2.15", "3.25", "3.45"), "avg", 2.15),
        (triple("BbAvH", "BbAvD", "BbAvA", "2.05", "3.20", "3.55"), "bbavg", 2.05),
        (triple("B365H", "B365D", "B365A", "1.90", "3.60", "4.00"), "b365", 1.90),
    ],
)
def test_odds_each_link_of_the_chain(cells, expected_source, expected_home):
    h, d, a, source = select_odds(cells)
    assert source == expected_source
    assert h == expected_home and d > 1 and a > 1


def test_odds_chain_prefers_earlier_complete_triple_and_skips_bad_ones(tmp_path):
    rows = [
        # everything present -> Pinnacle closing wins
        row(**{**triple("PSCH", "PSCD", "PSCA", "2.1", "3.4", "3.6"),
               **triple("B365H", "B365D", "B365A", "1.9", "3.6", "4.0")}),
        # Pinnacle closing partial (draw missing) -> market average closing
        row(HomeTeam="Chelsea", AwayTeam="Everton",
            **{"PSCH": "2.1", "PSCA": "3.6",
               **triple("AvgCH", "AvgCD", "AvgCA", "2.0", "3.3", "3.5")}),
        # Pinnacle closing has an invalid price <= 1.0 -> next link
        row(HomeTeam="Fulham", AwayTeam="Leeds",
            **{**triple("PSCH", "PSCD", "PSCA", "1.0", "3.4", "3.6"),
               **triple("B365CH", "B365CD", "B365CA", "1.8", "3.7", "4.4")}),
        # non-numeric junk -> falls through to the last link
        row(HomeTeam="Burnley", AwayTeam="Luton",
            **{**triple("PSCH", "PSCD", "PSCA", "NA", "x", ""),
               **triple("B365H", "B365D", "B365A", "2.5", "3.2", "2.9")}),
        # nothing usable
        row(HomeTeam="Brentford", AwayTeam="Arsenal"),
    ]
    recs = parse_couk_csv(write(tmp_path, make_csv(rows, BASE_COLS + ODDS_COLS)), "E0", 2023)
    assert [r["odds_source"] for r in recs] == [
        "pinnacle_close", "avg_close", "b365_close", "b365", None
    ]
    assert (recs[0]["odds_home"], recs[0]["odds_draw"], recs[0]["odds_away"]) == (2.1, 3.4, 3.6)
    assert recs[4]["odds_home"] is None and recs[4]["odds_draw"] is None


def test_parse_dataframe_input():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(
        [
            {"Div": "SP1", "Date": "20/08/2023", "Time": "20:00", "HomeTeam": "Ath Madrid",
             "AwayTeam": "Sevilla", "FTHG": 2, "FTAG": float("nan"), "FTR": "H"},
            {"Div": "SP1", "Date": "21/08/2023", "Time": None, "HomeTeam": "Betis",
             "AwayTeam": "Girona", "FTHG": 1.0, "FTAG": 1.0, "FTR": "D"},
        ]
    )
    recs = parse_couk_csv(df, "SP1", 2023)
    assert len(recs) == 1  # NaN away goals => unplayed, skipped
    assert recs[0]["home_team"] == "Real Betis Balompié" and recs[0]["home_goals"] == 1


def test_unknown_division_rejected(tmp_path):
    with pytest.raises(ValueError):
        parse_couk_csv(write(tmp_path, make_csv([row()], BASE_COLS)), "XX", 2023)


# ---------------------------------------------------------------------------
# download_season (HTTP mocked - nothing touches the network)
# ---------------------------------------------------------------------------

@responses.activate
def test_download_season_saves_file(tmp_path):
    body = make_csv([row()], BASE_COLS)
    responses.add(responses.GET, "https://www.football-data.co.uk/mmz4281/2324/E0.csv", body=body)
    dest = download_season(2023, "E0", tmp_path / "couk")
    assert dest == tmp_path / "couk" / "E0_2324.csv"
    assert dest.read_bytes() == body
    assert len(responses.calls) == 1


@responses.activate
def test_download_season_404_raises_and_writes_nothing(tmp_path):
    responses.add(responses.GET, "https://www.football-data.co.uk/mmz4281/3031/E0.csv", status=404)
    with pytest.raises(requests.HTTPError):
        download_season(2030, "E0", tmp_path)
    assert list(tmp_path.iterdir()) == []
