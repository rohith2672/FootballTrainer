"""Canonical team names.

The canonical name of a team is the name football-data.org (API v4) uses,
because that is what the upcoming-fixtures API and the existing database rows
carry.  football-data.co.uk uses short names ("Man United", "Ath Madrid"), so
this module maps those onto the canonical names.

Resolution order in :func:`to_canonical`:

1. explicit per-league mapping of co.uk names (``COUK_TO_CANONICAL``),
2. the name is already a canonical name,
3. normalisation fallback (accents, case, FC/CF/AC/SSC/AS/1. ... stripped),
4. unmapped: the stripped input is returned unchanged.

Only 1 and 2 are considered "known"; :func:`unmapped_names` reports names that
resolved through 3 or not at all, so they can be reviewed and added to the map.

UNCERTAIN MAPPINGS
------------------
Written from memory of the football-data.org naming style, NOT verified against
live API data.  Canonical values that need checking against
``GET /v4/competitions/{code}/teams`` (the ones marked ``# ?`` below) are:
RC Deportivo de La Coruña, Real Sporting de Gijón, Córdoba CF, Real Oviedo,
Pescara (Delfino Pescara 1936), Carpi FC 1909, AC ChievoVerona, SPAL 2013,
US Salernitana 1919, Como 1907, Hellas Verona FC, DSC Arminia Bielefeld,
Fortuna Düsseldorf, SpVgg Greuther Fürth, FC St. Pauli 1910, Holstein Kiel,
FC Ingolstadt 04, Hamburger SV, AS Nancy Lorraine, AC Ajaccio vs GFC Ajaccio,
Nîmes Olympique, Paris FC, FC Crotone, Palermo FC, Brescia Calcio,
Huddersfield Town AFC, Hull City AFC, Queens Park Rangers FC, AFC Bournemouth.
"""

from __future__ import annotations

import re
import unicodedata

# co.uk short name -> football-data.org canonical name, per league code.
COUK_TO_CANONICAL: dict[str, dict[str, str]] = {
    "PL": {
        "Arsenal": "Arsenal FC",
        "Aston Villa": "Aston Villa FC",
        "Bournemouth": "AFC Bournemouth",
        "Brentford": "Brentford FC",
        "Brighton": "Brighton & Hove Albion FC",
        "Burnley": "Burnley FC",
        "Cardiff": "Cardiff City FC",
        "Chelsea": "Chelsea FC",
        "Crystal Palace": "Crystal Palace FC",
        "Everton": "Everton FC",
        "Coventry": "Coventry City FC",  # ?
        "Fulham": "Fulham FC",
        "Huddersfield": "Huddersfield Town AFC",
        "Hull": "Hull City AFC",
        "Ipswich": "Ipswich Town FC",
        "Leeds": "Leeds United FC",
        "Leicester": "Leicester City FC",
        "Liverpool": "Liverpool FC",
        "Luton": "Luton Town FC",
        "Man City": "Manchester City FC",
        "Man United": "Manchester United FC",
        "Middlesbrough": "Middlesbrough FC",
        "Newcastle": "Newcastle United FC",
        "Norwich": "Norwich City FC",
        "Nott'm Forest": "Nottingham Forest FC",
        "QPR": "Queens Park Rangers FC",
        "Sheffield United": "Sheffield United FC",
        "Sheffield Utd": "Sheffield United FC",
        "Southampton": "Southampton FC",
        "Stoke": "Stoke City FC",
        "Sunderland": "Sunderland AFC",
        "Swansea": "Swansea City AFC",
        "Tottenham": "Tottenham Hotspur FC",
        "Watford": "Watford FC",
        "West Brom": "West Bromwich Albion FC",
        "West Ham": "West Ham United FC",
        "Wolves": "Wolverhampton Wanderers FC",
    },
    "PD": {
        "Alaves": "Deportivo Alavés",
        "Almeria": "UD Almería",
        "Ath Bilbao": "Athletic Club",
        "Ath Madrid": "Club Atlético de Madrid",
        "Barcelona": "FC Barcelona",
        "Betis": "Real Betis Balompié",
        "Cadiz": "Cádiz CF",
        "Celta": "RC Celta de Vigo",
        "Cordoba": "Córdoba CF",  # ?
        "Eibar": "SD Eibar",
        "Elche": "Elche CF",
        "Espanol": "RCD Espanyol de Barcelona",
        "Getafe": "Getafe CF",
        "Girona": "Girona FC",
        "Granada": "Granada CF",
        "Huesca": "SD Huesca",
        "La Coruna": "RC Deportivo de La Coruña",  # ?
        "Las Palmas": "UD Las Palmas",
        "Leganes": "CD Leganés",
        "Levante": "Levante UD",
        "Malaga": "Málaga CF",
        "Mallorca": "RCD Mallorca",
        "Osasuna": "CA Osasuna",
        "Oviedo": "Real Oviedo",  # ?
        "Real Madrid": "Real Madrid CF",
        "Santander": "Real Racing Club de Santander",  # ?
        "Sevilla": "Sevilla FC",
        "Sociedad": "Real Sociedad de Fútbol",
        "Sp Gijon": "Real Sporting de Gijón",  # ?
        "Valencia": "Valencia CF",
        "Valladolid": "Real Valladolid CF",
        "Vallecano": "Rayo Vallecano de Madrid",
        "Villarreal": "Villarreal CF",
    },
    "SA": {
        "Atalanta": "Atalanta BC",
        "Benevento": "Benevento Calcio",
        "Bologna": "Bologna FC 1909",
        "Brescia": "Brescia Calcio",  # ?
        "Cagliari": "Cagliari Calcio",
        "Carpi": "Carpi FC 1909",  # ?
        "Chievo": "AC ChievoVerona",  # ?
        "Como": "Como 1907",  # ?
        "Cremonese": "US Cremonese",
        "Crotone": "FC Crotone",  # ?
        "Empoli": "Empoli FC",
        "Fiorentina": "ACF Fiorentina",
        "Frosinone": "Frosinone Calcio",
        "Genoa": "Genoa CFC",
        "Inter": "FC Internazionale Milano",
        "Juventus": "Juventus FC",
        "Lazio": "SS Lazio",
        "Lecce": "US Lecce",
        "Milan": "AC Milan",
        "Monza": "AC Monza",
        "Napoli": "SSC Napoli",
        "Palermo": "Palermo FC",  # ?
        "Parma": "Parma Calcio 1913",
        "Pescara": "Delfino Pescara 1936",  # ?
        "Pisa": "AC Pisa 1909",
        "Roma": "AS Roma",
        "Salernitana": "US Salernitana 1919",  # ?
        "Sampdoria": "UC Sampdoria",
        "Sassuolo": "US Sassuolo Calcio",
        "Spal": "SPAL 2013",  # ?
        "Spezia": "Spezia Calcio",
        "Torino": "Torino FC",
        "Udinese": "Udinese Calcio",
        "Venezia": "Venezia FC",
        "Verona": "Hellas Verona FC",
    },
    "BL1": {
        "Augsburg": "FC Augsburg",
        "Bayern Munich": "FC Bayern München",
        "Bielefeld": "DSC Arminia Bielefeld",  # ?
        "Bochum": "VfL Bochum 1848",
        "Darmstadt": "SV Darmstadt 98",
        "Dortmund": "Borussia Dortmund",
        "Ein Frankfurt": "Eintracht Frankfurt",
        "Elversberg": "SV 07 Elversberg",  # ?
        "FC Koln": "1. FC Köln",
        "Fortuna Dusseldorf": "Fortuna Düsseldorf",  # ?
        "Freiburg": "SC Freiburg",
        "Greuther Furth": "SpVgg Greuther Fürth",  # ?
        "Hamburg": "Hamburger SV",  # ?
        "Hannover": "Hannover 96",
        "Heidenheim": "1. FC Heidenheim 1846",
        "Hertha": "Hertha BSC",
        "Hoffenheim": "TSG 1899 Hoffenheim",
        "Holstein Kiel": "Holstein Kiel",  # ?
        "Ingolstadt": "FC Ingolstadt 04",  # ?
        "Leverkusen": "Bayer 04 Leverkusen",
        "M'gladbach": "Borussia Mönchengladbach",
        "Mainz": "1. FSV Mainz 05",
        "Nurnberg": "1. FC Nürnberg",
        "Paderborn": "SC Paderborn 07",
        "RB Leipzig": "RB Leipzig",
        "Schalke 04": "FC Schalke 04",
        "St Pauli": "FC St. Pauli 1910",  # ?
        "Stuttgart": "VfB Stuttgart",
        "Union Berlin": "1. FC Union Berlin",
        "Werder Bremen": "SV Werder Bremen",
        "Wolfsburg": "VfL Wolfsburg",
    },
    "FL1": {
        "Ajaccio": "AC Ajaccio",  # ?
        "Ajaccio GFCO": "GFC Ajaccio",  # ?
        "Amiens": "Amiens SC",
        "Angers": "Angers SCO",
        "Auxerre": "AJ Auxerre",
        "Bastia": "SC Bastia",
        "Bordeaux": "FC Girondins de Bordeaux",
        "Brest": "Stade Brestois 29",
        "Caen": "SM Caen",
        "Clermont": "Clermont Foot 63",
        "Dijon": "Dijon FCO",
        "Guingamp": "EA Guingamp",
        "Le Havre": "Le Havre AC",
        "Le Mans": "Le Mans FC",  # ?
        "Lens": "RC Lens",
        "Lille": "Lille OSC",
        "Lorient": "FC Lorient",
        "Lyon": "Olympique Lyonnais",
        "Marseille": "Olympique de Marseille",
        "Metz": "FC Metz",
        "Monaco": "AS Monaco FC",
        "Montpellier": "Montpellier HSC",
        "Nancy": "AS Nancy Lorraine",  # ?
        "Nantes": "FC Nantes",
        "Nice": "OGC Nice",
        "Nimes": "Nîmes Olympique",  # ?
        "Paris FC": "Paris FC",  # ?
        "Paris SG": "Paris Saint-Germain FC",
        "Reims": "Stade de Reims",
        "Rennes": "Stade Rennais FC 1901",
        "St Etienne": "AS Saint-Étienne",
        "Strasbourg": "RC Strasbourg Alsace",
        "Toulouse": "Toulouse FC",
        "Troyes": "ESTAC Troyes",
    },
}

CANONICAL_NAMES: frozenset[str] = frozenset(
    canonical for league_map in COUK_TO_CANONICAL.values() for canonical in league_map.values()
)

# --------------------------------------------------------------------------
# Normalisation fallback
# --------------------------------------------------------------------------

_STOP_TOKENS = frozenset(
    {
        "fc", "cf", "ac", "afc", "sc", "ssc", "as", "ud", "cd", "rcd", "rc", "sd", "ca",
        "sv", "vfl", "vfb", "fsv", "tsg", "us", "uc", "ss", "ogc", "asc", "bc", "cfc",
        "sco", "ec", "fk", "bsc", "sk", "ssd", "calcio", "club", "the",
    }
)

_CHAR_FIXES = str.maketrans({"ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ł": "l", "đ": "d"})


def normalize_name(name: str) -> str:
    """Lower-case, accent-free, punctuation-free key with club-prefix noise removed.

    Pure-digit tokens (founding years like 1909, 04, 96) are dropped as well.
    """
    text = unicodedata.normalize("NFKD", name.translate(_CHAR_FIXES))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in _STOP_TOKENS and not t.isdigit()]
    return " ".join(tokens)


def _build_fallback_index() -> dict[str, str]:
    index: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(key: str, canonical: str) -> None:
        if not key or key in ambiguous:
            return
        if key in index and index[key] != canonical:
            ambiguous.add(key)
            del index[key]
            return
        index[key] = canonical

    for league_map in COUK_TO_CANONICAL.values():
        for couk, canonical in league_map.items():
            add(normalize_name(canonical), canonical)
            add(normalize_name(couk), canonical)
    return index


_FALLBACK_INDEX = _build_fallback_index()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def resolve(name: str, league: str | None = None) -> tuple[str, str]:
    """Return (canonical_name, how) where how is map|canonical|fallback|unmapped."""
    clean = " ".join(str(name).split())
    if league and clean in COUK_TO_CANONICAL.get(league, {}):
        return COUK_TO_CANONICAL[league][clean], "map"
    if clean in CANONICAL_NAMES:
        return clean, "canonical"
    if league is None:
        hits = {m[clean] for m in COUK_TO_CANONICAL.values() if clean in m}
        if len(hits) == 1:
            return hits.pop(), "map"
    key = normalize_name(clean)
    if key in _FALLBACK_INDEX:
        return _FALLBACK_INDEX[key], "fallback"
    return clean, "unmapped"


def to_canonical(name: str, league: str | None = None) -> str:
    """Map a football-data.co.uk team name to the football-data.org name."""
    return resolve(name, league)[0]


def unmapped_names(names, league: str | None = None) -> dict[str, str]:
    """Names that did not resolve through the explicit map.

    Returns {name: "fallback" | "unmapped"}; use it to review/extend the map.
    """
    out: dict[str, str] = {}
    for name in names:
        _, how = resolve(name, league)
        if how in ("fallback", "unmapped"):
            out[name] = how
    return out


def unknown_canonical(names) -> list[str]:
    """football-data.org names (e.g. from the DB or API) not in CANONICAL_NAMES.

    Use against live API data to find map entries whose canonical spelling is wrong.
    """
    return sorted({n for n in names if n not in CANONICAL_NAMES})
