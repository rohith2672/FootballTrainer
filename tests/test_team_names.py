import pytest

from src.ingestion.team_names import (
    CANONICAL_NAMES,
    COUK_TO_CANONICAL,
    normalize_name,
    to_canonical,
    unknown_canonical,
    unmapped_names,
)

SAMPLES = {
    "PL": {
        "Man United": "Manchester United FC",
        "Man City": "Manchester City FC",
        "Wolves": "Wolverhampton Wanderers FC",
        "Brighton": "Brighton & Hove Albion FC",
        "Nott'm Forest": "Nottingham Forest FC",
        "Sheffield United": "Sheffield United FC",
        "Tottenham": "Tottenham Hotspur FC",
        "West Brom": "West Bromwich Albion FC",
        "Newcastle": "Newcastle United FC",
        "Arsenal": "Arsenal FC",
    },
    "PD": {
        "Ath Madrid": "Club Atlético de Madrid",
        "Ath Bilbao": "Athletic Club",
        "Barcelona": "FC Barcelona",
        "Sociedad": "Real Sociedad de Fútbol",
        "Vallecano": "Rayo Vallecano de Madrid",
        "Espanol": "RCD Espanyol de Barcelona",
        "Real Madrid": "Real Madrid CF",
        "Betis": "Real Betis Balompié",
    },
    "SA": {
        "Inter": "FC Internazionale Milano",
        "Milan": "AC Milan",
        "Roma": "AS Roma",
        "Napoli": "SSC Napoli",
        "Verona": "Hellas Verona FC",
        "Juventus": "Juventus FC",
        "Sampdoria": "UC Sampdoria",
    },
    "BL1": {
        "Bayern Munich": "FC Bayern München",
        "M'gladbach": "Borussia Mönchengladbach",
        "Ein Frankfurt": "Eintracht Frankfurt",
        "Leverkusen": "Bayer 04 Leverkusen",
        "FC Koln": "1. FC Köln",
        "Mainz": "1. FSV Mainz 05",
        "Hoffenheim": "TSG 1899 Hoffenheim",
        "Dortmund": "Borussia Dortmund",
    },
    "FL1": {
        "Paris SG": "Paris Saint-Germain FC",
        "Marseille": "Olympique de Marseille",
        "Lyon": "Olympique Lyonnais",
        "St Etienne": "AS Saint-Étienne",
        "Monaco": "AS Monaco FC",
        "Brest": "Stade Brestois 29",
        "Rennes": "Stade Rennais FC 1901",
    },
}


@pytest.mark.parametrize(
    "league, couk, expected",
    [(lg, c, e) for lg, m in SAMPLES.items() for c, e in m.items()],
)
def test_couk_names_map_to_canonical(league, couk, expected):
    assert to_canonical(couk, league) == expected
    # league-less lookup resolves the same for unambiguous names
    assert to_canonical(couk) == expected


def test_canonical_names_pass_through():
    for name in ("Arsenal FC", "Club Atlético de Madrid", "Paris Saint-Germain FC"):
        assert to_canonical(name, "PL") == name


def test_whitespace_is_collapsed():
    assert to_canonical("  Man   United ", "PL") == "Manchester United FC"


def test_normalisation_fallback_and_reporting():
    # not in the explicit map, but normalises to a canonical name
    assert to_canonical("STOKE CITY fc", "PL") == "Stoke City FC"
    report = unmapped_names(["Man United", "STOKE CITY fc", "Totally Unknown XI"], "PL")
    assert report == {"STOKE CITY fc": "fallback", "Totally Unknown XI": "unmapped"}
    assert to_canonical("Totally Unknown XI", "PL") == "Totally Unknown XI"


def test_normalize_name_strips_noise():
    assert normalize_name("Bayer 04 Leverkusen") == "bayer leverkusen"
    assert normalize_name("Real Betis Balompié") == "real betis balompie"
    assert normalize_name("FC Köln") == "koln"
    assert normalize_name("Brighton & Hove Albion FC") == "brighton and hove albion"


def test_canonical_values_are_unique_per_league_and_nonempty():
    for league, mapping in COUK_TO_CANONICAL.items():
        assert mapping, league
        # no two distinct co.uk names (other than known aliases) share a target by accident
        values = list(mapping.values())
        dupes = {v for v in values if values.count(v) > 1}
        assert dupes <= {"Sheffield United FC"}, (league, dupes)


def test_unknown_canonical():
    assert unknown_canonical(["Arsenal FC", "Celtic FC"]) == ["Celtic FC"]
    assert "Arsenal FC" in CANONICAL_NAMES
