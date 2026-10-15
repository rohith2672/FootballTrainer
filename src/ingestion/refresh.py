"""Weekly data refresh.

    python -m src.ingestion.refresh

Re-downloads the CURRENT season's football-data.co.uk CSVs for the five domestic
divisions (E0, SP1, I1, D1, F1) and fetches the current season's finished
matches for all six competitions from football-data.org (PL PD SA BL1 FL1 CL),
then upserts both.  Safe to re-run: unchanged rows are left untouched, corrected
results and newly published shots/odds are merged in, and a NULL never
overwrites a stored value.

Requires DATABASE_URL and FOOTBALL_DATA_API_KEY.  football-data.org calls go
through the 10 requests/minute limiter in ``api_client`` (6 calls here).
Other seasons are not touched; use ``python -m src.ingestion.ingest`` for
backfills.
"""

from __future__ import annotations

import logging

from src.ingestion import csv_history
from src.ingestion.ingest import (
    ALL_LEAGUES,
    DOMESTIC_LEAGUES,
    current_season,
    ingest_couk,
    ingest_fdorg,
)

logger = logging.getLogger(__name__)


def refresh(raw_dir=csv_history.DEFAULT_RAW_DIR, session=None) -> dict:
    season = current_season()
    summary = {
        "season": season,
        "couk": ingest_couk(
            DOMESTIC_LEAGUES, [season], raw_dir, download=True, force_download=True, session=session
        ),
        "fdorg": ingest_fdorg(ALL_LEAGUES, [season], session=session),
    }
    logger.info("Refresh summary: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    refresh()
