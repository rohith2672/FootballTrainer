"""Select the installed PostgreSQL driver consistently across SQLAlchemy versions."""

from sqlalchemy.engine import make_url


def sqlalchemy_url(value: str) -> str:
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg2")
        return url.render_as_string(hide_password=False)
    return value
