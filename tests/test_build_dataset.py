import datetime
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.features import build_dataset as B
from src.features.build_dataset import OUTPUT_COLS, RESULT_MAP, build_dataset, build_features
from src.features.columns import FEATURE_COLS
from tests.helpers_features import make_league_matches


def _m(id_, date, home, away, hg, ag, result, season=2023, league="PL", **kw):
    base = dict(
        id=id_, date=datetime.datetime.strptime(date, "%Y-%m-%d"), kickoff=None, season=season, league=league,
        home_team=home, away_team=away, home_goals=hg, away_goals=ag, result=result,
        home_shots=None, away_shots=None, home_shots_on_target=None, away_shots_on_target=None,
        odds_home=None, odds_draw=None, odds_away=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _session(matches):
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value.order_by.return_value.all.return_value = matches
    return session


def _multi_season_matches():
    return make_league_matches(leagues=("PL", "PD"), seasons=(2018, 2019, 2020), n_teams=6, with_cl=True, seed=2)


def test_result_map_values():
    assert RESULT_MAP == {"H": 0, "D": 1, "A": 2}


def test_output_columns_order_and_target_encoding():
    df = build_features(_multi_season_matches())
    assert list(df.columns) == OUTPUT_COLS
    assert OUTPUT_COLS[-len(FEATURE_COLS):] == FEATURE_COLS
    assert set(df["target"].unique()) == {0, 1, 2}
    assert "result" not in df.columns


def test_target_matches_goals():
    m = _multi_season_matches()
    df = build_features(m, burn_in_seasons=0).set_index("match_id")
    mm = m.set_index("id")
    expected = np.sign(mm["away_goals"] - mm["home_goals"]) + 1   # H->0, D->1, A->2
    assert (df["target"] == expected.loc[df.index]).all()


def test_burn_in_drops_each_leagues_first_season_and_cl_follows_domestic():
    m = _multi_season_matches()
    kept = build_features(m, burn_in_seasons=1)
    assert kept["season"].min() == 2019
    assert set(kept["league"]) == {"PL", "PD", "CL"}
    assert len(build_features(m, burn_in_seasons=0)) == len(m)
    assert build_features(m, burn_in_seasons=0)["season"].min() == 2018


def test_burn_in_is_per_league():
    pl = make_league_matches(leagues=("PL",), seasons=(2018, 2019, 2020), n_teams=4)
    sa = make_league_matches(leagues=("SA",), seasons=(2019, 2020), n_teams=4, start_id=10_000)
    kept = build_features(pd.concat([pl, sa], ignore_index=True), burn_in_seasons=1)
    assert kept[kept["league"] == "PL"]["season"].min() == 2019
    assert kept[kept["league"] == "SA"]["season"].min() == 2020


def test_nans_are_kept_not_dropped():
    df = build_features(_multi_season_matches(), burn_in_seasons=0)
    assert len(df) == len(_multi_season_matches())
    assert df["home_shots_for_avg"].isna().all()          # no shots data at all -> NaN, not 0
    assert df["odds_home"].isna().all()


def test_odds_are_passed_through():
    m = make_league_matches(seasons=(2019,), n_teams=4)
    m["odds_home"], m["odds_draw"], m["odds_away"] = 2.0, 3.4, 3.9
    df = build_features(m, burn_in_seasons=0)
    assert (df["odds_home"] == 2.0).all() and (df["odds_away"] == 3.9).all()


def test_build_dataset_from_mock_session_maps_orm_rows():
    matches = [
        _m(1, "2023-08-01", "A", "B", 2, 1, "H", home_shots=12, away_shots=7,
           home_shots_on_target=5, away_shots_on_target=2, odds_home=1.8, odds_draw=3.6, odds_away=4.5),
        _m(2, "2023-08-02", "C", "D", 0, 0, "D"),
        _m(3, "2023-08-08", "A", "C", 1, 2, "A"),
    ]
    df = build_dataset(db_session=_session(matches), burn_in_seasons=0)
    assert list(df["match_id"]) == [1, 2, 3]
    assert list(df["target"]) == [0, 1, 2]
    assert df.loc[0, "odds_home"] == 1.8 and math.isnan(df.loc[1, "odds_home"])
    assert df.loc[2, "home_shots_for_avg"] == 12                  # A's shots from game 1
    assert math.isnan(df.loc[1, "home_shots_for_avg"])


def test_main_writes_csv_and_prints_summary(tmp_path, capsys):
    out = tmp_path / "nested" / "features.csv"
    session = _session([_m(i + 1, f"2023-08-{i + 1:02d}", "A", "B", 1, 0, "H") for i in range(5)])
    df = B.main(output_path=str(out), db_session=session, burn_in_seasons=0)
    text = capsys.readouterr().out
    assert out.exists() and len(pd.read_csv(out)) == len(df) == 5
    assert "Class distribution" in text and "Home Win" in text and "PL: 5" in text
    back = pd.read_csv(out)
    assert list(back.columns) == OUTPUT_COLS


def test_load_matches_from_csv_and_no_db_build(tmp_path, capsys):
    header = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HST,AST,B365H,B365D,B365A"
    (tmp_path / "E0_1819.csv").write_text("\n".join([
        header,
        "E0,10/08/2018,20:00,Man United,Leicester,2,1,H,8,13,6,4,1.57,3.9,7.5",
        "E0,11/08/2018,12:30,Bournemouth,Cardiff,2,0,H,,,,,2.0,3.5,4.0",
        "E0,11/08/2018,12:30,Bournemouth,Cardiff,2,0,H,,,,,2.0,3.5,4.0",      # duplicate row
        "E0,12/08/2018,,Arsenal,Chelsea,,,,,,,,,,",                          # unplayed -> skipped
        "",
    ]))
    (tmp_path / "E0_1920.csv").write_text("\n".join([
        header,
        "E0,09/08/2019,20:00,Liverpool,Norwich,4,1,H,15,12,7,5,1.2,7.0,15.0",
        "E0,10/08/2019,12:30,West Ham,Man City,0,5,A,5,20,2,10,9.0,6.0,1.3",
    ]))
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / "E0_1920.csv.bak").write_text("ignored")

    m = B.load_matches_from_csv(str(tmp_path))
    assert list(m.columns) == B._MATCH_ATTRS
    assert len(m) == 4 and list(m["id"]) == [1, 2, 3, 4]
    assert set(m["league"]) == {"PL"} and list(m["season"]) == [2018, 2018, 2019, 2019]
    assert m["date"].is_monotonic_increasing and m["date"].dt.tz is None
    assert m.loc[0, "home_goals"] == 2 and m.loc[0, "odds_home"] == 1.57 and m.loc[0, "home_shots"] == 8

    # same engine / target / burn-in path as the DB build
    df = build_dataset(csv_dir=str(tmp_path), burn_in_seasons=0)
    assert list(df.columns) == OUTPUT_COLS
    assert list(df["target"]) == [0, 0, 0, 2]
    assert df.loc[2, "home_form_n"] == 0            # Liverpool has no prior match in this tiny set
    kept = build_dataset(csv_dir=str(tmp_path), burn_in_seasons=1)
    assert set(kept["season"]) == {2019}

    out = tmp_path / "out" / "features.csv"
    B.main(output_path=str(out), burn_in_seasons=0, csv_dir=str(tmp_path))
    assert list(pd.read_csv(out).columns) == OUTPUT_COLS
    assert pd.api.types.is_datetime64_any_dtype(pd.read_csv(out, parse_dates=["date"])["date"])   # mixed midnight / timed
    assert "PL: 4" in capsys.readouterr().out


def test_load_matches_from_csv_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        B.load_matches_from_csv(str(tmp_path))
