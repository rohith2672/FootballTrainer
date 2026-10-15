import numpy as np
import pandas as pd
import pytest

from src.model.train import (
    chronological_slices,
    compute_sample_weights,
    make_splits,
    sort_chronological,
    split_by_date,
)
from tests.helpers_model import make_matches


def _assert_chronological(plan):
    df = plan.df
    for tr, va in plan.folds:
        assert df.iloc[tr]["date"].max() < df.iloc[va]["date"].min()
        assert tr.max() < va.min()
        assert plan.holdout_start > va.max()
    assert plan.dev["date"].max() < plan.holdout["date"].min()


def test_season_mode_holds_out_last_season_and_folds_by_season():
    df = make_matches(seasons=(2018, 2019, 2020, 2021, 2022), per_season=120)
    plan = make_splits(df)
    assert plan.mode == "season"
    assert set(plan.holdout["season"]) == {2022}
    assert plan.fold_labels == ["season 2019", "season 2020", "season 2021"]
    for (tr, va), s in zip(plan.folds, (2019, 2020, 2021)):
        assert set(plan.df.iloc[va]["season"]) == {s}
        assert plan.df.iloc[tr]["season"].max() < s
    _assert_chronological(plan)


def test_three_seasons_hold_out_last_season_with_date_folds():
    df = make_matches(seasons=(2020, 2021, 2022), per_season=150)
    plan = make_splits(df)
    assert plan.mode == "season_holdout+date_folds"
    assert set(plan.holdout["season"]) == {2022}
    assert len(plan.folds) >= 2
    _assert_chronological(plan)


def test_two_seasons_fall_back_to_date_blocks():
    df = make_matches(seasons=(2021, 2022), per_season=200)
    plan = make_splits(df)
    assert plan.mode == "date"
    assert len(plan.folds) >= 2
    assert len(plan.holdout) == pytest.approx(0.2 * len(df), abs=6)
    _assert_chronological(plan)


def test_no_season_column_uses_date_mode():
    df = make_matches(seasons=(2021, 2022), per_season=100, with_season=False)
    plan = make_splits(df)
    assert plan.mode == "date"
    _assert_chronological(plan)


def test_partial_trailing_season_goes_to_holdout_not_dev():
    df = make_matches(seasons=(2018, 2019, 2020, 2021, 2022), per_season=150)
    last = df[df["season"] == 2022].head(20)  # in-progress season
    df = pd.concat([df[df["season"] != 2022], last], ignore_index=True)
    plan = make_splits(df)
    assert plan.holdout_partial
    assert set(plan.holdout["season"]) == {2021, 2022}
    assert 2021 not in set(plan.dev["season"])
    _assert_chronological(plan)


def test_cuts_never_split_a_single_date():
    # every date has many matches, so row-count cutoffs would land mid-date
    df = make_matches(seasons=(2021, 2022), per_season=200, with_season=False)
    assert df["date"].duplicated().any()
    plan = make_splits(df)
    dates = plan.df["date"]
    hs = plan.holdout_start
    assert dates.iloc[hs - 1] < dates.iloc[hs]
    for tr, va in plan.folds:
        assert dates.iloc[tr.max()] < dates.iloc[va.min()]
    train, test = split_by_date(df, 0.2)
    assert train["date"].max() < test["date"].min()


def test_all_same_dates_in_block_stay_together_in_slices():
    df = make_matches(seasons=(2021,), per_season=150, with_season=False)
    a, b, c = chronological_slices(df)
    assert a["date"].max() < b["date"].min()
    assert b["date"].max() < c["date"].min()
    assert len(a) + len(b) + len(c) == len(df)


def test_sort_is_deterministic_with_tiebreak():
    df = make_matches(seasons=(2021,), per_season=60)
    shuffled = df.sample(frac=1.0, random_state=3)
    a = sort_chronological(df)
    b = sort_chronological(shuffled)
    pd.testing.assert_frame_equal(a, b)


def test_too_little_data_raises():
    with pytest.raises(ValueError):
        make_splits(make_matches(seasons=(2021,), per_season=10))


def test_sample_weights_are_recency_weighted_and_mean_one():
    df = make_matches(seasons=(2020, 2021), per_season=60)
    w = compute_sample_weights(sort_chronological(df))
    assert w.mean() == pytest.approx(1.0)
    assert w[-1] > w[0]
    assert np.all(w > 0)
